"""客人端留言頁：LINE 登入後可留言與傳圖片，只看得到自己的對話。"""
import os
import re

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session

from extensions import db_service

message_bp = Blueprint('messages', __name__)

ALLOWED_IMAGE_EXTS = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                      '.webp': 'image/webp'}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _user():
    user = session.get('user') or {}
    line_id = user.get('line_id') or ''
    if user.get('id') and re.fullmatch(r'U[0-9a-f]{32}', line_id):
        return user
    return None


def _message_json(m, viewer='customer'):
    mid = m.get('id')
    if m.get('has_attachment'):
        src = f'/messages/attachment/{mid}'
    else:
        src = (m.get('image_url') or '') if viewer == 'admin' else ''
    return {
        'id': mid,
        'direction': m.get('direction'),
        'kind': m.get('kind'),
        'body': m.get('body') or '',
        'image_src': src,
        'via': m.get('via') or 'line',
        'created_at': str(m.get('created_at') or '')[:16],
    }


@message_bp.get('/messages')
def page():
    raw_user = session.get('user') or {}
    if not raw_user.get('id'):
        return redirect('/login/line?next=/messages')
    user = _user()
    if not user:
        return render_template('messages.html', need_line=True,
                               member={'name': raw_user.get('name') or ''})
    member = db_service.get_user_by_id(user['id']) or {}
    return render_template('messages.html', need_line=False,
                           member={'name': member.get('name') or user.get('name') or ''})


@message_bp.get('/api/messages/mine')
def api_mine():
    user = _user()
    if not user:
        return jsonify(status='error', code='login_required', message='請先使用 LINE 登入'), 401
    try:
        after_id = int(request.args.get('after_id') or 0)
    except ValueError:
        after_id = 0
    rows = db_service.chat_messages(user['line_id'], after_id)
    return jsonify(status='success', data=[_message_json(m) for m in rows])


@message_bp.post('/api/messages/mine')
def api_send_text():
    user = _user()
    if not user:
        return jsonify(status='error', code='login_required', message='請先使用 LINE 登入'), 401
    data = request.get_json(silent=True) or {}
    text = str(data.get('text') or '').strip()
    if not text:
        return jsonify(status='error', message='請輸入留言'), 400
    if len(text) > 5000:
        return jsonify(status='error', message='留言最多 5000 字'), 400
    row = db_service.chat_add_message(user['line_id'], 'IN', 'text', text, via='web')
    return jsonify(status='success', message=_message_json(row))


@message_bp.post('/api/messages/mine/image')
def api_send_image():
    user = _user()
    if not user:
        return jsonify(status='error', code='login_required', message='請先使用 LINE 登入'), 401
    upload = request.files.get('image')
    if not upload or not upload.filename:
        return jsonify(status='error', message='請選擇圖片'), 400
    ext = os.path.splitext(upload.filename)[1].lower()
    mime = ALLOWED_IMAGE_EXTS.get(ext)
    if not mime:
        return jsonify(status='error', message='只支援 JPG、PNG 或 WebP 圖片'), 400
    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size <= 0 or size > MAX_IMAGE_BYTES:
        return jsonify(status='error', message='圖片大小需小於 10MB'), 400
    data = upload.stream.read()
    row = db_service.chat_add_message(
        user['line_id'], 'IN', 'image', '[圖片]', via='web',
        attachment={'name': upload.filename, 'mime': mime, 'size': len(data), 'data': data})
    return jsonify(status='success', message=_message_json(row))


@message_bp.get('/messages/attachment/<int:message_id>')
def attachment(message_id):
    user = _user()
    if not user:
        return '', 403
    row = db_service.chat_get_attachment(message_id)
    if not row or row['line_user_id'] != user['line_id']:
        return '', 404
    response = Response(row['attachment_data'], mimetype=row.get('attachment_mime') or 'application/octet-stream')
    name = (row.get('attachment_name') or 'image').replace('"', '')
    response.headers['Content-Disposition'] = f'inline; filename="{name}"'
    response.headers['Cache-Control'] = 'private, max-age=86400'
    return response
