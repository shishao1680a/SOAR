from flask import Blueprint, render_template, send_from_directory
from extensions import UPLOAD_FOLDER

main_bp = Blueprint('main', __name__)

@main_bp.route('/', endpoint='home')
def home():
    """前台首頁"""
    return render_template('index.html')

@main_bp.route('/uploads/<path:filename>', endpoint='serve_uploaded_file')
def serve_uploaded_file(filename):
    """公開上傳檔案靜態路由"""
    res = send_from_directory(UPLOAD_FOLDER, filename)
    res.headers['Access-Control-Allow-Origin'] = '*'
    res.headers['Cache-Control'] = 'public, max-age=31536000'
    return res
