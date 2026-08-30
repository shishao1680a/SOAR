import io
import uuid
from flask import Blueprint, request, jsonify, session
from PIL import Image
from extensions import (
    db_service, material_recognize_service, admin_or_coach_required,
    _validate_upload, ALLOWED_IMAGE_EXTS
)

material_bp = Blueprint('material', __name__)

@material_bp.route('/api/admin/material-purchases', methods=['GET', 'POST'])
@admin_or_coach_required
def api_admin_material_purchases():
    """耗材進貨紀錄查詢與新增"""
    if request.method == 'POST':
        data = request.get_json() or {}
        material_name = data.get('material_name', '').strip()
        total_capacity = data.get('total_capacity', '').strip()
        purchase_cost = float(data.get('purchase_cost', 0))
        purchase_qty = int(data.get('purchase_qty', 0))
        supplier = data.get('supplier', '預設進貨廠商').strip()
        remark = data.get('remark', '').strip()
        purchase_date = data.get('purchase_date', '').strip() or None
        image_url = data.get('image_url', '').strip()
        measure_type = data.get('measure_type', 'capacity').strip()
        if measure_type not in ('capacity', 'quantity'):
            measure_type = 'capacity'

        if not material_name:
            return jsonify({"status": "error", "message": "耗材名稱為必填欄位！"}), 400

        session_user = session.get('user', {}) or {}
        current_name = session_user.get('name') or session_user.get('username') or '管理員'
        operator_name = current_name  # 自動代入填表人姓名

        success = db_service.add_material_purchase(material_name, purchase_cost, purchase_qty, supplier, remark, operator_name, purchase_date, total_capacity, image_url, measure_type)
        if success:
            return jsonify({"status": "success", "message": "耗材進貨紀錄已成功儲存！"})
        return jsonify({"status": "error", "message": "儲存耗材進貨紀錄失敗"}), 500
    else:
        logs = db_service.get_material_purchases()
        return jsonify({"status": "success", "data": logs})

@material_bp.route('/api/admin/material-names', methods=['GET'])
@admin_or_coach_required
def api_admin_material_names():
    """取得所有不重複耗材名稱"""
    names = db_service.get_unique_material_names()
    return jsonify({"status": "success", "data": names})

@material_bp.route('/api/admin/material-unit-costs', methods=['GET'])
@admin_or_coach_required
def api_admin_material_unit_costs():
    """各耗材加權平均單位成本（Σ進貨總成本 ÷ Σ容量）"""
    costs = db_service.get_material_unit_costs()
    return jsonify({"status": "success", "data": costs})

@material_bp.route('/api/admin/material-images', methods=['GET'])
@admin_or_coach_required
def api_admin_material_images():
    """各耗材最近一筆有圖片的圖片網址（供寄送結算視窗顯示耗材照片）"""
    images = db_service.get_material_images()
    return jsonify({"status": "success", "data": images})

@material_bp.route('/api/admin/material-measure-types', methods=['GET'])
@admin_or_coach_required
def api_admin_material_measure_types():
    """各耗材的計量方式（capacity=容量 / quantity=數量）"""
    types = db_service.get_material_measure_types()
    return jsonify({"status": "success", "data": types})

@material_bp.route('/api/admin/material-management', methods=['GET'])
@admin_or_coach_required
def api_admin_material_management():
    """耗材管理：各耗材進貨總量/消耗總量（可依日期區間）與目前剩餘"""
    date_from = request.args.get('from', '').strip()[:10]
    date_to = request.args.get('to', '').strip()[:10]
    from_str = f"{date_from} 00:00:00" if date_from else "1970-01-01 00:00:00"
    to_str = f"{date_to} 23:59:59" if date_to else "9999-12-31 23:59:59"
    data = db_service.get_material_management_summary(from_str, to_str)
    return jsonify({"status": "success", "data": data})

@material_bp.route('/api/admin/material-management/detail', methods=['GET'])
@admin_or_coach_required
def api_admin_material_management_detail():
    """單一耗材明細：進貨紀錄 + 消耗紀錄（訂單結算／試作記錄）"""
    material = request.args.get('material', '').strip()
    if not material:
        return jsonify({"status": "error", "message": "請指定耗材"}), 400
    date_from = request.args.get('from', '').strip()[:10]
    date_to = request.args.get('to', '').strip()[:10]
    from_str = f"{date_from} 00:00:00" if date_from else "1970-01-01 00:00:00"
    to_str = f"{date_to} 23:59:59" if date_to else "9999-12-31 23:59:59"
    detail = db_service.get_material_management_detail(material, from_str, to_str)
    return jsonify({"status": "success", "data": detail})

