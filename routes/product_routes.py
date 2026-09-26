import json
import uuid
from flask import Blueprint, request, jsonify
from extensions import db_service, line_service, _run_in_background, StockError

product_bp = Blueprint('product', __name__)

# 前台公開 API 允許輸出的商品欄位白名單。
# 成本（cost_price／uv_cost_price）與分潤比例（designer_ratio／packager_ratio／platform_ratio）
# 屬營業機密，只提供給後台端點（/api/admin/products），不得出現在公開 API。
# （2026-09-26 Codex Security 掃描 finding：sensitive-data-exposure.public-product-cost）
PUBLIC_PRODUCT_FIELDS = (
    'id', 'name', 'category', 'material', 'price', 'stock_qty', 'badge',
    'image_url', 'images_json', 'items_json', 'description', 'is_uv',
)
ITEM_SECRET_FIELDS = ('cost_price', 'uv_cost_price')


def _strip_item_secrets(items_json):
    """把 items_json 內每個款式的成本欄位移除後重新序列化。"""
    try:
        items = json.loads(items_json) if isinstance(items_json, str) else (items_json or [])
    except (ValueError, TypeError):
        return items_json
    if not isinstance(items, list):
        return items_json
    cleaned = [
        {k: v for k, v in it.items() if k not in ITEM_SECRET_FIELDS}
        for it in items if isinstance(it, dict)
    ]
    return json.dumps(cleaned, ensure_ascii=False)


def to_public_product(prod):
    """只保留前台需要的欄位，避免成本與分潤比例經公開 API 外洩。"""
    out = {k: prod.get(k) for k in PUBLIC_PRODUCT_FIELDS}
    out['items_json'] = _strip_item_secrets(prod.get('items_json'))
    return out


@product_bp.route('/api/products', methods=['GET'])
def api_get_products():
    """取得前台商品列表（僅回傳前台可見欄位）"""
    products = [to_public_product(p) for p in db_service.get_products()]
    return jsonify({"status": "success", "data": products})

@product_bp.route('/api/product-options', methods=['GET'])
def api_get_product_options():
    """取得商品分類與材質選項"""
    cats = db_service.get_custom_categories()
    mats = db_service.get_custom_materials()
    return jsonify({"status": "success", "categories": cats, "materials": mats})

@product_bp.route('/api/orders', methods=['POST'])
def api_create_order():
    """前台會員下單 API"""
    data = request.get_json() or {}
    cart_items = data.get('cart', [])
    user_name = (data.get('user_name') or '社團會員').strip()[:60]
    user_line_id = (data.get('user_line_id') or 'GUEST').strip()[:100]

    if not isinstance(cart_items, list) or not cart_items:
        return jsonify({"status": "error", "message": "Cart is empty"}), 400

    # 伺服器端以資料庫價格重新計算，不信任客戶端傳來的價格/總額
    products = {p['id']: p for p in db_service.get_products()}
    validated_items = []
    total_amount = 0.0

    for item in cart_items:
        if not isinstance(item, dict):
            return jsonify({"status": "error", "message": "購物車內容格式錯誤"}), 400
        pid = str(item.get('id') or '').strip()
        try:
            qty = int(item.get('qty'))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "購買數量格式錯誤"}), 400
        if not pid or qty <= 0 or qty > 999:
            return jsonify({"status": "error", "message": "購買數量必須介於 1~999"}), 400

        prod = products.get(pid)
        if not prod:
            return jsonify({"status": "error", "message": "商品不存在或已下架，請重新整理頁面"}), 400

        unit_price = float(prod.get('price') or 0)
        available = int(prod.get('stock_qty') or 0)
        variant_name = (item.get('variant_name') or '').strip()

        items_arr = []
        try:
            raw = prod.get('items_json') or '[]'
            items_arr = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (ValueError, TypeError):
            items_arr = []

        matched_variant = None
        if variant_name and isinstance(items_arr, list):
            for v in items_arr:
                if (v.get('name') or '').strip() == variant_name:
                    matched_variant = v
                    break
        if variant_name and not matched_variant:
            return jsonify({
                "status": "error",
                "message": f"商品「{prod.get('name')}」的規格「{variant_name}」不存在，請重新整理頁面"
            }), 400
        if matched_variant:
            unit_price = float(matched_variant.get('price', prod.get('price') or 0))
            available = int(matched_variant.get('stock_qty', available) or 0)

        if qty > available:
            return jsonify({
                "status": "error",
                "message": f"商品「{prod.get('name')}」庫存不足（剩餘 {available} 件）"
            }), 400

        validated_items.append({
            "id": pid,
            "name": item.get('name') or prod.get('name'),
            "price": unit_price,
            "qty": qty,
            "variant_name": variant_name,
            "variant_color": (item.get('color_name') or '').strip(),
        })
        total_amount += unit_price * qty

    total_amount = round(total_amount, 2)
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    try:
        saved = db_service.save_order_with_stock(
            order_id, 'USER_TEMP', user_name, user_line_id, validated_items, total_amount
        )
    except StockError as se:
        return jsonify({"status": "error", "message": str(se)}), 400

    if saved:
        order_details = "\n".join([
            f"• {it.get('name')} x{it.get('qty', 1)} (${float(it.get('price')):.2f})"
            for it in validated_items
        ])
        line_msg = (
            f"🛒 【展夢.飛翔 新訂單通知】\n"
            f"----------------------------\n"
            f"訂單編號: {order_id}\n"
            f"訂購人: {user_name} ({user_line_id})\n"
            f"明細:\n{order_details}\n"
            f"----------------------------\n"
            f"總計金額: ${total_amount:.2f}\n\n"
            f"訂單已儲存至 PostgreSQL，請工程團隊進行 3D 切片與印刷排單！"
        )
        _run_in_background(line_service.push_text_message, None, line_msg)

        return jsonify({
            "status": "success",
            "order_id": order_id,
            "line_pushed": True,
            "message": "Order created successfully"
        })
    return jsonify({"status": "error", "message": "Failed to save order"}), 500
