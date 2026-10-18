import re
import uuid
from flask import Blueprint, request, jsonify
from extensions import db_service, line_service, admin_or_coach_required, _run_in_background

bulletin_bp = Blueprint('bulletin', __name__)

@bulletin_bp.route('/api/bulletins', methods=['GET'])
def api_get_bulletins():
    """取得社團公告列表"""
    bulletins = db_service.get_bulletins()
    return jsonify({"status": "success", "data": bulletins})

@bulletin_bp.route('/api/admin/bulletins', methods=['POST'])
@admin_or_coach_required
def api_admin_save_bulletin():
    """管理員發佈公告"""
    data = request.get_json() or {}
    b_id = data.get('id') or f"b_{uuid.uuid4().hex[:6]}"
    title = data.get('title')
    date_str = data.get('date_str', db_service._get_taiwan_now_str()[:10])
    tag = data.get('tag', '最新公告')
    is_pinned = bool(data.get('is_pinned', False))
    summary = data.get('summary', '')
    content = data.get('content', '')
    line_broadcasted = bool(data.get('line_broadcasted', True))
    color_re = re.compile(r'^#[0-9A-Fa-f]{6}$')
    mtext = data.get('marquee_text_color') or '#E7EFE9'
    mbg = data.get('marquee_bg_color') or '#0B0F14'
    if not isinstance(mtext, str) or not color_re.match(mtext):
        mtext = '#E7EFE9'
    if not isinstance(mbg, str) or not color_re.match(mbg):
        mbg = '#0B0F14'

    saved = db_service.save_bulletin(b_id, title, date_str, tag, is_pinned, summary, content, line_broadcasted,
                                     mtext, mbg)
    if saved:
        if line_broadcasted:
            _run_in_background(
                line_service.push_text_message,
                None,
                f"📢 【社團最新公告】\n{title}\n\n{summary}\n\n詳情請至 展夢.飛翔 首頁查看！"
            )
        return jsonify({"status": "success", "message": "公告已成功發佈！"})
    return jsonify({"status": "error", "message": "發佈失敗"}), 500

@bulletin_bp.route('/api/admin/bulletins/<b_id>', methods=['DELETE'])
@admin_or_coach_required
def api_admin_delete_bulletin(b_id):
    """管理員刪除公告"""
    deleted = db_service.delete_bulletin(b_id)
    if deleted:
        return jsonify({"status": "success", "message": "公告已刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"}), 500
