"""管理員客服訊息：網站回覆、客人在 LINE 收發。"""
import os
import tempfile
import uuid

from flask import Blueprint, jsonify, redirect, render_template, request, session

from cloudinary_service import CloudinaryService
from extensions import db_service, line_service

chat_bp = Blueprint('chat', __name__)
cloudinary_service = CloudinaryService()

ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png'}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _admin():
    user = session.get('user') or {}
    return user if user.get('role') == 'admin' else None


def _deny():
    return jsonify(status='error', message='此功能僅限管理員使用'), 403


def _thread_name(t):
    return (t.get('member_name') or t.get('display_name') or
            'LINE ' + str(t.get('line_user_id') or '')[-6:])


def _thread_json(t):
    last = t.get('last_body') or ''
    if t.get('last_kind') == 'image':
        last = '[圖片]'
    elif t.get('last_kind') == 'placeholder':
        last = last or '[非文字訊息]'
    return {
        'line_user_id': t.get('line_user_id'),
        'name': _thread_name(t),
        'member': bool(t.get('user_id')),
        'unread': int(t.get('unread_count') or 0),
        'last': str(last)[:80],
        'last_at': str(t.get('last_message_at') or '')[:16],
        'last_direction': t.get('last_direction') or '',
    }


def _message_json(m):
    return {
        'id': m.get('id'),
        'direction': m.get('direction'),
        'kind': m.get('kind'),
        'body': m.get('body') or '',
        'image_url': m.get('image_url') or '',
        'status': m.get('status') or 'SENT',
        'error': m.get('error') or '',
        'admin_name': m.get('admin_name') or '',
        'created_at': str(m.get('created_at') or '')[:16],
    }


def _send_push(line_user_id, message):
    key = str(uuid.uuid5(uuid.NAMESPACE_URL, f'soar-chat-{message["id"]}'))
    if message['kind'] == 'image':
        return line_service.push_user_image(line_user_id, message.get('image_url') or '', key)
    return line_service.push_user_text(line_user_id, message.get('body') or '', key)


def _finish_send(message):
    ok, error = _send_push(message['line_user_id'], message)
    db_service.chat_update_message(message['id'], 'SENT' if ok else 'FAILED', '' if ok else error)
    return message['id'], ok, error


@chat_bp.get('/admin/chat')
def chat_page():
    if not _admin():
        return redirect('/admin')
    return render_template('chat.html', admin_name=(session.get('user') or {}).get('name') or '管理員')


@chat_bp.get('/api/admin/chat/threads')
def api_threads():
    if not _admin():
        return _deny()
    rows = db_service.chat_threads(200)
    return jsonify(status='success', data=[_thread_json(t) for t in rows],
                   unread=db_service.chat_unread_total())


@chat_bp.get('/api/admin/chat/<line_user_id>/messages')
def api_messages(line_user_id):
    if not _admin():
        return _deny()
    try:
        after_id = int(request.args.get('after_id') or 0)
    except ValueError:
        after_id = 0
    rows = db_service.chat_messages(line_user_id, after_id)
    return jsonify(status='success', data=[_message_json(m) for m in rows])


@chat_bp.post('/api/admin/chat/<line_user_id>/send')
def api_send_text(line_user_id):
    admin = _admin()
    if not admin:
        return _deny()
    data = request.get_json(silent=True) or {}
    text = str(data.get('text') or '').strip()
    if not text:
        return jsonify(status='error', message='請輸入訊息'), 400
    if len(text) > 5000:
        return jsonify(status='error', message='訊息最多 5000 字'), 400
    message = db_service.chat_add_message(
        line_user_id, 'OUT', 'text', text,
        admin_id=admin.get('id'), admin_name=admin.get('name') or '', status='PENDING')
    msg_id, ok, error = _finish_send(message)
    row = db_service.chat_get_message(msg_id)
    return jsonify(status='success', ok=ok, error='' if ok else error,
                   message=_message_json(row))


@chat_bp.post('/api/admin/chat/<line_user_id>/send-image')
def api_send_image(line_user_id):
    admin = _admin()
    if not admin:
        return _deny()
    upload = request.files.get('image')
    if not upload or not upload.filename:
        return jsonify(status='error', message='請選擇圖片'), 400
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify(status='error', message='只支援 JPG 或 PNG 圖片'), 400
    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size <= 0 or size > MAX_IMAGE_BYTES:
        return jsonify(status='error', message='圖片大小需小於 10MB'), 400

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=ext)
        with os.fdopen(fd, 'wb') as fh:
            fh.write(upload.stream.read())
        url = cloudinary_service.upload_image(tmp_path, folder='uxprint/chat')
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    if not url:
        return jsonify(status='error', message='圖片上傳失敗，請確認 Cloudinary 設定'), 400

    message = db_service.chat_add_message(
        line_user_id, 'OUT', 'image', '[圖片]', image_url=url,
        admin_id=admin.get('id'), admin_name=admin.get('name') or '', status='PENDING')
    msg_id, ok, error = _finish_send(message)
    row = db_service.chat_get_message(msg_id)
    return jsonify(status='success', ok=ok, error='' if ok else error,
                   message=_message_json(row))


@chat_bp.post('/api/admin/chat/messages/<int:message_id>/retry')
def api_retry(message_id):
    if not _admin():
        return _deny()
    message = db_service.chat_get_message(message_id)
    if not message or message['direction'] != 'OUT':
        return jsonify(status='error', message='找不到可重送的訊息'), 404
    ok, error = _send_push(message['line_user_id'], message)
    db_service.chat_update_message(message_id, 'SENT' if ok else 'FAILED', '' if ok else error)
    return jsonify(status='success', ok=ok, error='' if ok else error,
                   message=_message_json(db_service.chat_get_message(message_id)))


@chat_bp.post('/api/admin/chat/<line_user_id>/read')
def api_read(line_user_id):
    if not _admin():
        return _deny()
    db_service.chat_mark_read(line_user_id)
    return jsonify(status='success', unread=db_service.chat_unread_total())
