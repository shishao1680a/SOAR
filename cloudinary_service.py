import os
import uuid
import datetime
import cloudinary
import cloudinary.uploader
import cloudinary.api


class CloudinaryService:
    """上傳圖片 / 檔案至 Cloudinary，並提供目錄隔離與暫存安全清理機制。
    需設定環境變數 CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET；
    未設定時 enabled=False，上傳方法回傳 None，由呼叫端沿用本機備援。
    """

    ALLOWED_TEMP_PREFIXES = ("uxprint/temp", "uxprint/temp_line")

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

    def upload_image(self, file_path, folder="uxprint/products"):
        """上傳圖片，回傳 Cloudinary secure_url；失敗或未設定回傳 None。
        
        :param file_path: 本地圖片路徑
        :param folder: Cloudinary 儲存目錄，預設商品圖存放於 'uxprint/products'，
                      LINE 暫存圖請傳入 'uxprint/temp_line'
        """
        if not self.enabled:
            return None
        try:
            response = cloudinary.uploader.upload(
                file_path,
                resource_type="image",
                folder=folder,
            )
            return response.get('secure_url')
        except Exception as e:
            print(f"Cloudinary Image Upload Error ({folder}): {e}")
            return None

    def upload_file(self, file_path, raw_filename=None, folder="uxprint/files"):
        """上傳任意檔案（如 PDF）至 Cloudinary raw 類型，回傳 secure_url；失敗回傳 None。
        
        自動加入 UUID 前綴，防止不同使用者上傳同名檔案時互相覆蓋。
        """
        if not self.enabled:
            return None
        try:
            display_name = raw_filename if raw_filename else os.path.basename(file_path)
            clean_folder = folder.rstrip('/')
            unique_prefix = uuid.uuid4().hex[:8]
            public_id = f"{clean_folder}/{unique_prefix}_{display_name}"

            response = cloudinary.uploader.upload(
                file_path,
                resource_type="raw",
                public_id=public_id,
                overwrite=False,
                unique_filename=False,
            )
            return response.get('secure_url')
        except Exception as e:
            print(f"Cloudinary File Upload Error ({folder}): {e}")
            return None

    def cleanup_temp_files(self, days=14, folder="uxprint/temp_line"):
        """安全清理 Cloudinary 指定暫存目錄中超過 N 天的過期檔案。
        
        【安全防呆鎖】：
        強制僅允許清理開頭為 'uxprint/temp' 的暫存資料夾，
        若指向 'products'、根目錄或空值，一律拒絕執行並拋出異常。
        """
        # 1. 安全前綴白名單驗證（最優先執行）
        clean_folder = (folder or "").strip().rstrip('/')
        if not clean_folder or not any(clean_folder.startswith(p) for p in self.ALLOWED_TEMP_PREFIXES) or "products" in clean_folder:
            raise ValueError(f"安全防護觸發：拒絕執行！資料夾 '{clean_folder}' 非允許的暫存目錄（需以 uxprint/temp 開頭且不可包含 products）。")

        if not self.enabled:
            return {"status": "skipped", "message": "Cloudinary 未啟用", "deleted_count": 0}

        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        deleted_count = 0
        errors = []

        # 2. 清理 image 與 raw 兩種類型的暫存資源
        for res_type in ["image", "raw"]:
            next_cursor = None
            while True:
                try:
                    kwargs = {
                        "type": "upload",
                        "resource_type": res_type,
                        "prefix": f"{clean_folder}/",
                        "max_results": 100,
                    }
                    if next_cursor:
                        kwargs["next_cursor"] = next_cursor

                    result = cloudinary.api.resources(**kwargs)
                    resources = result.get("resources", [])
                    to_delete = []

                    for r in resources:
                        created_str = r.get("created_at")
                        if created_str:
                            try:
                                # 解析 Cloudinary ISO 時間字串 (例如 "2026-08-01T12:00:00Z")
                                if created_str.endswith('Z'):
                                    created_dt = datetime.datetime.fromisoformat(created_str[:-1] + '+00:00')
                                else:
                                    created_dt = datetime.datetime.fromisoformat(created_str)
                                
                                if created_dt < cutoff_date:
                                    to_delete.append(r.get("public_id"))
                            except Exception as parse_err:
                                print(f"Error parsing created_at for {r.get('public_id')}: {parse_err}")

                    if to_delete:
                        del_res = cloudinary.api.delete_resources(to_delete, resource_type=res_type)
                        deleted_dict = del_res.get("deleted", {})
                        success_deletes = sum(1 for v in deleted_dict.values() if v == "deleted")
                        deleted_count += success_deletes

                    next_cursor = result.get("next_cursor")
                    if not next_cursor:
                        break
                except Exception as e:
                    err_msg = f"Cloudinary cleanup error ({res_type}): {e}"
                    print(err_msg)
                    errors.append(err_msg)
                    break

        return {
            "status": "success" if not errors else "partial",
            "folder": clean_folder,
            "days_threshold": days,
            "deleted_count": deleted_count,
            "errors": errors,
        }
