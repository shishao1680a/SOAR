import os
import cloudinary
import cloudinary.uploader


class CloudinaryService:
    """上傳圖片 / 檔案至 Cloudinary。
    需設定環境變數 CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET；
    未設定時 enabled=False，上傳方法回傳 None，由呼叫端沿用本機備援。
    """

    def __init__(self):
        self.enabled = bool(
            os.getenv('CLOUDINARY_CLOUD_NAME')
            and os.getenv('CLOUDINARY_API_KEY')
            and os.getenv('CLOUDINARY_API_SECRET')
        )
        if self.enabled:
            cloudinary.config(
                cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
                api_key=os.getenv('CLOUDINARY_API_KEY'),
                api_secret=os.getenv('CLOUDINARY_API_SECRET'),
                secure=True,
            )

    def upload_image(self, file_path):
        """上傳圖片，回傳 Cloudinary secure_url；失敗或未設定回傳 None。"""
        if not self.enabled:
            return None
        try:
            response = cloudinary.uploader.upload(
                file_path,
                resource_type="image",
                folder="uxprint/uploads",
            )
            return response.get('secure_url')
        except Exception as e:
            print(f"Cloudinary Image Upload Error: {e}")
            return None

    def upload_file(self, file_path, raw_filename=None):
        """上傳任意檔案（如 PDF）至 Cloudinary raw 類型，回傳 secure_url；失敗回傳 None。"""
        if not self.enabled:
            return None
        try:
            display_name = raw_filename if raw_filename else os.path.basename(file_path)
            response = cloudinary.uploader.upload(
                file_path,
                resource_type="raw",
                public_id=f"uxprint/files/{display_name}",
                overwrite=True,
                unique_filename=False,
            )
            return response.get('secure_url')
        except Exception as e:
            print(f"Cloudinary File Upload Error: {e}")
            return None
