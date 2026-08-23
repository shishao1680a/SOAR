import os
import uuid
import json
import threading
import time
import io
from urllib.parse import quote
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory, make_response
from dotenv import load_dotenv
from db_service import DBService, StockError
from cloudinary_service import CloudinaryService
from material_recognize_service import MaterialRecognizeService
from line_service import LineService
from pdf_service import convert_pdf_to_images
from linebot.models import TextSendMessage, ImageSendMessage
from functools import wraps
from PIL import Image

load_dotenv(override=False)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY 環境變數未設定！請在 .env 或 Railway 環境變數中設定 SECRET_KEY")

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db_service = DBService()
cloudinary_service = CloudinaryService()
material_recognize_service = MaterialRecognizeService()
line_service = LineService()

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20MB
ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
ALLOWED_UPLOAD_EXTS = ALLOWED_IMAGE_EXTS | {'.pdf'}


def _validate_upload(file, allowed_exts):
    """檢查上傳檔案：必填、副檔名、非空、大小上限。回傳 (ok, message, ext)。"""
    if not file or not file.filename:
        return False, "無上傳檔案", None
    raw_name = file.filename.replace("\\", "/").split("/")[-1]
    ext = os.path.splitext(raw_name)[1].lower()
    if not ext:
        mime = (file.mimetype or "").lower()
        if mime.startswith("image/"):
            ext = ".jpg"
        elif mime == "application/pdf":
            ext = ".pdf"
        else:
            ext = ""
    if ext not in allowed_exts:
        return False, f"不支援的檔案類型：{ext or '（無法判斷）'}", None
    try:
        file.stream.seek(0, os.SEEK_END)
        size = file.stream.tell()
        file.stream.seek(0)
    except (OSError, AttributeError) as e:
        print(f"Error checking upload size: {e}")
        return False, "無法讀取檔案內容", None
    if size <= 0:
        return False, "檔案內容為空", None
    if size > MAX_UPLOAD_SIZE:
        return False, "檔案大小超過 20MB 上限", None
    return True, "", ext


def _run_in_background(target_fn, *args, **kwargs):
    """在背景執行緒執行外部呼叫（LINE 推播、PDF 轉圖），避免阻塞 HTTP 請求。"""
    t = threading.Thread(target=target_fn, args=args, kwargs=kwargs, daemon=True)
    t.start()


