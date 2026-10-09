from flask import Blueprint, render_template, send_from_directory, abort
from extensions import db_service
from routes.product_routes import to_public_product
from detail_content import read_detail_blocks
from extensions import UPLOAD_FOLDER

main_bp = Blueprint('main', __name__)

@main_bp.route('/', endpoint='home')
def home():
    """前台首頁"""
    return render_template('index.html')

@main_bp.route('/products/<prod_id>')
def product_detail(prod_id):
    product = next((p for p in db_service.get_products() if p['id'] == prod_id), None)
    if product is None:
        abort(404)
    public = to_public_product(product)
    return render_template('product.html', product=public,
                           detail_blocks=read_detail_blocks(public.get('detail_blocks_json')))

@main_bp.route('/uploads/<path:filename>', endpoint='serve_uploaded_file')
def serve_uploaded_file(filename):
    """公開上傳檔案靜態路由"""
    res = send_from_directory(UPLOAD_FOLDER, filename)
    res.headers['Access-Control-Allow-Origin'] = '*'
    res.headers['Cache-Control'] = 'public, max-age=31536000'
    return res