@material_bp.route('/api/admin/material-consumptions', methods=['POST'])
@admin_or_coach_required
def api_admin_material_consumptions():
    """新增試作耗材消耗記錄"""
    data = request.get_json() or {}
    material_name = data.get('material_name', '').strip()
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "消耗量格式錯誤"}), 400
    if not material_name:
        return jsonify({"status": "error", "message": "請選擇耗材"}), 400
    if amount <= 0:
        return jsonify({"status": "error", "message": "消耗量需大於 0"}), 400

    measure_type = data.get('measure_type', 'capacity').strip()
    if measure_type not in ('capacity', 'quantity'):
        measure_type = 'capacity'
    session_user = session.get('user', {}) or {}
    operator_name = session_user.get('name') or session_user.get('username') or '管理員'
    raw_date = data.get('consumed_at', '').strip()
    consumed_at = raw_date.replace('T', ' ') + ':00' if raw_date else None
    try:
        cost = float(data.get('cost', 0))
        unit_cost = float(data.get('unit_cost', 0))
    except (TypeError, ValueError):
        cost = 0.0
        unit_cost = 0.0

    ok = db_service.add_material_consumption(
        material_name, amount, measure_type,
        data.get('remark', '').strip(), operator_name, consumed_at, cost, unit_cost,
    )
    if ok:
        return jsonify({"status": "success", "message": "消耗耗材記錄已儲存！"})
    return jsonify({"status": "error", "message": "儲存消耗記錄失敗"}), 500

@material_bp.route('/api/admin/material-consumptions/<int:log_id>', methods=['PUT', 'DELETE'])
@admin_or_coach_required
def api_admin_material_consumptions_detail(log_id):
    """修改或刪除試作耗材消耗記錄"""
    if request.method == 'PUT':
        data = request.get_json() or {}
        material_name = data.get('material_name', '').strip()
        try:
            amount = float(data.get('amount', 0))
            cost = float(data.get('cost', 0))
            unit_cost = float(data.get('unit_cost', 0))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "數量或成本格式錯誤"}), 400
        if not material_name:
            return jsonify({"status": "error", "message": "請選擇耗材"}), 400
        if amount <= 0:
            return jsonify({"status": "error", "message": "消耗量需大於 0"}), 400

        measure_type = data.get('measure_type', 'capacity').strip()
        if measure_type not in ('capacity', 'quantity'):
            measure_type = 'capacity'

        raw_date = data.get('consumed_at', '').strip()
        consumed_at = raw_date.replace('T', ' ') + ':00' if raw_date else None

        updated = db_service.update_material_consumption(
            log_id, material_name, amount, measure_type,
            data.get('remark', '').strip(), consumed_at, cost, unit_cost,
        )
        if updated:
            return jsonify({"status": "success", "message": "消耗記錄已更新！"})
        return jsonify({"status": "error", "message": "更新消耗記錄失敗"}), 500
    else:
        deleted = db_service.delete_material_consumption(log_id)
        if deleted:
            return jsonify({"status": "success", "message": "消耗記錄已刪除！"})
        return jsonify({"status": "error", "message": "刪除失敗"}), 500

@material_bp.route('/api/admin/material-recognize', methods=['POST'])
@admin_or_coach_required
def api_admin_material_recognize():
    """上傳墨盒用量圖片（可多張），以 Gemini Vision 辨識各色使用量"""
    try:
        files = request.files.getlist('files') or request.files.getlist('file')
        if not files:
            return jsonify({"status": "error", "message": "請選擇至少一張圖片"}), 400

        images = []
        for f in files:
            ok, msg, ext = _validate_upload(f, ALLOWED_IMAGE_EXTS)
            if not ok:
                return jsonify({"status": "error", "message": msg}), 400
            try:
                img = Image.open(io.BytesIO(f.read()))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                images.append(img)
            except Exception as e:
                print(f"Image open error: {e}")
                return jsonify({"status": "error", "message": f"圖片讀取失敗: {e}"}), 400

        items, err = material_recognize_service.recognize_ink_usage(images)
        if err:
            return jsonify({"status": "error", "message": err}), 400
        return jsonify({"status": "success", "data": {"items": items}})
    except Exception as e:
        print(f"Material recognize unexpected error: {e}")
        return jsonify({"status": "error", "message": f"辨識伺服器發生非預期錯誤: {e}"}), 500

