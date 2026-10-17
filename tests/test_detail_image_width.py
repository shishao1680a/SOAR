"""Image sizing regressions; no database or external service required."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from flask import Flask, render_template
from detail_content import read_detail_blocks, validate_detail_blocks


class DetailImageWidthTests(unittest.TestCase):
    def setUp(self):
        self.cloud = patch.dict(os.environ, CLOUDINARY_CLOUD_NAME='soar-test')
        self.cloud.start()
        self.addCleanup(self.cloud.stop)
        self.image = {'type': 'image', 'url': 'https://res.cloudinary.com/soar-test/image/upload/v1/uxprint/products/test.png', 'caption': '範例圖'}

    def render(self, blocks):
        app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        with app.test_request_context('/'):
            return render_template('product.html', product={'id': 'width-test', 'name': '圖片寬度測試'}, detail_blocks=blocks)

    def test_all_sizes_survive_json_save_and_reload(self):
        blocks = [dict(self.image, width=width) for width in (25, 50, 75, 100)]
        saved = json.dumps(validate_detail_blocks(blocks), ensure_ascii=False)
        self.assertEqual(read_detail_blocks(saved), blocks)
        for width in (25, 50, 75, 100):
            self.assertIn(f'style="width:{width}%"', self.render(read_detail_blocks(saved)))

    def test_legacy_image_keeps_content_and_full_width(self):
        blocks = [self.image]
        self.assertEqual(read_detail_blocks(json.dumps(blocks)), blocks)
        self.assertIn('style="width:100%"', self.render(blocks))

    def test_invalid_sizes_are_rejected(self):
        for width in (0, -25, 24, 101, 1000, '50', '50%;color:red', True, None, 50.0, [], {}):
            with self.subTest(width=width), self.assertRaises(ValueError):
                validate_detail_blocks([dict(self.image, width=width)])

    def test_separate_images_keep_their_size_and_order(self):
        blocks = [dict(self.image, width=25), {'type': 'text', 'text': '中間段落'}, dict(self.image, width=75)]
        loaded = read_detail_blocks(json.dumps(validate_detail_blocks(blocks)))
        self.assertEqual(loaded, blocks)
        html = self.render(loaded)
        self.assertLess(html.index('width:25%'), html.index('中間段落'))
        self.assertLess(html.index('中間段落'), html.index('width:75%'))

    def test_caption_and_text_are_escaped(self):
        html = self.render([dict(self.image, width=50, caption='<script>caption</script>'), {'type': 'text', 'text': '<script>text</script>'}])
        self.assertNotIn('<script>caption</script>', html)
        self.assertIn('&lt;script&gt;caption&lt;/script&gt;', html)
        self.assertIn('&lt;script&gt;text&lt;/script&gt;', html)


if __name__ == '__main__':
    unittest.main()
