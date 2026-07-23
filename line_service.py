import os
import requests
from linebot import LineBotApi, WebhookHandler
from linebot.models import TextSendMessage, ImageSendMessage
from linebot.exceptions import LineBotApiError, InvalidSignatureError

class LineService:
    def __init__(self):
        self.access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
        self.channel_id = os.getenv('LINE_LOGIN_CHANNEL_ID')
        self.channel_secret = os.getenv('LINE_CHANNEL_SECRET')
        self.redirect_uri = os.getenv('LINE_LOGIN_REDIRECT_URI')
        self.group_id = os.getenv('LINE_GROUP_ID')
        
        if self.access_token:
            self.line_bot_api = LineBotApi(self.access_token)
        else:
            self.line_bot_api = None

        if self.channel_secret:
            self.handler = WebhookHandler(self.channel_secret)
        else:
            self.handler = None

    def handle_webhook(self, body, signature):
        if not self.handler:
            return False
        try:
            self.handler.handle(body, signature)
            return True
        except InvalidSignatureError:
            return False

    def push_text_message(self, target_id, text):
        """傳送文字訊息至 LINE 群組或個人"""
        if not self.line_bot_api:
            print("LINE Bot API not configured.")
            return False
        try:
            to_id = target_id or self.group_id
            if not to_id:
                print("No LINE Target ID configured.")
                return False
            self.line_bot_api.push_message(to_id, TextSendMessage(text=text))
            return True
        except LineBotApiError as e:
            print(f"LINE Push Error: {e.status_code} - {e.error.message}")
            return False

    def get_login_url(self, state, redirect_uri=None):
        """產生 LINE Login 授權連結 (OAuth 2.1)"""
        r_uri = redirect_uri or self.redirect_uri
        url = "https://access.line.me/oauth2/v2.1/authorize"
        params = {
            "response_type": "code",
            "client_id": self.channel_id,
            "redirect_uri": r_uri,
            "state": state,
            "scope": "profile openid email"
        }
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{url}?{query_string}"

    def get_user_profile(self, code, redirect_uri=None):
        """以 Authorization Code 換取 Access Token 與 User Profile"""
        r_uri = redirect_uri or self.redirect_uri
        token_url = "https://api.line.me/oauth2/v2.1/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": r_uri,
            "client_id": self.channel_id,
            "client_secret": os.getenv('LINE_LOGIN_CHANNEL_SECRET')
        }
        
        response = requests.post(token_url, headers=headers, data=data)
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get("access_token")
            if access_token:
                profile_url = "https://api.line.me/v2/profile"
                p_headers = {"Authorization": f"Bearer {access_token}"}
                p_res = requests.get(profile_url, headers=p_headers)
                if p_res.status_code == 200:
                    return p_res.json()
            return token_data
        else:
            print(f"LINE Token Exchange Error: {response.text}")
            return None
