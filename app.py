import os
from flask import Flask
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# 載入環境變數
load_dotenv(override=False)

# 建立 Flask 實例
app = Flask(__name__, static_folder='static', template_folder='templates')
# Default: trust no forwarded header. Set only after verifying the deployment proxy chain.
proxy_hops = int(os.getenv('LOGIN_TRUSTED_PROXY_HOPS', '0'))
if proxy_hops < 0:
    raise RuntimeError('LOGIN_TRUSTED_PROXY_HOPS 必須為非負整數')
if proxy_hops:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops, x_proto=0, x_host=0, x_port=0, x_prefix=0)
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
