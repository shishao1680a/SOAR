import os
import threading
from functools import wraps
from flask import session, request, redirect, url_for
from dotenv import load_dotenv

from db_service import DBService, StockError
from cloudinary_service import CloudinaryService
from material_recognize_service import MaterialRecognizeService
from line_service import LineService

# 載入環境變數
load_dotenv(override=False)

# 初始化各核心服務單例
db_service = DBService()
cloudinary_service = CloudinaryService()
material_recognize_service = MaterialRecognizeService()
line_service = LineService()

# 檔案上傳設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20MB
ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
ALLOWED_UPLOAD_EXTS = ALLOWED_IMAGE_EXTS | {'.pdf'}


def _validate_upload(file, allowed_exts):
    """檢查上傳檔案：必填、副檔名、非空、大小上限。回傳 (ok, message, ext)。"""
    if not file or not file.filename:
        return False, "無上傳檔案", None
    raw_name = file.filename.replace("\\", "/").split("/")[-1]
    ext = os.path.splitext(raw_name)[1].lower()
    if not ext:
        mime = (file.mimetype or "").lower()
        if mime.startswith("image/"):
            ext = ".jpg"
        elif mime == "application/pdf":
            ext = ".pdf"
        else:
            ext = ""
    if ext not in allowed_exts:
        return False, f"不支援的檔案類型：{ext or '（無法判斷）'}", None
    try:
        file.stream.seek(0, os.SEEK_END)
        size = file.stream.tell()
        file.stream.seek(0)
    except (OSError, AttributeError) as e:
        print(f"Error checking upload size: {e}")
        return False, "無法讀取檔案內容", None
    if size <= 0:
        return False, "檔案內容為空", None
    if size > MAX_UPLOAD_SIZE:
        return False, "檔案大小超過 20MB 上限", None
    return True, "", ext


def _run_in_background(target_fn, *args, **kwargs):
    """在背景執行緒執行外部呼叫（LINE 推播、PDF 轉圖），避免阻塞 HTTP 請求。"""
    t = threading.Thread(target=target_fn, args=args, kwargs=kwargs, daemon=True)
    t.start()


def admin_or_coach_required(f):
    """管理者或助教權限檢查裝飾器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user')
        if not user or user.get('role') not in ['admin', 'assistant_coach']:
            return redirect(url_for('auth.login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function
