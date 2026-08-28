import os
import uuid
from flask import Blueprint, request, jsonify
from linebot.models import TextSendMessage, ImageSendMessage
from extensions import (
    db_service, line_service, cloudinary_service, admin_or_coach_required,
    _validate_upload, _run_in_background, UPLOAD_FOLDER,
    ALLOWED_IMAGE_EXTS, ALLOWED_UPLOAD_EXTS
)
from pdf_service import convert_pdf_to_images

line_bp = Blueprint('line', __name__)

@line_bp.route('/api/admin/line-groups', methods=['GET', 'POST'])
@admin_or_coach_required
def api_admin_line_groups():
    """LINE 群組資料取得與儲存"""
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

@line_bp.route('/api/admin/line-groups/<group_id>', methods=['DELETE'])
@admin_or_coach_required
def api_admin_delete_line_group(group_id):
    """刪除 LINE 群組"""
    deleted = db_service.delete_line_group(group_id)
    if deleted:
        return jsonify({"status": "success", "message": "群組已刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500

@line_bp.route('/api/admin/line/broadcast', methods=['POST'])
@admin_or_coach_required
def api_admin_line_broadcast():
    """廣播推播：支援文字、圖片與 PDF 自動轉圖片（背景處理，避免請求逾時）"""
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

    # 同步只做「快速磁碟寫入」；PDF 轉圖與 LINE 推播移到背景執行緒
    saved_files = []  # (abs_path, ext)
    skipped = 0
    for file in uploaded_files:
        if not file or not file.filename:
            continue
        ok, msg, ext = _validate_upload(file, ALLOWED_UPLOAD_EXTS)
        if not ok:
            print(f"Broadcast skipped file {file.filename}: {msg}")
            skipped += 1
            continue
        unique_id = uuid.uuid4().hex[:12]
        saved_filename = f"{unique_id}{ext}"
        file_path = os.path.join(UPLOAD_FOLDER, saved_filename)
        file.save(file_path)
        saved_files.append((file_path, ext))

    if not message_text and not saved_files:
        return jsonify({"status": "error", "message": "發送內容不能為空，請輸入文字或選擇檔案！"}), 400

    def _broadcast_job():
        message_objects = []
        image_count = 0
        pdf_count = 0

        if message_text:
            message_objects.append(TextSendMessage(text=message_text))

        for file_path, ext in saved_files:
            fname = os.path.basename(file_path)
            if ext == '.pdf':
                pdf_count += 1
                try:
                    converted_imgs = convert_pdf_to_images(file_path, output_folder=UPLOAD_FOLDER)
                    for img_fname in converted_imgs:
                        img_path = os.path.join(UPLOAD_FOLDER, img_fname)
                        img_url = cloudinary_service.upload_image(img_path) or f"{host_base}/uploads/{img_fname}"
                        message_objects.append(ImageSendMessage(original_content_url=img_url, preview_image_url=img_url))
                        image_count += 1
                except Exception as pdf_err:
                    print(f"Error converting PDF to images: {pdf_err}")
                pdf_url = cloudinary_service.upload_file(file_path, raw_filename=fname) or f"{host_base}/uploads/{fname}"
                message_objects.append(TextSendMessage(text=f"📎 原始 PDF 檔案下載網址: {pdf_url}"))
            elif ext in ALLOWED_IMAGE_EXTS:
                image_count += 1
                img_url = cloudinary_service.upload_image(file_path) or f"{host_base}/uploads/{fname}"
                message_objects.append(ImageSendMessage(original_content_url=img_url, preview_image_url=img_url))
            else:
                file_url = cloudinary_service.upload_file(file_path, raw_filename=fname) or f"{host_base}/uploads/{fname}"
                message_objects.append(TextSendMessage(text=f"📎 檔案下載網址: {file_url}"))

        if not message_objects:
            print("Broadcast job: no messages to send")
            return

        success_count = 0
        for gid in group_ids:
            if line_service.push_messages_chunked(gid, message_objects):
                success_count += 1
        print(f"Broadcast job done: {success_count}/{len(group_ids)} groups, "
              f"{image_count} images, {pdf_count} pdfs")

    _run_in_background(_broadcast_job)

    pdf_file_count = sum(1 for _, ext in saved_files if ext == '.pdf')
    extra_note = f"（{skipped} 個檔案因類型/大小不符被略過）" if skipped else ""

    return jsonify({
        "status": "success",
        "message": f"已開始背景推播至 {len(group_ids)} 個 LINE 群組："
                   f"{len(message_text)} 字元文字、{len(saved_files)} 個檔案"
                   f"（含 {pdf_file_count} 份 PDF）。{extra_note}"
    })

@line_bp.route('/callback', methods=['POST'])
def line_webhook():
    """LINE 官方帳號 Webhook 接收端點"""
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    success = line_service.handle_webhook(body, signature)
    if success:
        return 'OK', 200
    return 'Invalid signature', 400
