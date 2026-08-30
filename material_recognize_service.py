import os
import re
import json


class MaterialRecognizeService:
    """以 Gemini Vision 辨識 UV 墨盒用量圖片（依帳號可用模型依序嘗試）。"""

    def __init__(self, api_key=None):
        self.api_key = api_key

    def get_api_key(self):
        if self.api_key and len(str(self.api_key).strip()) > 10:
            return self.api_key.strip()
        env_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if env_key and len(env_key.strip()) > 10:
            return env_key.strip()
        return None

    def recognize_ink_usage(self, images):
        """images: list[PIL.Image]，回傳 (items, error)。items 為 [{letter, usage, unit}]。"""
        key = self.get_api_key()
        if not key:
            return None, "尚未設定 GEMINI_API_KEY（請在 Railway 環境變數加入）"
        try:
            import google.generativeai as genai
        except ImportError:
            return None, "伺服器缺少 Gemini 套件"

        genai.configure(api_key=key)

        prompt = (
            "你是 UV 印表機墨盒用量辨識助手。請仔細閱讀圖片中每一行或每一個列印記錄的墨水用量數值"
            "（例如：C<0.01 | M<0.01 | Y0.01 | W0.46 | W(F)0.00 | G0.44），"
            "將所有記錄中每一種顏色的使用量抽出來，輸出成純 JSON 陣列，格式："
            '[{"letter": "C", "usage": 0.01, "unit": "ml"}, ...]。'
            "字母請統一使用大寫：C / M / Y / K / W / W(F) / G；"
            "數值前面有 < 符號時，直接以該數值為準（例如 <0.01 視為 0.01）；"
            "請將所有記錄中相同的顏色各自抽取或加總；"
            "只要輸出 JSON，不要其他任何說明文字。"
        )

        # 適度縮小過大圖片，加快傳輸與辨識速度，避免連線逾時
        processed_images = []
        for img in images:
            try:
                max_dim = 1600
                if max(img.size) > max_dim:
                    scale = max_dim / max(img.size)
                    new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
                    processed_images.append(img.resize(new_size))
                else:
                    processed_images.append(img)
            except Exception:
                processed_images.append(img)

        contents = [prompt] + processed_images

        # 優先呼叫穩定且快速的模型
        candidates = [
            'gemini-2.0-flash',
            'gemini-1.5-flash',
            'gemini-1.5-pro',
            'gemini-2.5-flash',
        ]

        response = None
        last_err = None
        for cand in candidates:
            try:
                model = genai.GenerativeModel(cand)
                response = model.generate_content(contents)
                if response and response.text:
                    print(f"Gemini material recognize SUCCESS with model: {cand}")
                    break
            except Exception as e:
                last_err = e
                print(f"Gemini candidate {cand} failed: {e}")

        if not response or not response.text:
            return None, f"Gemini 辨識失敗：{last_err or '無回應'}"

        raw = response.text.strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        elif raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]

        try:
            parsed = json.loads(raw.strip())
        except Exception:
            m = re.search(r'\[.*\]', raw, re.S)
            if not m:
                return None, "Gemini 回傳格式無法解析"
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                return None, "Gemini 回傳格式無法解析"

        if not isinstance(parsed, list):
            return None, "Gemini 回傳格式不是陣列"

        # 同一顏色（字母）在多張圖片/多筆辨識結果中出現時，使用量自動加總
        aggregated = {}
        for it in parsed:
            letter = str(it.get('letter') or '').strip().upper()
            letter = 'W(F)' if letter in ('WF', 'W(F)', 'W（F）') else letter
            try:
                usage = float(it.get('usage', 0))
            except (TypeError, ValueError):
                usage = 0.0
            if not letter:
                continue
            d = aggregated.setdefault(letter, {
                "letter": letter,
                "usage": 0.0,
                "unit": (str(it.get('unit') or 'ml').strip() or 'ml'),
            })
            d["usage"] += max(0.0, usage)

        items = [
            {"letter": k, "usage": round(v["usage"], 3), "unit": v["unit"]}
            for k, v in aggregated.items()
        ]
        return items, None
