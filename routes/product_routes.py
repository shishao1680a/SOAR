import json
import uuid
from flask import Blueprint, request, jsonify, session
from extensions import db_service, line_service, _run_in_background, StockError
import shop_service

product_bp = Blueprint('product', __name__)

# 前台公開 API 允許輸出的商品欄位白名單。
# 成本（cost_price／uv_cost_price）與分潤比例（designer_ratio／packager_ratio／platform_ratio）
# 屬營業機密，只提供給後台端點（/api/admin/products），不得出現在公開 API。
# （2026-09-26 Codex Security 掃描 finding：sensitive-data-exposure.public-product-cost）
PUBLIC_PRODUCT_FIELDS = (
    'id', 'name', 'category', 'material', 'price', 'stock_qty', 'badge',
    'image_url', 'images_json', 'items_json', 'description', 'is_uv', 'detail_blocks_json',
    # 2026-10-10：前台商品頁兩個選項群組的標題（可在後台自訂）
    'variant_label', 'color_label',
    # 2026-10-11：商品作者（前台列表與商品頁顯示）
    'author', 'onsite_enabled',
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


def user_name_map():
    """2026-10-11 主人指定：作者顯示要比照設計者──存 ID、顯示時查最新姓名。

    回傳 {人員ID: 姓名}。取不到時回傳空表，呼叫端會退回商品上的姓名備援值。
    """
    try:
        return {u.get('id'): u.get('name') for u in db_service.get_all_users() if u.get('id')}
    except Exception as e:
        print(f"Error building user name map: {e}")
        return {}


def to_public_product(prod, name_map=None):
    """只保留前台需要的欄位，避免成本與分潤比例經公開 API 外洩。"""
    out = {k: prod.get(k) for k in PUBLIC_PRODUCT_FIELDS}
    out['items_json'] = _strip_item_secrets(prod.get('items_json'))
    # 作者：優先用 author_user_id 查「現在」的姓名；查不到才用商品上存檔時的姓名。
    uid = prod.get('author_user_id') or ''
    live_name = (name_map or {}).get(uid) if uid else None
    out['author'] = live_name or prod.get('author') or ''
    return out


@product_bp.route('/api/products', methods=['GET'])
def api_get_products():
    """取得前台商品列表（僅回傳前台可見欄位）"""
    name_map = user_name_map()
    products = [to_public_product(p, name_map) for p in db_service.get_products()]
    return jsonify({"status": "success", "data": products})

@product_bp.route('/api/product-options', methods=['GET'])
def api_get_product_options():
    """取得商品分類與材質選項"""
    cats = db_service.get_custom_categories()
    mats = db_service.get_custom_materials()
    return jsonify({"status": "success", "categories": cats, "materials": mats})

@product_bp.route('/api/orders', methods=['POST'])
def api_create_order():
    """前台結帳 API：必須登入，並帶收件與寄送方式。"""
    user = session.get('user') or {}
    if not user.get('id'):
        return jsonify({"status": "error", "code": "login_required",
                        "message": "請先使用 LINE 登入"}), 401
    data = request.get_json() or {}
    cart_items = data.get('cart', [])
    ok, message, shipping = shop_service.validate_shipping(data.get('shipping'))
    if not ok:
        return jsonify({"status": "error", "message": message}), 400
    user_name = (user.get('name') or '').strip()[:60] or '社團會員'
    user_line_id = (user.get('line_id') or '').strip()[:100]

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
            raw_qty = item.get('qty')
            if isinstance(raw_qty, bool) or not isinstance(raw_qty, (int, str)):
                raise ValueError('quantity must be an integer')
            qty = int(raw_qty)
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
        if isinstance(items_arr, list) and items_arr and not variant_name:
            return jsonify({"status": "error", "message": "請先選擇商品款式"}), 400
        if variant_name and not matched_variant:
            return jsonify({
                "status": "error",
                "message": f"商品「{prod.get('name')}」的規格「{variant_name}」不存在，請重新整理頁面"
            }), 400
        if matched_variant:
            unit_price = float(matched_variant.get('price', prod.get('price') or 0))
            available = int(matched_variant.get('stock_qty', available) or 0)

        color_name = (item.get('color_name') or '').strip()
        colors = matched_variant.get('colors', []) if matched_variant else []
        if colors:
            chosen = next((c for c in colors if (c.get('name') or '').strip() == color_name), None)
            if not chosen:
                return jsonify({"status": "error", "message": "請選擇有效的商品顏色"}), 400
            available = min(available, int(chosen.get('stock_qty') or 0))
        elif color_name:
            return jsonify({"status": "error", "message": "商品顏色不存在，請重新選擇"}), 400
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
            "variant_color": color_name,
        })
        total_amount += unit_price * qty

    total_amount = round(total_amount, 2)
    fee = shop_service.shipping_fee_for(total_amount)
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    try:
        saved = db_service.create_checkout_order(
            order_id, user['id'], user_name, user_line_id, validated_items,
            total_amount, fee, shipping
        )
    except StockError as se:
        return jsonify({"status": "error", "message": str(se)}), 400
    if not saved:
        return jsonify({"status": "error", "message": "訂單儲存失敗，請稍後重試"}), 500

    db_service.update_user_address_if_empty(user['id'], shipping['address'])
    order = {
        'id': order_id, 'user_name': user_name,
        'items_json': json.dumps(validated_items, ensure_ascii=False),
        'total_amount': total_amount, 'shipping_fee': fee,
        'shipping_method': shipping['method'],
        'shipping_recipient': shipping['recipient'],
        'shipping_phone': shipping['phone'],
        'shipping_address': shipping['address'],
        'shipping_store': shipping.get('store') or '',
    }
    base_url = shop_service.public_base(request.url_root)
    group = None
    try:
        groups = db_service.get_line_groups() or []
        group = groups[0]['id'] if groups else None
    except Exception:
        group = None
    _run_in_background(line_service.push_text_message, group, shop_service.group_order_message(order))
    _run_in_background(line_service.push_user_text, user_line_id,
                       shop_service.customer_order_message(order, base_url), str(uuid.uuid4()))
    return jsonify({
        "status": "success",
        "order_id": order_id,
        "amount_due": str(float(total_amount) + float(fee)),
        "message": "Order created successfully"
    })
