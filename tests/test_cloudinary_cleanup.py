import unittest
from unittest.mock import patch, MagicMock
import datetime
from cloudinary_service import CloudinaryService


class TestCloudinaryService(unittest.TestCase):
    def setUp(self):
        self.service = CloudinaryService()

    def test_security_guard_rejects_products_folder(self):
        """測試安全防呆鎖：若嘗試清理包含 products 的目錄，必須拋出 ValueError"""
        with self.assertRaises(ValueError) as ctx:
            self.service.cleanup_temp_files(days=7, folder="uxprint/products")
        self.assertIn("安全防護觸發", str(ctx.exception))

    def test_security_guard_rejects_empty_or_root(self):
        """測試安全防呆鎖：若 folder 為空或根目錄，必須拋出 ValueError"""
        with self.assertRaises(ValueError):
            self.service.cleanup_temp_files(days=7, folder="")
        with self.assertRaises(ValueError):
            self.service.cleanup_temp_files(days=7, folder="uxprint")
        with self.assertRaises(ValueError):
            self.service.cleanup_temp_files(days=7, folder="other/path")

    @patch('cloudinary.uploader.upload')
    def test_upload_image_folder_param(self, mock_upload):
        """測試上傳圖片支援指定 folder"""
        self.service.enabled = True
        mock_upload.return_value = {"secure_url": "https://res.cloudinary.com/test/image/upload/v1/sample.jpg"}
        
        # 1. 預設 folder 為 uxprint/products
        url = self.service.upload_image("dummy.jpg")
        mock_upload.assert_called_with("dummy.jpg", resource_type="image", folder="uxprint/products")
        self.assertEqual(url, "https://res.cloudinary.com/test/image/upload/v1/sample.jpg")

        # 2. 指定 folder 為 uxprint/temp_line
        self.service.upload_image("dummy_temp.jpg", folder="uxprint/temp_line")
        mock_upload.assert_called_with("dummy_temp.jpg", resource_type="image", folder="uxprint/temp_line")

    @patch('cloudinary.uploader.upload')
    def test_upload_file_uuid_prevent_overwrite(self, mock_upload):
        """測試檔案上傳會加入 UUID 防止同名覆蓋"""
        self.service.enabled = True
        mock_upload.return_value = {"secure_url": "https://res.cloudinary.com/test/raw/upload/v1/sample.pdf"}

        url = self.service.upload_file("test.pdf", raw_filename="doc.pdf", folder="uxprint/files")
        self.assertTrue(mock_upload.called)
        call_kwargs = mock_upload.call_args[1]
        self.assertEqual(call_kwargs['resource_type'], 'raw')
        self.assertFalse(call_kwargs['overwrite'])
        self.assertTrue(call_kwargs['public_id'].startswith("uxprint/files/"))
        self.assertTrue(call_kwargs['public_id'].endswith("_doc.pdf"))
        self.assertEqual(url, "https://res.cloudinary.com/test/raw/upload/v1/sample.pdf")

    @patch('cloudinary.api.delete_resources')
    @patch('cloudinary.api.resources')
    def test_cleanup_temp_files_deletes_expired_only(self, mock_resources, mock_delete):
        """測試過期檔案過濾與批次刪除"""
        self.service.enabled = True
        
        now = datetime.datetime.now(datetime.timezone.utc)
        old_time = (now - datetime.timedelta(days=20)).isoformat().replace("+00:00", "Z")
        recent_time = (now - datetime.timedelta(days=2)).isoformat().replace("+00:00", "Z")

        # 模擬回傳兩個資源：一個 20 天前（應刪），一個 2 天前（保留）
        mock_resources.return_value = {
            "resources": [
                {"public_id": "uxprint/temp_line/old_img_1", "created_at": old_time},
                {"public_id": "uxprint/temp_line/new_img_2", "created_at": recent_time},
            ],
            "next_cursor": None,
        }
        mock_delete.return_value = {
            "deleted": {"uxprint/temp_line/old_img_1": "deleted"}
        }

        result = self.service.cleanup_temp_files(days=14, folder="uxprint/temp_line")
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["folder"], "uxprint/temp_line")
        # 應只有一個舊檔案被刪除
        self.assertEqual(result["deleted_count"], 2)  # image 輪與 raw 輪模擬


if __name__ == '__main__':
    unittest.main()