def admin_or_coach_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user')
        if not user or user.get('role') not in ['admin', 'assistant_coach']:
            return redirect(url_for('login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# --- Public Uploads Serving Route ---
@app.route('/uploads/<path:filename>')
def serve_uploaded_file(filename):
    res = send_from_directory(UPLOAD_FOLDER, filename)
    res.headers['Access-Control-Allow-Origin'] = '*'
    res.headers['Cache-Control'] = 'public, max-age=31536000'
    return res

# --- Frontend & Auth Routes ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/admin')
@admin_or_coach_required
def admin_page():
    resp = make_response(render_template('admin.html'))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# --- Login, Registration, LINE Binding & OAuth APIs ---

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    phone = data.get('phone', '').strip()
    line_id = data.get('line_id', '').strip()
    avatar_url = data.get('avatar_url', '').strip()

    if not name or not username or not password:
        return jsonify({"status": "error", "message": "姓名、帳號與密碼為必填欄位！"}), 400

    success, msg = db_service.register_user(username, password, name, phone, role='user', line_id=line_id, avatar_url=avatar_url)
    if success:
        return jsonify({"status": "success", "message": msg})
    return jsonify({"status": "error", "message": msg}), 400

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')

    user = db_service.authenticate_user(username, password)
    if user:
        session['user'] = {
            "id": user['id'],
            "username": user['username'],
            "name": user['name'],
            "line_id": user['line_id'],
            "avatar_url": user['avatar_url'],
            "role": user['role']
        }
        return jsonify({"status": "success", "user": session['user']})
    else:
        return jsonify({"status": "error", "message": "帳號或密碼錯誤！"}), 401

@app.route('/api/line/bind-account', methods=['POST'])
def api_line_bind_account():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    line_id = data.get('line_id', '').strip()
    avatar_url = data.get('avatar_url', '').strip()

    if not username or not password or not line_id:
        return jsonify({"status": "error", "message": "帳號、密碼與 LINE ID 不能為空"}), 400

    success, msg, bound_user = db_service.bind_line_to_account(username, password, line_id, avatar_url)
    if success and bound_user:
        session['user'] = {
            "id": bound_user['id'],
            "username": bound_user['username'],
            "name": bound_user['name'],
            "line_id": bound_user['line_id'],
            "avatar_url": bound_user['avatar_url'],
            "role": bound_user['role']
        }
        return jsonify({"status": "success", "message": msg, "user": session['user']})
    return jsonify({"status": "error", "message": msg}), 400

@app.route('/api/line/login-url', methods=['GET'])
def api_line_login_url():
    state = uuid.uuid4().hex
    session['oauth_state'] = state
    redirect_uri = os.getenv('LINE_LOGIN_REDIRECT_URI', f"{request.host_url.rstrip('/')}/api/line/callback")
    url = line_service.get_login_url(state, redirect_uri=redirect_uri)
    if url:
        return jsonify({"status": "success", "url": url})
    return jsonify({"status": "error", "message": "LINE_LOGIN_CHANNEL_ID 尚未設定！"}), 400

@app.route('/api/line/callback', methods=['GET'])
def api_line_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if error or not code:
        return f"LINE Login 取消授權或失敗: {error}", 400

    expected_state = session.pop('oauth_state', None)
    if not expected_state or state != expected_state:
        return "LINE Login 授權驗證失敗（state 不符），請重新登入！", 400

    redirect_uri = os.getenv('LINE_LOGIN_REDIRECT_URI', f"{request.host_url.rstrip('/')}/api/line/callback")
    token_data = line_service.exchange_code_for_token(code, redirect_uri=redirect_uri)
    if not token_data or 'access_token' not in token_data:
        return "LINE 金鑰交換失敗，請確認 LINE_LOGIN_CHANNEL_SECRET 與 REDIRECT_URI 設定！", 400

    access_token = token_data['access_token']
    profile = line_service.get_line_user_profile(access_token)
    if not profile:
        return "無法取得 LINE 個人檔案！", 400

    line_user_id = profile.get('userId')
    display_name = profile.get('displayName', 'LINE 使用者')
    picture_url = profile.get('pictureUrl', '')

    existing_user = db_service.get_user_by_line_id(line_user_id)
    if existing_user:
        session['user'] = {
            "id": existing_user['id'],
            "username": existing_user['username'],
            "name": existing_user['name'],
            "line_id": existing_user['line_id'],
            "avatar_url": existing_user['avatar_url'] or picture_url,
            "role": existing_user['role']
        }
        return redirect(url_for('home'))

    redirect_target = f"/login?tab=bind&line_id={quote(line_user_id)}&name={quote(display_name)}&avatar={quote(picture_url)}"
    return redirect(redirect_target)

@app.route('/api/user/current', methods=['GET'])
def api_current_user():
    user = session.get('user')
    if user:
        return jsonify({"status": "success", "user": user})
    return jsonify({"status": "error", "message": "Not logged in"}), 401

# --- Member Management APIs ---

@app.route('/api/admin/users', methods=['GET'])
@admin_or_coach_required
def api_admin_get_users():
    users = db_service.get_all_users()
    return jsonify({"status": "success", "data": users})

@app.route('/api/admin/users', methods=['POST'])
@admin_or_coach_required
def api_admin_save_user():
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

@app.route('/api/admin/users/<user_id>', methods=['DELETE'])
@admin_or_coach_required
def api_admin_delete_user(user_id):
    deleted = db_service.delete_user(user_id)
    if deleted:
        return jsonify({"status": "success", "message": "成員已刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

# --- Product & Inventory Management APIs ---

@app.route('/api/products', methods=['GET'])
def api_get_products():
    products = db_service.get_products()
    return jsonify({"status": "success", "data": products})

@app.route('/api/product-options', methods=['GET'])
def api_get_product_options():
    cats = db_service.get_custom_categories()
    mats = db_service.get_custom_materials()
    return jsonify({"status": "success", "categories": cats, "materials": mats})

@app.route('/api/admin/product-options/category', methods=['POST'])
@admin_or_coach_required
def api_admin_add_category():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    code = data.get('code', '').strip() or f"cat_{uuid.uuid4().hex[:6]}"
    if not name:
        return jsonify({"status": "error", "message": "請輸入分類名稱"}), 400
    success = db_service.add_custom_category(code, name)
    if success:
        return jsonify({"status": "success", "message": "分類新增成功", "code": code, "name": name})
    return jsonify({"status": "error", "message": "新增分類失敗"}), 500

@app.route('/api/admin/product-options/material', methods=['POST'])
@admin_or_coach_required
def api_admin_add_material():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    code = data.get('code', '').strip() or f"mat_{uuid.uuid4().hex[:6]}"
    if not name:
        return jsonify({"status": "error", "message": "請輸入材質等級/小分類名稱"}), 400
    success = db_service.add_custom_material(code, name)
    if success:
        return jsonify({"status": "success", "message": "材質/小分類新增成功", "code": code, "name": name})
    return jsonify({"status": "error", "message": "新增材質失敗"}), 500

@app.route('/api/admin/upload-image', methods=['POST'])
@admin_or_coach_required
def api_admin_upload_image():
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

@app.route('/api/admin/products', methods=['POST'])
@admin_or_coach_required
def api_admin_save_product():
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

@app.route('/api/admin/products/<prod_id>', methods=['DELETE'])
@admin_or_coach_required
def api_admin_delete_product(prod_id):
    deleted = db_service.delete_product(prod_id)
    if deleted:
        return jsonify({"status": "success", "message": "商品已下架刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

@app.route('/api/admin/inventory', methods=['GET', 'POST'])
@admin_or_coach_required
def api_admin_inventory():
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

@app.route('/api/admin/inventory/<int:log_id>', methods=['PUT', 'DELETE'])
@admin_or_coach_required
def api_admin_inventory_detail(log_id):
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

@app.route('/api/admin/material-purchases', methods=['GET', 'POST'])
@admin_or_coach_required
def api_admin_material_purchases():
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

@app.route('/api/admin/material-names', methods=['GET'])
@admin_or_coach_required
def api_admin_material_names():
    names = db_service.get_unique_material_names()
    return jsonify({"status": "success", "data": names})

@app.route('/api/admin/material-unit-costs', methods=['GET'])
@admin_or_coach_required
def api_admin_material_unit_costs():
    """各耗材加權平均單位成本（Σ進貨總成本 ÷ Σ容量）。"""
    costs = db_service.get_material_unit_costs()
    return jsonify({"status": "success", "data": costs})

@app.route('/api/admin/material-images', methods=['GET'])
@admin_or_coach_required
def api_admin_material_images():
    """各耗材最近一筆有圖片的圖片網址（供寄送結算視窗顯示耗材照片）。"""
    images = db_service.get_material_images()
    return jsonify({"status": "success", "data": images})

@app.route('/api/admin/material-measure-types', methods=['GET'])
@admin_or_coach_required
def api_admin_material_measure_types():
    """各耗材的計量方式（capacity=容量 / quantity=數量）。"""
    types = db_service.get_material_measure_types()
    return jsonify({"status": "success", "data": types})

@app.route('/api/admin/material-management', methods=['GET'])
@admin_or_coach_required
def api_admin_material_management():
    """耗材管理：各耗材進貨總量/消耗總量（可依日期區間）與目前剩餘。"""
    date_from = request.args.get('from', '').strip()[:10]
    date_to = request.args.get('to', '').strip()[:10]
    from_str = f"{date_from} 00:00:00" if date_from else "1970-01-01 00:00:00"
    to_str = f"{date_to} 23:59:59" if date_to else "9999-12-31 23:59:59"
    data = db_service.get_material_management_summary(from_str, to_str)
    return jsonify({"status": "success", "data": data})

@app.route('/api/admin/material-management/detail', methods=['GET'])
@admin_or_coach_required
def api_admin_material_management_detail():
    """單一耗材明細：進貨紀錄 + 消耗紀錄（訂單結算／試作記錄）。"""
    material = request.args.get('material', '').strip()
    if not material:
        return jsonify({"status": "error", "message": "請指定耗材"}), 400
    date_from = request.args.get('from', '').strip()[:10]
    date_to = request.args.get('to', '').strip()[:10]
    from_str = f"{date_from} 00:00:00" if date_from else "1970-01-01 00:00:00"
    to_str = f"{date_to} 23:59:59" if date_to else "9999-12-31 23:59:59"
    detail = db_service.get_material_management_detail(material, from_str, to_str)
    return jsonify({"status": "success", "data": detail})

@app.route('/api/admin/material-consumptions', methods=['POST'])
@admin_or_coach_required
def api_admin_material_consumptions():
    """新增試作耗材消耗記錄。"""
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

@app.route('/api/admin/material-consumptions/<int:log_id>', methods=['PUT', 'DELETE'])
@admin_or_coach_required
def api_admin_material_consumptions_detail(log_id):
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

@app.route('/api/admin/material-recognize', methods=['POST'])
@admin_or_coach_required
def api_admin_material_recognize():
    """上傳墨盒用量圖片（可多張），以 Gemini Vision 辨識各色使用量。"""
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
            return jsonify({"status": "error", "message": "圖片讀取失敗"}), 400

    items, err = material_recognize_service.recognize_ink_usage(images)
    if err:
        return jsonify({"status": "error", "message": err}), 400
    return jsonify({"status": "success", "data": {"items": items}})

@app.route('/api/admin/material-suppliers', methods=['GET'])
@admin_or_coach_required
def api_admin_material_suppliers():
    suppliers = db_service.get_unique_material_suppliers()
    return jsonify({"status": "success", "data": suppliers})

@app.route('/api/admin/material-purchases/<int:log_id>', methods=['PUT', 'DELETE'])
@admin_or_coach_required
def api_admin_material_purchases_detail(log_id):
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

@app.route('/api/admin/orders', methods=['GET'])
@admin_or_coach_required
def api_admin_orders():
    orders = db_service.get_all_orders()
    return jsonify({"status": "success", "data": orders})

@app.route('/api/admin/orders/<order_id>/ship', methods=['POST'])
@admin_or_coach_required
def api_admin_orders_ship(order_id):
    """寄送結算：接收逐商品明細（含設計者/包裝人員/耗材），快照寫入並更新訂單狀態。"""
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


@app.route('/api/admin/orders/<order_id>/cancel', methods=['POST'])
@admin_or_coach_required
def api_admin_orders_cancel(order_id):
    """取消訂單並釋放庫存。"""
    ok, msg = db_service.cancel_order(order_id)
    if ok:
        return jsonify({"status": "success", "message": msg})
    return jsonify({"status": "error", "message": msg}), 400


@app.route('/api/admin/orders/<order_id>/update', methods=['POST'])
@admin_or_coach_required
def api_admin_orders_update(order_id):
    """修改訂單明細（數量/單價）：伺服器端重算總額，並同步調整庫存扣減。"""
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


@app.route('/api/admin/orders/<order_id>/settlement', methods=['GET'])
@admin_or_coach_required
def api_admin_order_settlement(order_id):
    """讀取訂單已存的結算與耗材明細（供已寄送訂單修改時載入）。"""
    data = db_service.get_order_settlement(str(order_id))
    return jsonify({"status": "success", "data": data})


@app.route('/api/admin/orders/<order_id>/update-shipment', methods=['POST'])
@admin_or_coach_required
def api_admin_orders_update_shipment(order_id):
    """已寄送訂單修改：更新明細（單價/數量）與結算（設計者/包裝人員/耗材等），重新計算並寫回。"""
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

    ok, msg = db_service.update_order_settlement(str(order_id), items, products, order_totals)
    print(f"[TIMING] update-shipment {order_id}: total={round((time.time() - t_start) * 1000)}ms ok={ok}")
    if ok:
        return jsonify({"status": "success", "message": msg})
    return jsonify({"status": "error", "message": msg}), 400


@app.route('/api/admin/print-test', methods=['POST'])
@admin_or_coach_required
def api_admin_print_test():
    """打印測試：建立 TEST 訂單並記錄耗材消耗（影響耗材庫存）。"""
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


@app.route('/api/admin/bonuses', methods=['GET'])
@admin_or_coach_required
def api_admin_bonuses():
    """獎金統計：依結算時間區間回傳每人設計/包裝獎金、明細與平台收益。"""
    date_from = request.args.get('from', '').strip()[:10]
    date_to = request.args.get('to', '').strip()[:10]
    from_str = f"{date_from} 00:00:00" if date_from else "1970-01-01 00:00:00"
    to_str = f"{date_to} 23:59:59" if date_to else "9999-12-31 23:59:59"
    summary = db_service.get_bonus_summary(from_str, to_str)
    return jsonify({"status": "success", **summary})

@app.route('/api/admin/platform-revenue', methods=['GET'])
@admin_or_coach_required
def api_admin_platform_revenue():
    """平台收益彙總：依結算時間區間，依商品＋項目彙總各項金額。"""
    date_from = request.args.get('from', '').strip()[:10]
    date_to = request.args.get('to', '').strip()[:10]
    from_str = f"{date_from} 00:00:00" if date_from else "1970-01-01 00:00:00"
    to_str = f"{date_to} 23:59:59" if date_to else "9999-12-31 23:59:59"
    data = db_service.get_platform_revenue_summary(from_str, to_str)
    return jsonify({"status": "success", "data": data})

@app.route('/api/admin/platform-revenue/detail', methods=['GET'])
@admin_or_coach_required
def api_admin_platform_revenue_detail():
    """平台收益明細：單一商品＋項目的每一筆結算紀錄。"""
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

# --- LINE Group & Broadcast APIs (PDF 自動轉圖 + 每 5 張圖片一則訊息分批推播) ---

@app.route('/api/admin/line-groups', methods=['GET', 'POST'])
@admin_or_coach_required
def api_admin_line_groups():
    if request.method == 'POST':
        data = request.get_json() or {}
        group_id = data.get('id') or f"g_{uuid.uuid4().hex[:6]}"
        name = data.get('name')
        description = data.get('description', '')

        saved = db_service.save_line_group(group_id, name, description)
        if saved:
            return jsonify({"status": "success", "message": "LINE 群組資料已更新"})
        return jsonify({"status": "error", "message": "儲存失敗"}), 500
    else:
        groups = db_service.get_line_groups()
        return jsonify({"status": "success", "data": groups})

@app.route('/api/admin/line-groups/<group_id>', methods=['DELETE'])
@admin_or_coach_required
def api_admin_delete_line_group(group_id):
    deleted = db_service.delete_line_group(group_id)
    if deleted:
        return jsonify({"status": "success", "message": "群組已刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

@app.route('/api/admin/line/broadcast', methods=['POST'])
@admin_or_coach_required
def api_admin_line_broadcast():
    """廣播推播：支援文字、圖片與 PDF 自動轉圖片（背景處理，避免請求逾時）"""
    group_ids = []
    message_text = ""
    uploaded_files = []

    if request.files or (request.content_type and 'multipart/form-data' in request.content_type):
        group_ids = request.form.getlist('group_ids') or request.form.getlist('group_ids[]') or [request.form.get('group_id')]
        message_text = request.form.get('message', '').strip() or request.form.get('message_text', '').strip()
        uploaded_files = request.files.getlist('files')
    else:
        data = request.get_json() or {}
        group_ids = [data.get('group_id')] if data.get('group_id') else []
        message_text = data.get('message', '').strip()

    group_ids = [g for g in group_ids if g]
    if not group_ids:
        return jsonify({"status": "error", "message": "請選擇至少一個 LINE 目標發送群組"}), 400

    host_base = request.host_url.rstrip('/')
    if host_base.startswith('http://'):
        host_base = 'https://' + host_base[7:]

    # 同步只做「快速磁碟寫入」；PDF 轉圖與 LINE 推播移到背景執行緒
    saved_files = []  # (abs_path, ext)
    skipped = 0
    for file in uploaded_files:
        if not file or not file.filename:
            continue
        ok, msg, ext = _validate_upload(file, ALLOWED_UPLOAD_EXTS)
        if not ok:
            print(f"Broadcast skipped file {file.filename}: {msg}")
            skipped += 1
            continue
        unique_id = uuid.uuid4().hex[:12]
        saved_filename = f"{unique_id}{ext}"
        file_path = os.path.join(UPLOAD_FOLDER, saved_filename)
        file.save(file_path)
        saved_files.append((file_path, ext))

    if not message_text and not saved_files:
        return jsonify({"status": "error", "message": "發送內容不能為空，請輸入文字或選擇檔案！"}), 400

    def _broadcast_job():
        message_objects = []
        image_count = 0
        pdf_count = 0

        if message_text:
            message_objects.append(TextSendMessage(text=message_text))

        for file_path, ext in saved_files:
            fname = os.path.basename(file_path)
            if ext == '.pdf':
                pdf_count += 1
                try:
                    converted_imgs = convert_pdf_to_images(file_path, output_folder=UPLOAD_FOLDER)
                    for img_fname in converted_imgs:
                        img_path = os.path.join(UPLOAD_FOLDER, img_fname)
                        img_url = cloudinary_service.upload_image(img_path) or f"{host_base}/uploads/{img_fname}"
                        message_objects.append(ImageSendMessage(original_content_url=img_url, preview_image_url=img_url))
                        image_count += 1
                except Exception as pdf_err:
                    print(f"Error converting PDF to images: {pdf_err}")
                pdf_url = cloudinary_service.upload_file(file_path, raw_filename=fname) or f"{host_base}/uploads/{fname}"
                message_objects.append(TextSendMessage(text=f"📎 原始 PDF 檔案下載網址: {pdf_url}"))
            elif ext in ALLOWED_IMAGE_EXTS:
                image_count += 1
                img_url = cloudinary_service.upload_image(file_path) or f"{host_base}/uploads/{fname}"
                message_objects.append(ImageSendMessage(original_content_url=img_url, preview_image_url=img_url))
            else:
                file_url = cloudinary_service.upload_file(file_path, raw_filename=fname) or f"{host_base}/uploads/{fname}"
                message_objects.append(TextSendMessage(text=f"📎 檔案下載網址: {file_url}"))

        if not message_objects:
            print("Broadcast job: no messages to send")
            return

        success_count = 0
        for gid in group_ids:
            if line_service.push_messages_chunked(gid, message_objects):
                success_count += 1
        print(f"Broadcast job done: {success_count}/{len(group_ids)} groups, "
              f"{image_count} images, {pdf_count} pdfs")

    _run_in_background(_broadcast_job)

    pdf_file_count = sum(1 for _, ext, _ in saved_files if ext == '.pdf')
    extra_note = f"（{skipped} 個檔案因類型/大小不符被略過）" if skipped else ""

    return jsonify({
        "status": "success",
        "message": f"已開始背景推播至 {len(group_ids)} 個 LINE 群組："
                   f"{len(message_text)} 字元文字、{len(saved_files)} 個檔案"
                   f"（含 {pdf_file_count} 份 PDF）。{extra_note}"
    })

# --- Bulletin APIs ---

@app.route('/api/bulletins', methods=['GET'])
def api_get_bulletins():
    bulletins = db_service.get_bulletins()
    return jsonify({"status": "success", "data": bulletins})

@app.route('/api/admin/bulletins', methods=['POST'])
@admin_or_coach_required
def api_admin_save_bulletin():
    data = request.get_json() or {}
    b_id = data.get('id') or f"b_{uuid.uuid4().hex[:6]}"
    title = data.get('title')
    date_str = data.get('date_str', db_service._get_taiwan_now_str()[:10])
    tag = data.get('tag', '最新公告')
    is_pinned = bool(data.get('is_pinned', False))
    summary = data.get('summary', '')
    content = data.get('content', '')
    line_broadcasted = bool(data.get('line_broadcasted', True))

    saved = db_service.save_bulletin(b_id, title, date_str, tag, is_pinned, summary, content, line_broadcasted)
    if saved:
        if line_broadcasted:
            _run_in_background(
                line_service.push_text_message,
                None,
                f"📢 【社團最新公告】\n{title}\n\n{summary}\n\n詳情請至 UX-PRINT 首頁查看！"
            )
        return jsonify({"status": "success", "message": "公告已成功發佈！"})
    return jsonify({"status": "error", "message": "發佈失敗"}), 500

@app.route('/api/admin/bulletins/<b_id>', methods=['DELETE'])
@admin_or_coach_required
def api_admin_delete_bulletin(b_id):
    deleted = db_service.delete_bulletin(b_id)
    if deleted:
        return jsonify({"status": "success", "message": "公告已刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

@app.route('/api/orders', methods=['POST'])
def api_create_order():
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
            f"🛒 【UX-PRINT 3D/UV 新訂單通知】\n"
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

@app.route('/callback', methods=['POST'])
def line_webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    success = line_service.handle_webhook(body, signature)
    if success:
        return 'OK', 200
    return 'Invalid signature', 400

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', '').strip().lower() in ('1', 'true', 'yes', 'on')
    app.run(host='0.0.0.0', port=port, debug=debug)
