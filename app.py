import os
from flask import Flask
from dotenv import load_dotenv

# 載入環境變數
load_dotenv(override=False)

# 建立 Flask 實例
app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY 環境變數未設定！請在 .env 或 Railway 環境變數中設定 SECRET_KEY")

# 匯入並註冊所有業務藍圖模組
from routes import (
    main_bp,
    auth_bp,
    product_bp,
    bulletin_bp,
    admin_bp,
    material_bp,
    order_bp,
    line_bp,
)

app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(product_bp)
app.register_blueprint(bulletin_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(material_bp)
app.register_blueprint(order_bp)
app.register_blueprint(line_bp)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', '').strip().lower() in ('1', 'true', 'yes', 'on')
    app.run(host='0.0.0.0', port=port, debug=debug)
