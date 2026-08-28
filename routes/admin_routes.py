import os
import uuid
import json
from flask import Blueprint, render_template, request, jsonify, make_response, session
from extensions import (
    db_service, cloudinary_service, admin_or_coach_required,
    _validate_upload, UPLOAD_FOLDER, ALLOWED_IMAGE_EXTS
)

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin', endpoint='admin_page')
@admin_or_coach_required
def admin_page():
    """後台管理頁面"""
    resp = make_response(render_template('admin.html'))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp

# --- Member Management APIs ---

@admin_bp.route('/api/admin/users', methods=['GET'])
@admin_or_coach_required
def api_admin_get_users():
    """取得所有成員列表"""
    users = db_service.get_all_users()
    return jsonify({"status": "success", "data": users})

@admin_bp.route('/api/admin/users', methods=['POST'])
@admin_or_coach_required
def api_admin_save_user():
    """新增或更新成員資料"""
    data = request.get_json() or {}
    user_id = data.get('id') or f"u_{uuid.uuid4().hex[:8]}"
    username = data.get('username')
    password = data.get('password', '')
    name = data.get('name')
    line_id = data.get('line_id', '')
    avatar_url = data.get('avatar_url', 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80')
    phone = data.get('phone', '')
    role = data.get('role', 'user')

    saved = db_service.save_or_update_user(user_id, username, password, name, line_id, avatar_url, phone, role)
    if saved:
        return jsonify({"status": "success", "message": "成員資料更新成功"})
    return jsonify({"status": "error", "message": "儲存失敗"}), 500

@admin_bp.route('/api/admin/users/<user_id>', methods=['DELETE'])
@admin_or_coach_required
def api_admin_delete_user(user_id):
    """刪除成員"""
    deleted = db_service.delete_user(user_id)
    if deleted:
        return jsonify({"status": "success", "message": "成員已刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

# --- Product & Inventory Management APIs ---

@admin_bp.route('/api/admin/product-options/category', methods=['POST'])
@admin_or_coach_required
def api_admin_add_category():
    """新增自訂商品大分類"""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    code = data.get('code', '').strip() or f"cat_{uuid.uuid4().hex[:6]}"
    if not name:
        return jsonify({"status": "error", "message": "請輸入分類名稱"}), 400
    success = db_service.add_custom_category(code, name)
    if success:
        return jsonify({"status": "success", "message": "分類新增成功", "code": code, "name": name})
    return jsonify({"status": "error", "message": "新增分類失敗"}), 500

@admin_bp.route('/api/admin/product-options/material', methods=['POST'])
@admin_or_coach_required
def api_admin_add_material():
    """新增自訂材質/小分類"""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    code = data.get('code', '').strip() or f"mat_{uuid.uuid4().hex[:6]}"
    if not name:
        return jsonify({"status": "error", "message": "請輸入材質等級/小分類名稱"}), 400
    success = db_service.add_custom_material(code, name)
    if success:
        return jsonify({"status": "success", "message": "材質/小分類新增成功", "code": code, "name": name})
    return jsonify({"status": "error", "message": "新增材質失敗"}), 500

@admin_bp.route('/api/admin/upload-image', methods=['POST'])
@admin_or_coach_required
def api_admin_upload_image():
    """管理員上傳商品圖片（優先 Cloudinary，備援本地）"""
    file = request.files.get('file') or request.files.get('image')
    ok, msg, ext = _validate_upload(file, ALLOWED_IMAGE_EXTS)
    if not ok:
        return jsonify({"status": "error", "message": msg}), 400

    unique_name = f"item_{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(UPLOAD_FOLDER, unique_name)
    file.save(file_path)

    # 優先上傳至 Cloudinary（持久保存，重新部署不會消失）
    cloud_url = cloudinary_service.upload_image(file_path)
    if cloud_url:
        try:
            os.remove(file_path)
        except OSError:
            pass
        return jsonify({"status": "success", "url": cloud_url, "filename": unique_name})

    # Cloudinary 未設定或上傳失敗：沿用本機檔案（備援）
    host_base = request.host_url.rstrip('/')
    if host_base.startswith('http://'):
        host_base = 'https://' + host_base[7:]

    public_url = f"{host_base}/uploads/{unique_name}"
    return jsonify({"status": "success", "url": public_url, "filename": unique_name})

@admin_bp.route('/api/admin/products', methods=['POST'])
@admin_or_coach_required
def api_admin_save_product():
    """管理員新增/編輯商品"""
    data = request.get_json() or {}
    prod_id = data.get('id') or f"p_{uuid.uuid4().hex[:6]}"
    name = data.get('name')
    category = data.get('category', '3d-print')
    material = data.get('material', 'TPU_95A')
    price = float(data.get('price', 0))
    cost_price = float(data.get('cost_price', 0))
    uv_cost_price = float(data.get('uv_cost_price', 0))
    stock_qty = int(data.get('stock_qty', 0))
    badge = data.get('badge', '')
    image_url = data.get('image_url', '')
    images = data.get('images', [])
    images_json = json.dumps(images if images else [image_url], ensure_ascii=False)
    description = data.get('description', '')
    is_uv = bool(data.get('is_uv', False))
    designer_ratio = float(data.get('designer_ratio', 20) or 20)
    packager_ratio = float(data.get('packager_ratio', 60) or 60)
    platform_ratio = float(data.get('platform_ratio', 20) or 20)

    items = data.get('items', [])
    items_json = json.dumps(items, ensure_ascii=False) if isinstance(items, list) else items

    saved = db_service.save_product(
        prod_id, name, category, material, price, cost_price, uv_cost_price, stock_qty,
        badge, image_url, images_json, description, is_uv, items_json=items_json,
        designer_ratio=designer_ratio, packager_ratio=packager_ratio, platform_ratio=platform_ratio,
    )
    if saved:
        return jsonify({"status": "success", "message": "商品儲存成功"})
    return jsonify({"status": "error", "message": "商品儲存失敗"}), 500

@admin_bp.route('/api/admin/products/<prod_id>', methods=['DELETE'])
@admin_or_coach_required
def api_admin_delete_product(prod_id):
    """管理員下架/刪除商品"""
    deleted = db_service.delete_product(prod_id)
    if deleted:
        return jsonify({"status": "success", "message": "商品已下架刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

@admin_bp.route('/api/admin/inventory', methods=['GET', 'POST'])
@admin_or_coach_required
def api_admin_inventory():
    """商品進貨紀錄查詢與新增"""
    if request.method == 'POST':
        data = request.get_json() or {}
        records = data.get('records')
        session_user = session.get('user', {}) or {}
        current_name = session_user.get('name') or session_user.get('username') or '管理員'
        operator_name = data.get('operator_name', '').strip() or current_name

        if isinstance(records, list) and records:
            for rec in records:
                product_id = rec.get('product_id')
                product_name = rec.get('product_name')
                item_name = (rec.get('item_name', '-') or '-').strip() or '-'
                sub_option = (rec.get('sub_option') or '').strip()
                purchase_qty = int(rec.get('purchase_qty', 0))
                if purchase_qty <= 0:
                    continue
                purchase_cost = float(rec.get('purchase_cost', 0))
                supplier = rec.get('supplier', '預設進貨廠商')
                remark = rec.get('remark', '')
                ok = db_service.add_inventory_log(
                    product_id, product_name, item_name, purchase_qty, purchase_cost,
                    supplier, remark, operator_name, sub_option,
                )
                if not ok:
                    return jsonify({"status": "error", "message": "進貨失敗"}), 500
            return jsonify({"status": "success", "message": "進貨紀錄已儲存，商品庫存已更新！"})

        product_id = data.get('product_id')
        product_name = data.get('product_name')
        purchase_qty = int(data.get('purchase_qty', 0))
        purchase_cost = float(data.get('purchase_cost', 0))
        supplier = data.get('supplier', '預設進貨廠商')
        remark = data.get('remark', '')

        item_name = data.get('item_name', '-').strip() or '-'
        sub_option = (data.get('sub_option') or '').strip()

        success = db_service.add_inventory_log(product_id, product_name, item_name, purchase_qty, purchase_cost, supplier, remark, operator_name, sub_option)
        if success:
            return jsonify({"status": "success", "message": "進貨紀錄已儲存，商品庫存已更新！"})
        return jsonify({"status": "error", "message": "進貨失敗"}), 500
    else:
        logs = db_service.get_inventory_logs()
        return jsonify({"status": "success", "data": logs})

@admin_bp.route('/api/admin/inventory/<int:log_id>', methods=['PUT', 'DELETE'])
@admin_or_coach_required
def api_admin_inventory_detail(log_id):
    """修改或刪除進貨紀錄"""
    if request.method == 'PUT':
        data = request.get_json() or {}
        item_name = data.get('item_name', '-').strip() or '-'
        purchase_qty = int(data.get('purchase_qty', 0))
        purchase_cost = float(data.get('purchase_cost', 0))
        supplier = data.get('supplier')
        if supplier is None:
            existing = db_service._fetch_one(
                "SELECT supplier FROM inventory_logs WHERE id = :id", {"id": log_id}
            )
            supplier = (existing or {}).get('supplier') or ''
        remark = data.get('remark', '')
        sub_option = data.get('sub_option')

        session_user = session.get('user', {}) or {}
        operator_name = session_user.get('name') or session_user.get('username') or '管理員'

        updated = db_service.update_inventory_log(log_id, item_name, purchase_qty, purchase_cost, supplier, remark, operator_name, sub_option)
        if updated:
            return jsonify({"status": "success", "message": "進貨紀錄已成功修改！"})
        return jsonify({"status": "error", "message": "修改進貨紀錄失敗"}), 500
    else:
        deleted = db_service.delete_inventory_log(log_id)
        if deleted:
            return jsonify({"status": "success", "message": "進貨紀錄已成功刪除！"})
        return jsonify({"status": "error", "message": "刪除失敗"}), 500
