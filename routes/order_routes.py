import time
from flask import Blueprint, request, jsonify
from extensions import db_service, admin_or_coach_required

order_bp = Blueprint('order', __name__)

@order_bp.route('/api/admin/orders', methods=['GET'])
@admin_or_coach_required
def api_admin_orders():
    """取得所有訂單列表"""
    orders = db_service.get_all_orders()
    return jsonify({"status": "success", "data": orders})

@order_bp.route('/api/admin/orders/<order_id>/ship', methods=['POST'])
@admin_or_coach_required
def api_admin_orders_ship(order_id):
    """寄送結算：接收逐商品明細（含設計者/包裝人員/耗材），快照寫入並更新訂單狀態"""
    data = request.get_json() or {}
    products = data.get('products')
    if not isinstance(products, list) or not products:
        return jsonify({"status": "error", "message": "缺少逐商品結算明細"}), 400

    # 驗證設計者/包裝人員為可分配角色（admin / assistant_coach）
    eligible = {
        u['id'] for u in db_service.get_all_users()
        if u.get('role') in ('admin', 'assistant_coach')
    }
    order_totals = {"other_cost": 0.0, "shipping_cost": 0.0, "net_profit": 0.0}
    for p in products:
        if not isinstance(p, dict):
            return jsonify({"status": "error", "message": "結算明細格式錯誤"}), 400
        if p.get('designer_user_id') and p.get('designer_user_id') not in eligible:
            return jsonify({"status": "error", "message": "請選擇有效的設計者"}), 400
        if p.get('packager_user_id') and p.get('packager_user_id') not in eligible:
            return jsonify({"status": "error", "message": "請選擇有效的包裝人員"}), 400
        order_totals["other_cost"] += float(p.get('other_cost', 0) or 0)
        order_totals["shipping_cost"] += float(p.get('shipping_cost', 0) or 0)
        order_totals["net_profit"] += float(p.get('net_profit', 0) or 0)

    success = db_service.save_order_settlement(str(order_id), products, order_totals)
    if success:
        return jsonify({
            "status": "success",
            "message": f"訂單 #{order_id} 已成功執行寄送，逐商品利潤結算與分潤已存檔！"
        })
    return jsonify({"status": "error", "message": "處理訂單寄送失敗"}), 500

@order_bp.route('/api/admin/orders/<order_id>/cancel', methods=['POST'])
@admin_or_coach_required
def api_admin_orders_cancel(order_id):
    """取消訂單並釋放庫存"""
    ok, msg = db_service.cancel_order(order_id)
    if ok:
        return jsonify({"status": "success", "message": msg})
    return jsonify({"status": "error", "message": msg}), 400

@order_bp.route('/api/admin/orders/<order_id>/update', methods=['POST'])
@admin_or_coach_required
def api_admin_orders_update(order_id):
    """修改訂單明細（數量/單價）：伺服器端重算總額，並同步調整庫存扣減"""
    data = request.get_json() or {}
    items = data.get('items')
    if not isinstance(items, list) or not items:
        return jsonify({"status": "error", "message": "請至少保留一筆商品"}), 400

    for it in items:
        if not isinstance(it, dict):
            return jsonify({"status": "error", "message": "商品資料格式錯誤"}), 400
        try:
            qty = int(it.get('qty') or 0)
            price = float(it.get('price') or 0)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "商品數量或單價格式錯誤"}), 400
        if qty <= 0:
            return jsonify({"status": "error", "message": "商品數量需大於 0"}), 400
        if price < 0:
            return jsonify({"status": "error", "message": "單價不可為負數"}), 400

    ok, msg = db_service.update_order_items(str(order_id), items)
    if ok:
        return jsonify({"status": "success", "message": msg})
    return jsonify({"status": "error", "message": msg}), 400

@order_bp.route('/api/admin/orders/<order_id>/settlement', methods=['GET'])
@admin_or_coach_required
def api_admin_order_settlement(order_id):
    """讀取訂單已存的結算與耗材明細（供已寄送訂單修改時載入）"""
    data = db_service.get_order_settlement(str(order_id))
    return jsonify({"status": "success", "data": data})

