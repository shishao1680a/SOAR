import os
import uuid
from urllib.parse import quote
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session
from extensions import db_service, line_service

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', endpoint='login_page')
def login_page():
    """登入頁面"""
    return render_template('login.html')

@auth_bp.route('/logout', endpoint='logout')
def logout():
    """登出"""
    session.clear()
    return redirect(url_for('main.home'))

@auth_bp.route('/api/register', methods=['POST'])
def api_register():
    """會員註冊 API"""
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

@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    """會員帳密登入 API"""
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

@auth_bp.route('/api/line/bind-account', methods=['POST'])
def api_line_bind_account():
    """LINE 帳號綁定 API"""
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

@auth_bp.route('/api/line/login-url', methods=['GET'])
def api_line_login_url():
    """取得 LINE Login 授權 URL"""
    state = uuid.uuid4().hex
    session['oauth_state'] = state
    redirect_uri = os.getenv('LINE_LOGIN_REDIRECT_URI', f"{request.host_url.rstrip('/')}/api/line/callback")
    url = line_service.get_login_url(state, redirect_uri=redirect_uri)
    if url:
        return jsonify({"status": "success", "url": url})
    return jsonify({"status": "error", "message": "LINE_LOGIN_CHANNEL_ID 尚未設定！"}), 400

@auth_bp.route('/api/line/callback', methods=['GET'])
def api_line_callback():
    """LINE Login OAuth 回呼處理"""
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
        return redirect(url_for('main.home'))

    redirect_target = f"/login?tab=bind&line_id={quote(line_user_id)}&name={quote(display_name)}&avatar={quote(picture_url)}"
    return redirect(redirect_target)

@auth_bp.route('/api/user/current', methods=['GET'])
def api_current_user():
    """取得當前登入者資訊"""
    user = session.get('user')
    if user:
        return jsonify({"status": "success", "user": user})
    return jsonify({"status": "error", "message": "Not logged in"}), 401
