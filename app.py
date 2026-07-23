import os
import uuid
import json
from urllib.parse import quote
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from db_service import DBService
from line_service import LineService
from pdf_service import convert_pdf_to_images
from linebot.models import TextSendMessage, ImageSendMessage
from functools import wraps

load_dotenv(override=False)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv("SECRET_KEY", "ux_print_club_secret_key_2026")

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db_service = DBService()
line_service = LineService()

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
    return render_template('admin.html')

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
    if not file or not file.filename:
        return jsonify({"status": "error", "message": "無上傳圖片檔案"}), 400

    orig_filename = secure_filename(file.filename) or f"img_{uuid.uuid4().hex[:6]}.jpg"
    ext = os.path.splitext(orig_filename)[1].lower() or ".jpg"
    unique_name = f"item_{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(UPLOAD_FOLDER, unique_name)
    file.save(file_path)

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

    items = data.get('items', [])
    items_json = json.dumps(items, ensure_ascii=False) if isinstance(items, list) else items

    saved = db_service.save_product(prod_id, name, category, material, price, cost_price, uv_cost_price, stock_qty, badge, image_url, images_json, description, is_uv, items_json=items_json)
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
        product_id = data.get('product_id')
        product_name = data.get('product_name')
        purchase_qty = int(data.get('purchase_qty', 0))
        purchase_cost = float(data.get('purchase_cost', 0))
        supplier = data.get('supplier', '預設進貨廠商')
        remark = data.get('remark', '')

        item_name = data.get('item_name', '-').strip() or '-'
        session_user = session.get('user', {}) or {}
        current_name = session_user.get('name') or session_user.get('username') or '管理員'
        operator_name = data.get('operator_name', '').strip() or current_name

        success = db_service.add_inventory_log(product_id, product_name, item_name, purchase_qty, purchase_cost, supplier, remark, operator_name)
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
        supplier = data.get('supplier', '')
        remark = data.get('remark', '')

        session_user = session.get('user', {}) or {}
        operator_name = session_user.get('name') or session_user.get('username') or '管理員'

        updated = db_service.update_inventory_log(log_id, item_name, purchase_qty, purchase_cost, supplier, remark, operator_name)
        if updated:
            return jsonify({"status": "success", "message": "進貨紀錄已成功修改！"})
        return jsonify({"status": "error", "message": "修改進貨紀錄失敗"}), 500
    else:
        deleted = db_service.delete_inventory_log(log_id)
        if deleted:
            return jsonify({"status": "success", "message": "進貨紀錄已成功刪除！"})
        return jsonify({"status": "error", "message": "刪除失敗"}), 500

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
    """廣播推播：支援文字、圖片與 PDF 自動轉圖片 (每 5 則訊息一包分批發送)"""
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

    message_objects = []

    # 1. 如果有文字內容，加入第一則訊息
    if message_text:
        message_objects.append(TextSendMessage(text=message_text))

    # 2. 處理檔案 (圖片 / PDF / 一般文件)
    pdf_count = 0
    image_count = 0

    for file in uploaded_files:
        if file and file.filename:
            orig_filename = secure_filename(file.filename) or f"doc_{uuid.uuid4().hex[:6]}"
            ext = os.path.splitext(orig_filename)[1].lower()
            if not ext:
                ext = ".jpg" if "image" in file.mimetype else ".pdf"

            unique_id = uuid.uuid4().hex[:12]
            saved_filename = f"{unique_id}{ext}"
            file_path = os.path.join(UPLOAD_FOLDER, saved_filename)
            file.save(file_path)

            file_public_url = f"{host_base}/uploads/{saved_filename}"

            if ext == '.pdf':
                pdf_count += 1
                # 轉 PDF 各頁為圖片 (.jpg)
                try:
                    converted_imgs = convert_pdf_to_images(file_path, output_folder=UPLOAD_FOLDER)
                    for img_fname in converted_imgs:
                        img_url = f"{host_base}/uploads/{img_fname}"
                        message_objects.append(ImageSendMessage(original_content_url=img_url, preview_image_url=img_url))
                        image_count += 1
                except Exception as pdf_err:
                    print(f"Error converting PDF to images: {pdf_err}")

                # 附上原始 PDF 下載網址
                message_objects.append(TextSendMessage(text=f"📎 原始 PDF 檔案下載網址: {file_public_url}"))
            elif ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                image_count += 1
                message_objects.append(ImageSendMessage(original_content_url=file_public_url, preview_image_url=file_public_url))
            else:
                message_objects.append(TextSendMessage(text=f"📎 檔案下載網址: {file_public_url}"))

    if not message_objects:
        return jsonify({"status": "error", "message": "發送內容不能為空，請輸入文字或選擇檔案！"}), 400

    # 3. 呼叫 line_service 進行每 5 則訊息一包的分批發送 (push_messages_chunked)
    success_count = 0
    for gid in group_ids:
        ok = line_service.push_messages_chunked(gid, message_objects)
        if ok:
            success_count += 1

    return jsonify({
        "status": "success",
        "message": f"成功推播至 {success_count} 個 LINE 群組！（共傳送 {len(message_objects)} 則訊息包，包含 {image_count} 張圖片及 {pdf_count} 份 PDF 下載連結）"
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
            line_service.push_text_message(None, f"📢 【社團最新公告】\n{title}\n\n{summary}\n\n詳情請至 UX-PRINT 首頁查看！")
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
    user_name = data.get('user_name', '社團會員')
    user_line_id = data.get('user_line_id', 'GUEST')
    total_amount = data.get('total_amount', 0)

    if not cart_items:
        return jsonify({"status": "error", "message": "Cart is empty"}), 400

    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    saved = db_service.save_order(order_id, 'USER_TEMP', user_name, user_line_id, cart_items, total_amount)

    if saved:
        order_details = "\n".join([f"• {item.get('name')} x{item.get('qty', 1)} (${item.get('price')})" for item in cart_items])
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
        push_success = line_service.push_text_message(None, line_msg)

        return jsonify({
            "status": "success",
            "order_id": order_id,
            "line_pushed": push_success,
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
    app.run(host='0.0.0.0', port=port, debug=True)