@material_bp.route('/api/admin/material-suppliers', methods=['GET'])
@admin_or_coach_required
def api_admin_material_suppliers():
    """取得所有不重複廠商名稱"""
    suppliers = db_service.get_unique_material_suppliers()
    return jsonify({"status": "success", "data": suppliers})

@material_bp.route('/api/admin/material-purchases/<int:log_id>', methods=['PUT', 'DELETE'])
@admin_or_coach_required
def api_admin_material_purchases_detail(log_id):
    """修改或刪除耗材進貨紀錄"""
    if request.method == 'PUT':
        data = request.get_json() or {}
        material_name = data.get('material_name', '').strip()
        total_capacity = data.get('total_capacity', '').strip()
        purchase_cost = float(data.get('purchase_cost', 0))
        purchase_qty = int(data.get('purchase_qty', 0))
        supplier = data.get('supplier', '').strip()
        remark = data.get('remark', '').strip()
        purchase_date = data.get('purchase_date', '').strip() or None
        image_url = data.get('image_url', '').strip()
        measure_type = data.get('measure_type', 'capacity').strip()
        if measure_type not in ('capacity', 'quantity'):
            measure_type = 'capacity'

        session_user = session.get('user', {}) or {}
        operator_name = session_user.get('name') or session_user.get('username') or '管理員'

        updated = db_service.update_material_purchase(log_id, material_name, purchase_cost, purchase_qty, supplier, remark, operator_name, purchase_date, total_capacity, image_url, measure_type)
        if updated:
            return jsonify({"status": "success", "message": "耗材進貨紀錄已成功修改！"})
        return jsonify({"status": "error", "message": "修改耗材進貨紀錄失敗"}), 500
    else:
        deleted = db_service.delete_material_purchase(log_id)
        if deleted:
            return jsonify({"status": "success", "message": "耗材進貨紀錄已成功刪除！"})
        return jsonify({"status": "error", "message": "刪除失敗"}), 500

# --- Print Test APIs ---

@material_bp.route('/api/admin/print-test', methods=['POST'])
@admin_or_coach_required
def api_admin_print_test():
    """打印測試：建立 TEST 訂單並記錄耗材消耗（影響耗材庫存）"""
    data = request.get_json() or {}
    work_name = data.get('work_name', '').strip()
    materials = data.get('materials')
    if not work_name:
        return jsonify({"status": "error", "message": "請輸入作品名稱"}), 400
    if not isinstance(materials, list) or not materials:
        return jsonify({"status": "error", "message": "請至少填寫一筆耗材"}), 400
    try:
        other_cost = float(data.get('other_cost', 0) or 0)
        shipping_cost = float(data.get('shipping_cost', 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "成本格式錯誤"}), 400

    session_user = session.get('user', {}) or {}
    operator_name = session_user.get('name') or session_user.get('username') or '管理員'
    order_id = f"TEST-{uuid.uuid4().hex[:8].upper()}"

    ok, msg = db_service.save_print_test(order_id, work_name, materials, other_cost, shipping_cost, operator_name)
    if ok:
        return jsonify({"status": "success", "message": msg, "order_id": order_id})
    return jsonify({"status": "error", "message": msg}), 400

@material_bp.route('/api/admin/print-test/<order_id>', methods=['PUT', 'DELETE'])
@admin_or_coach_required
def api_admin_print_test_detail(order_id):
    """修改或刪除打印測試訂單"""
    if request.method == 'PUT':
        data = request.get_json() or {}
        work_name = data.get('work_name', '').strip()
        materials = data.get('materials')
        if not work_name:
            return jsonify({"status": "error", "message": "請輸入作品名稱"}), 400
        if not isinstance(materials, list):
            return jsonify({"status": "error", "message": "耗材明細格式錯誤"}), 400
        try:
            other_cost = float(data.get('other_cost', 0) or 0)
            shipping_cost = float(data.get('shipping_cost', 0) or 0)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "成本格式錯誤"}), 400

        ok, msg = db_service.update_print_test(str(order_id), work_name, materials, other_cost, shipping_cost)
        if ok:
            return jsonify({"status": "success", "message": msg})
        return jsonify({"status": "error", "message": msg}), 400
    else:
        ok, msg = db_service.delete_print_test(str(order_id))
        if ok:
            return jsonify({"status": "success", "message": msg})
        return jsonify({"status": "error", "message": msg}), 400
