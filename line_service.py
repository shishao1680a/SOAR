import os
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

        if self.channel_secret:
            self.handler = WebhookHandler(self.channel_secret)
            self._register_webhook_handlers()
        else:
            self.handler = None

    def _register_webhook_handlers(self):
        """註冊事件處理器 (例如: 在群組內打 flbr 指令自動回覆 GID)"""
        if not self.handler:
            return

        @self.handler.add(MessageEvent, message=TextMessage)
        def handle_text_message(event):
            text_content = event.message.text.strip().lower()
            if text_content == 'flbr':
                # 取得來源群組 ID (groupId) 或聊天室 ID
                source_id = getattr(event.source, 'group_id', None) or getattr(event.source, 'room_id', None) or getattr(event.source, 'user_id', None)
                reply_text = f"【UX-PRINT 群組 ID 通知】\n本群組的 GID 為：\n{source_id}\n\n請複製上方 GID 貼至管理員後台【LINE 群組維護】即可完成設定！"
                
                try:
                    self.line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=reply_text)
                    )
                    print(f"Replied FLBR command with GID: {source_id}")
                except Exception as e:
                    print(f"Error replying FLBR command: {e}")

    def handle_webhook(self, body, signature):
        """處理 LINE Webhook 簽章驗證與事件派發"""
        if not self.handler:
            return False
        try:
            self.handler.handle(body, signature)
            return True
        except InvalidSignatureError:
            print("LINE Webhook Invalid Signature Error")
            return False
        except Exception as e:
            print(f"LINE Webhook Handler Error: {e}")
            return False

    def push_text_message(self, group_id, text_content):
        """發送單筆或批量文字訊息至 LINE 群組"""
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
