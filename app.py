import os
import uuid
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from dotenv import load_dotenv
from db_service import DBService
from line_service import LineService
from functools import wraps

# 載入環境變數
load_dotenv(override=False)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv("SECRET_KEY", "ux_print_club_secret_key_2026")

# 初始化 DB 與 LINE 服務 (對齊 第一金人壽 BR)
db_service = DBService()
line_service = LineService()

# 權限驗證 Decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user')
        if not user or user.get('role') != 'admin':
            return redirect(url_for('login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# --- Frontend & Auth Routes ---

@app.route('/')
def home():
    """主頁面渲染"""
    return render_template('index.html')

@app.route('/login')
def login_page():
    """登入頁面 (支援一般帳/密登入與 LINE Login 登入)"""
    return render_template('login.html')

@app.route('/admin')
@admin_required
def admin_page():
    """管理員後台頁面 (對齊 第一金人壽 BR admin.html 介面)"""
    return render_template('admin.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# --- Login & Authentication APIs ---

@app.route('/api/login', methods=['POST'])
def api_login():
    """一般帳/密 登入 API"""
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

@app.route('/api/line/login-url', methods=['GET'])
def api_line_login_url():
    """取得 LINE Login 授權網址"""
    state = uuid.uuid4().hex
    url = line_service.get_login_url(state)
    return jsonify({"status": "success", "url": url})

@app.route('/api/user/current', methods=['GET'])
def api_current_user():
    """取得目前登入使用者狀態"""
    user = session.get('user')
    if user:
        return jsonify({"status": "success", "user": user})
    return jsonify({"status": "error", "message": "Not logged in"}), 401

# --- Member Management APIs (成員管理) ---

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def api_admin_get_users():
    users = db_service.get_all_users()
    return jsonify({"status": "success", "data": users})

@app.route('/api/admin/users', methods=['POST'])
@admin_required
def api_admin_save_user():
    data = request.get_json() or {}
    user_id = data.get('id') or f"u_{uuid.uuid4().hex[:8]}"
    username = data.get('username')
    password = data.get('password', '123456')
    name = data.get('name')
    line_id = data.get('line_id', '')
    avatar_url = data.get('avatar_url', 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80')
    phone = data.get('phone', '')
    role = data.get('role', 'member')

    saved = db_service.save_or_update_user(user_id, username, password, name, line_id, avatar_url, phone, role)
    if saved:
        return jsonify({"status": "success", "message": "成員資料更新成功"})
    return jsonify({"status": "error", "message": "儲存失敗"}), 500

@app.route('/api/admin/users/<user_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_user(user_id):
    deleted = db_service.delete_user(user_id)
    if deleted:
        return jsonify({"status": "success", "message": "成員已刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

# --- Product & Inventory Management APIs (商品與進貨維護) ---

@app.route('/api/products', methods=['GET'])
def api_get_products():
    """抓取公開商品清單"""
    products = db_service.get_products()
    return jsonify({"status": "success", "data": products})

@app.route('/api/admin/products', methods=['POST'])
@admin_required
def api_admin_save_product():
    """新增/編輯商品 (支援上傳多張照片 images_json、3D設計成本 cost_price)"""
    data = request.get_json() or {}
    prod_id = data.get('id') or f"p_{uuid.uuid4().hex[:6]}"
    name = data.get('name')
    category = data.get('category', '3d-print')
    material = data.get('material', 'TPU_95A')
    price = float(data.get('price', 0))
    cost_price = float(data.get('cost_price', 0)) # 3D設計與生產成本
    stock_qty = int(data.get('stock_qty', 0))
    badge = data.get('badge', '')
    image_url = data.get('image_url', '') # 主圖
    images = data.get('images', []) # 多張照片列表
    images_json = json.dumps(images if images else [image_url], ensure_ascii=False)
    description = data.get('description', '')
    is_uv = bool(data.get('is_uv', False))

    saved = db_service.save_product(prod_id, name, category, material, price, cost_price, stock_qty, badge, image_url, images_json, description, is_uv)
    if saved:
        return jsonify({"status": "success", "message": "商品儲存成功"})
    return jsonify({"status": "error", "message": "商品儲存失敗"}), 500

@app.route('/api/admin/products/<prod_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_product(prod_id):
    deleted = db_service.delete_product(prod_id)
    if deleted:
        return jsonify({"status": "success", "message": "商品已下架刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

@app.route('/api/admin/inventory', methods=['GET', 'POST'])
@admin_required
def api_admin_inventory():
    """商品進貨服務 (記錄進貨數量、單價與供應商，並自動更新庫存)"""
    if request.method == 'POST':
        data = request.get_json() or {}
        product_id = data.get('product_id')
        product_name = data.get('product_name')
        purchase_qty = int(data.get('purchase_qty', 0))
        purchase_cost = float(data.get('purchase_cost', 0))
        supplier = data.get('supplier', '預設進貨廠商')
        remark = data.get('remark', '')

        success = db_service.add_inventory_log(product_id, product_name, purchase_qty, purchase_cost, supplier, remark)
        if success:
            return jsonify({"status": "success", "message": "進貨紀錄已儲存，商品庫存已更新！"})
        return jsonify({"status": "error", "message": "進貨失敗"}), 500
    else:
        logs = db_service.get_inventory_logs()
        return jsonify({"status": "success", "data": logs})

# --- LINE Group & Broadcast APIs (LINE 與各項群組功能) ---

@app.route('/api/admin/line-groups', methods=['GET', 'POST'])
@admin_required
def api_admin_line_groups():
    """群組維護 (同 第一金人壽 BR 群組維護卡片)"""
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
@admin_required
def api_admin_delete_line_group(group_id):
    deleted = db_service.delete_line_group(group_id)
    if deleted:
        return jsonify({"status": "success", "message": "群組已刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

@app.route('/api/admin/line/broadcast', methods=['POST'])
@admin_required
def api_admin_line_broadcast():
    """發送群組訊息 (批量發送文字/圖片訊息至 LINE 群組)"""
    data = request.get_json() or {}
    group_id = data.get('group_id')
    message_text = data.get('message')

    if not message_text:
        return jsonify({"status": "error", "message": "訊息內容不能為空"}), 400

    success = line_service.push_text_message(group_id, message_text)
    return jsonify({
        "status": "success" if success else "simulated",
        "message": f"已推播訊息至 LINE 群組 [{group_id or '預設群組'}]"
    })

# --- Bulletin APIs (公佈欄訊息維護) ---

@app.route('/api/bulletins', methods=['GET'])
def api_get_bulletins():
    bulletins = db_service.get_bulletins()
    return jsonify({"status": "success", "data": bulletins})

@app.route('/api/admin/bulletins', methods=['POST'])
@admin_required
def api_admin_save_bulletin():
    """發佈與管理首頁最新公告 (公佈欄訊息維護)"""
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
        # 如果勾選一鍵推播，同步發送 LINE 訊息
        if line_broadcasted:
            line_service.push_text_message(None, f"📢 【社團最新公告】\n{title}\n\n{summary}\n\n詳情請至 UX-PRINT 首頁查看！")
        return jsonify({"status": "success", "message": "公告已成功發佈！"})
    return jsonify({"status": "error", "message": "發佈失敗"}), 500

@app.route('/api/admin/bulletins/<b_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_bulletin(b_id):
    deleted = db_service.delete_bulletin(b_id)
    if deleted:
        return jsonify({"status": "success", "message": "公告已刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

@app.route('/api/orders', methods=['POST'])
def api_create_order():
    """成立購物車訂單並同步推播至社團 LINE 群組"""
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