@order_bp.route('/api/admin/orders/<order_id>/update-shipment', methods=['POST'])
@admin_or_coach_required
def api_admin_orders_update_shipment(order_id):
    """已寄送訂單修改：更新明細（單價/數量）與結算（設計者/包裝人員/耗材等），重新計算並寫回"""
    t_start = time.time()
    data = request.get_json() or {}
    items = data.get('items')
    products = data.get('products')
    if not isinstance(items, list) or not items:
        return jsonify({"status": "error", "message": "請至少保留一筆商品"}), 400
    if not isinstance(products, list) or not products:
        return jsonify({"status": "error", "message": "缺少逐商品結算明細"}), 400

    for it in items:
        if not isinstance(it, dict):
            return jsonify({"status": "error", "message": "商品資料格式錯誤"}), 400
        try:
            qty = int(it.get('qty') or 0)
            price = float(it.get('price') or 0)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "商品數量或單價格式錯誤"}), 400
        if qty <= 0:
            return jsonify({"status": "error", "message": "商品數量需大於 0"}), 400
        if price < 0:
            return jsonify({"status": "error", "message": "單價不可為負數"}), 400

    eligible = {
        u['id'] for u in db_service.get_all_users()
        if u.get('role') in ('admin', 'assistant_coach')
    }
    order_totals = {"other_cost": 0.0, "shipping_cost": 0.0, "net_profit": 0.0}
    for p in products:
        if not isinstance(p, dict):
            return jsonify({"status": "error", "message": "結算明細格式錯誤"}), 400
        if p.get('designer_user_id') and p.get('designer_user_id') not in eligible:
            return jsonify({"status": "error", "message": "請選擇有效的設計者"}), 400
        if p.get('packager_user_id') and p.get('packager_user_id') not in eligible:
            return jsonify({"status": "error", "message": "請選擇有效的包裝人員"}), 400
        order_totals["other_cost"] += float(p.get('other_cost', 0) or 0)
        order_totals["shipping_cost"] += float(p.get('shipping_cost', 0) or 0)
        order_totals["net_profit"] += float(p.get('net_profit', 0) or 0)

    make_settlement = bool(data.get('make_settlement', True))
    ok, msg = db_service.update_order_settlement(str(order_id), items, products, order_totals, make_settlement)
    print(f"[TIMING] update-shipment {order_id}: total={round((time.time() - t_start) * 1000)}ms ok={ok}")
    if ok:
        return jsonify({"status": "success", "message": msg})
    return jsonify({"status": "error", "message": msg}), 400

# --- Bonus & Platform Revenue APIs ---

@order_bp.route('/api/admin/bonuses', methods=['GET'])
@admin_or_coach_required
def api_admin_bonuses():
    """獎金統計：依結算時間區間回傳每人設計/包裝獎金、明細與平台收益"""
    date_from = request.args.get('from', '').strip()[:10]
    date_to = request.args.get('to', '').strip()[:10]
    from_str = f"{date_from} 00:00:00" if date_from else "1970-01-01 00:00:00"
    to_str = f"{date_to} 23:59:59" if date_to else "9999-12-31 23:59:59"
    summary = db_service.get_bonus_summary(from_str, to_str)
    return jsonify({"status": "success", **summary})

@order_bp.route('/api/admin/platform-revenue', methods=['GET'])
@admin_or_coach_required
def api_admin_platform_revenue():
    """平台收益彙總：依結算時間區間，依商品＋項目彙總各項金額"""
    date_from = request.args.get('from', '').strip()[:10]
    date_to = request.args.get('to', '').strip()[:10]
    from_str = f"{date_from} 00:00:00" if date_from else "1970-01-01 00:00:00"
    to_str = f"{date_to} 23:59:59" if date_to else "9999-12-31 23:59:59"
    data = db_service.get_platform_revenue_summary(from_str, to_str)
    return jsonify({"status": "success", "data": data})

@order_bp.route('/api/admin/platform-revenue/detail', methods=['GET'])
@admin_or_coach_required
def api_admin_platform_revenue_detail():
    """平台收益明細：單一商品＋項目的每一筆結算紀錄"""
    product_id = request.args.get('product_id', '').strip() or None
    item_name = request.args.get('item_name', '').strip()
    if not item_name and product_id is None:
        return jsonify({"status": "error", "message": "請指定商品與項目"}), 400
    date_from = request.args.get('from', '').strip()[:10]
    date_to = request.args.get('to', '').strip()[:10]
    from_str = f"{date_from} 00:00:00" if date_from else "1970-01-01 00:00:00"
    to_str = f"{date_to} 23:59:59" if date_to else "9999-12-31 23:59:59"
    detail = db_service.get_platform_revenue_detail(product_id, item_name, from_str, to_str)
    return jsonify({"status": "success", "data": detail})
