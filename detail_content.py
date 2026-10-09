"""Validated, ordered plain-text/image blocks for product descriptions."""
import json
import os
from urllib.parse import urlsplit


def validate_detail_blocks(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError('詳細介紹必須為圖文段落，最多 100 段')
    blocks = []
    for block in value:
        if not isinstance(block, dict):
            raise ValueError('詳細介紹段落格式錯誤')
        if block.get('type') == 'text':
            content = block.get('text', '')
            if not isinstance(content, str) or len(content) > 10000:
                raise ValueError('每段文字最多 10,000 字')
            blocks.append({'type': 'text', 'text': content})
        elif block.get('type') == 'image':
            url, caption = block.get('url', ''), block.get('caption', '')
            cloud = os.getenv('CLOUDINARY_CLOUD_NAME', '')
            if not isinstance(url, str) or len(url) > 2048:
                raise ValueError('圖片網址格式錯誤')
            try:
                parsed = urlsplit(url)
                valid = (cloud and parsed.scheme == 'https'
                         and parsed.netloc == 'res.cloudinary.com'
                         and parsed.path.startswith(f'/{cloud}/image/upload/')
                         and '/uxprint/products/' in parsed.path
                         and not parsed.fragment)
            except ValueError:
                valid = False
            if not valid:
                raise ValueError('詳細介紹圖片必須由本站成功上傳至 Cloudinary')
            if not isinstance(caption, str) or len(caption) > 500:
                raise ValueError('圖片說明最多 500 字')
            blocks.append({'type': 'image', 'url': url, 'caption': caption})
        else:
            raise ValueError('詳細介紹只接受文字或圖片段落')
    if len(json.dumps(blocks, ensure_ascii=False)) > 250000:
        raise ValueError('詳細介紹內容過長')
    return blocks


def read_detail_blocks(raw):
    try:
        return validate_detail_blocks(json.loads(raw or '[]'))
    except (ValueError, TypeError):
        return []
