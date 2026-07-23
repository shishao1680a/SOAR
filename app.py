import os
import uuid
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from dotenv import load_dotenv
from db_service import DBService
from line_service import LineService

# 載入環境變數
load_dotenv(override=False)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv("SECRET_KEY", "ux_print_club_secret_key_2026")

# 初始化 DB 與 LINE 服務 (對齊 第一金人壽 BR)
db_service = DBService()
line_service = LineService()

@app.route('/')
def home():
    """主頁面渲染 (可直接載入 templates/index.html 或現有 index.html)"""
    if os.path.exists(os.path.join(app.template_folder, 'index.html')):
        return render_template('index.html')
    # 相容發佈模式下靜態資源根目錄
    return app.send_static_file('index.html') if os.path.exists(os.path.join(app.static_folder, 'index.html')) else open('index.html', encoding='utf-8').read()

@app.route('/index.html')
def index_html():
    return redirect(url_for('home'))

# --- API Endpoints ---

@app.route('/api/products', methods=['GET'])
def api_get_products():
    """抓取資料庫中的商品清單"""
    products = db_service.get_products()
    return jsonify({"status": "success", "data": products})

@app.route('/api/bulletins', methods=['GET'])
def api_get_bulletins():
    """抓取資料庫中的公佈欄公告"""
    bulletins = db_service.get_bulletins()
    return jsonify({"status": "success", "data": bulletins})

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
        # 組合 LINE 訊息內容 (對齊 第一金人壽 BR 推播格式)
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
        
        # 嘗試發送 LINE Bot Push Message
        push_success = line_service.push_text_message(None, line_msg)

        return jsonify({
            "status": "success",
            "order_id": order_id,
            "line_pushed": push_success,
            "message": "Order created successfully"
        })
    else:
        return jsonify({"status": "error", "message": "Failed to save order to database"}), 500

@app.route('/api/line/login-url', methods=['GET'])
def api_line_login_url():
    """取得 LINE Login 授權網址"""
    state = uuid.uuid4().hex
    url = line_service.get_login_url(state)
    return jsonify({"status": "success", "url": url})

@app.route('/callback', methods=['POST'])
def line_webhook():
    """LINE Bot Webhook 接收點"""
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    success = line_service.handle_webhook(body, signature)
    if success:
        return 'OK', 200
    return 'Invalid signature', 400

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
