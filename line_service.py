import os
import json
import requests
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
from linebot.exceptions import LineBotApiError, InvalidSignatureError

class LineService:
    def __init__(self):
        self.access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
        self.channel_secret = os.getenv('LINE_CHANNEL_SECRET')
        self.group_id = os.getenv('LINE_GROUP_ID')

        # LINE Login Credentials
        self.login_channel_id = os.getenv('LINE_LOGIN_CHANNEL_ID') or os.getenv('LINE_CHANNEL_ID')
        self.login_channel_secret = os.getenv('LINE_LOGIN_CHANNEL_SECRET') or os.getenv('LINE_CHANNEL_SECRET')
        self.redirect_uri = os.getenv('LINE_LOGIN_REDIRECT_URI', 'https://soar-staging.up.railway.app/api/line/callback')

        if self.access_token:
            self.line_bot_api = LineBotApi(self.access_token)
        else:
            self.line_bot_api = None
            print("WARNING: LINE_CHANNEL_ACCESS_TOKEN is missing! Bot cannot send reply messages.")

        if self.channel_secret:
            self.handler = WebhookHandler(self.channel_secret)
            self._register_webhook_handlers()
        else:
            self.handler = None
            print("WARNING: LINE_CHANNEL_SECRET is missing! Signature validation disabled.")

    def _register_webhook_handlers(self):
        """註冊事件處理器 (例如: 在群組內打 flbr 指令自動回覆 GID)"""
        if not self.handler:
            return

        @self.handler.add(MessageEvent, message=TextMessage)
        def handle_text_message(event):
            text_content = event.message.text.strip().lower()
            print(f"[LINE Webhook Event] Message received: '{text_content}'")
            
            if text_content == 'flbr':
                source_id = getattr(event.source, 'group_id', None) or getattr(event.source, 'room_id', None) or getattr(event.source, 'user_id', None)
                reply_text = f"【UX-PRINT 群組 ID 通知】\n本群組的 GID 為：\n{source_id}\n\n請複製上方 GID 貼至管理員後台【LINE 群組維護】即可完成設定！"
                
                if self.line_bot_api:
                    try:
                        self.line_bot_api.reply_message(
                            event.reply_token,
                            TextSendMessage(text=reply_text)
                        )
                        print(f"✅ Replied FLBR command with GID: {source_id}")
                    except Exception as e:
                        print(f"❌ Error replying FLBR command via LineBotApi: {e}")
                else:
                    print("⚠️ Cannot reply FLBR command because LINE_CHANNEL_ACCESS_TOKEN is missing on Railway!")

    def handle_webhook(self, body, signature):
        """處理 LINE Webhook 簽章驗證與事件派發，包含備援 JSON 解析"""
        print(f"[LINE Webhook] Received webhook payload: {body}")
        
        if self.handler:
            try:
                self.handler.handle(body, signature)
                return True
            except InvalidSignatureError:
                print("❌ LINE Webhook Signature Validation Failed. Attempting fallback payload parsing...")
            except Exception as e:
                print(f"❌ LINE Webhook Handler Error: {e}")

        try:
            payload = json.loads(body)
            events = payload.get('events', [])
            for event in events:
                if event.get('type') == 'message' and event.get('message', {}).get('type') == 'text':
                    msg_text = event['message'].get('text', '').strip().lower()
                    reply_token = event.get('replyToken')
                    source = event.get('source', {})
                    source_id = source.get('groupId') or source.get('roomId') or source.get('userId')

                    if msg_text == 'flbr' and reply_token and self.access_token:
                        reply_text = f"【UX-PRINT 群組 ID 通知】\n本群組的 GID 為：\n{source_id}\n\n請複製上方 GID 貼至管理員後台【LINE 群組維護】即可完成設定！"
                        headers = {
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {self.access_token}"
                        }
                        data = {
                            "replyToken": reply_token,
                            "messages": [{"type": "text", "text": reply_text}]
                        }
                        res = requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=data)
                        print(f"✅ Direct HTTP Reply FLBR response: {res.status_code} - {res.text}")
                        return True
        except Exception as fallback_err:
            print(f"Fallback parsing failed: {fallback_err}")

        return True

    def push_text_message(self, group_id, text_content):
        """發送單筆文字訊息至 LINE 群組"""
        target_group = group_id or self.group_id
        if not self.line_bot_api or not target_group:
            print("LINE Bot API or Group ID not configured.")
            return False
        try:
            message = TextSendMessage(text=text_content)
            self.line_bot_api.push_message(target_group, message)
            print(f"LINE Push message to group {target_group} success.")
            return True
        except LineBotApiError as e:
            print(f"LINE Bot Push Message Error: {e.status_code} - {e.error.message}")
            return False

    def push_messages_batch(self, group_id, text_content=None, image_urls=None):
        """混合推送文字與直接在 LINE 聊天室顯示預覽的真實圖片訊息 (ImageSendMessage，強制 HTTPS)"""
        target_group = group_id or self.group_id
        if not self.line_bot_api or not target_group:
            print("LINE Bot API or Group ID not configured.")
            return False

        messages = []
        if text_content:
            messages.append(TextSendMessage(text=text_content))

        if image_urls:
            for url in image_urls[:4]:
                # 強制轉換為 https 協定 (LINE API 嚴格要求 https)
                secure_url = url
                if secure_url.startswith('http://'):
                    secure_url = 'https://' + secure_url[7:]
                
                print(f"[LINE ImageSendMessage] Pushing image URL: {secure_url}")
                messages.append(ImageSendMessage(original_content_url=secure_url, preview_image_url=secure_url))

        if not messages:
            return False

        try:
            self.line_bot_api.push_message(target_group, messages)
            print(f"✅ LINE Push batch messages ({len(messages)} items) to group {target_group} success.")
            return True
        except LineBotApiError as e:
            print(f"❌ LINE Bot Push Batch Error: {e.status_code} - {e.error.message}")
            if e.error.details:
                for detail in e.error.details:
                    print(f"Detail: {detail.property} - {detail.message}")
            return False

    def get_login_url(self, state, redirect_uri=None):
        """產生真正的 LINE Login OAuth 2.1 授權網址"""
        r_uri = redirect_uri or self.redirect_uri
        if not self.login_channel_id:
            return None
        url = "https://access.line.me/oauth2/v2.1/authorize"
        params = {
            "response_type": "code",
            "client_id": self.login_channel_id,
            "redirect_uri": r_uri,
            "state": state,
            "scope": "profile openid email"
        }
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{url}?{query_string}"

    def exchange_code_for_token(self, code, redirect_uri=None):
        """以 authorization_code 向 LINE 換取 access_token"""
        r_uri = redirect_uri or self.redirect_uri
        token_url = "https://api.line.me/oauth2/v2.1/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": r_uri,
            "client_id": self.login_channel_id,
            "client_secret": self.login_channel_secret
        }
        try:
            res = requests.post(token_url, headers=headers, data=data)
            if res.status_code == 200:
                return res.json()
            else:
                print(f"LINE Token Exchange Error: {res.text}")
                return None
        except Exception as e:
            print(f"Failed to exchange LINE code: {e}")
            return None

    def get_line_user_profile(self, access_token):
        """使用 access_token 取得使用者的 LINE Profile (userId, displayName, pictureUrl)"""
        profile_url = "https://api.line.me/v2/profile"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            res = requests.get(profile_url, headers=headers)
            if res.status_code == 200:
                return res.json()
            else:
                print(f"LINE Profile Error: {res.text}")
                return None
        except Exception as e:
            print(f"Failed to get LINE user profile: {e}")
            return None
