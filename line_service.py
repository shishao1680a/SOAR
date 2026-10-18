import os
import re
import uuid
import requests
from urllib.parse import urlencode
from linebot import LineBotApi, WebhookHandler
from linebot.models import ImageMessage, MessageEvent, PostbackEvent, TextMessage, TextSendMessage
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
        """註冊事件處理器 (例如: 在群組內打 soar 指令自動回覆 GID)"""
        if not self.handler:
            return

        @self.handler.add(MessageEvent, message=TextMessage)
        def handle_text_message(event):
            text_content = event.message.text.strip().lower()
            print(f"[LINE Webhook Event] Message received: '{text_content}'")
            
            if text_content == 'soar':
                source_id = getattr(event.source, 'group_id', None) or getattr(event.source, 'room_id', None) or getattr(event.source, 'user_id', None)
                reply_text = f"【展夢.飛翔 群組 ID 通知】\n本群組的 GID 為：\n{source_id}\n\n請複製上方 GID 貼至管理員後台【LINE 群組維護】即可完成設定！"
                
                if self.line_bot_api:
                    try:
                        self.line_bot_api.reply_message(
                            event.reply_token,
                            TextSendMessage(text=reply_text)
                        )
                        print(f"✅ Replied SOAR command with GID: {source_id}")
                    except Exception as e:
                        print(f"❌ Error replying SOAR command via LineBotApi: {e}")
                else:
                    print("⚠️ Cannot reply SOAR command because LINE_CHANNEL_ACCESS_TOKEN is missing on Railway!")

            if getattr(event.source, 'type', None) == 'user':
                self._store_incoming(event, 'text', event.message.text.strip())

        @self.handler.add(MessageEvent, message=ImageMessage)
        def handle_image_message(event):
            if getattr(event.source, 'type', None) != 'user':
                return
            message_id = getattr(event.message, 'id', None)
            if not message_id:
                return
            url = None
            tmp_path = None
            try:
                content = self.line_bot_api.get_message_content(message_id)
                data = getattr(content, 'content', content)
                import tempfile
                fd, tmp_path = tempfile.mkstemp(suffix='.jpg')
                with os.fdopen(fd, 'wb') as fh:
                    fh.write(data)
                from extensions import cloudinary_service
                url = cloudinary_service.upload_image(tmp_path, folder='uxprint/chat')
            except Exception as exc:
                print(f"Incoming image failed: {exc}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
            if url:
                self._store_incoming(event, 'image', '[圖片]', url)
            else:
                self._store_incoming(event, 'placeholder', '（客人傳了圖片，但圖片儲存失敗）')

        @self.handler.add(PostbackEvent)
        def handle_postback(event):
            """匯款回報的三個按鈕：更新付款狀態並回覆客人。"""
            payload = (getattr(event.postback, 'data', '') or '').split(':')
            if len(payload) != 3 or payload[0] != 'remit':
                return
            order_id, action = payload[1], payload[2]
            try:
                from extensions import db_service
                import shop_service
                group_id = getattr(event.source, 'group_id', None)
                allowed = {g.get('id') for g in (db_service.get_line_groups() or [])}
                if self.group_id:
                    allowed.add(self.group_id)
                if group_id not in allowed:
                    return
                actor_id = getattr(event.source, 'user_id', '') or ''
                actor_name = actor_id
                if self.line_bot_api and actor_id:
                    try:
                        profile = self.line_bot_api.get_profile(actor_id)
                        actor_name = getattr(profile, 'display_name', None) or actor_id
                    except Exception:
                        pass
                order = db_service.set_payment_status(order_id, action, actor_id, actor_name)
                labels = {'CONFIRMED': '確認收到', 'NOT_RECEIVED': '尚未收到', 'AMOUNT_MISMATCH': '匯款金額有誤'}
                if self.line_bot_api:
                    self.line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"已更新訂單 {order_id}：{labels.get(action, action)}"))
                text = shop_service.customer_payment_message(order, action)
                if text:
                    self.push_user_text(order.get('user_line_id') or '', text, str(uuid.uuid4()))
            except Exception as exc:
                print(f"Postback handling failed: {exc}")
                try:
                    if self.line_bot_api:
                        self.line_bot_api.reply_message(
                            event.reply_token,
                            TextSendMessage(text='操作失敗，請稍後再試或使用後台確認。'))
                except Exception:
                    pass

    def _store_incoming(self, event, kind, body='', image_url=None):
        try:
            from extensions import db_service
            line_user_id = getattr(event.source, 'user_id', None)
            if not line_user_id:
                return
            thread = db_service._fetch_one(
                'SELECT display_name FROM chat_threads WHERE line_user_id=:l', {'l': line_user_id})
            display_name = ''
            if not thread or not (thread.get('display_name') or '').strip():
                try:
                    profile = self.line_bot_api.get_profile(line_user_id) if self.line_bot_api else None
                    display_name = getattr(profile, 'display_name', '') or ''
                except Exception:
                    display_name = ''
            member = db_service._fetch_one(
                'SELECT id, name FROM users WHERE line_id=:l ORDER BY id LIMIT 1', {'l': line_user_id})
            db_service.chat_upsert_thread(
                line_user_id,
                user_id=(member or {}).get('id'),
                display_name=(member or {}).get('name') or display_name,
            )
            db_service.chat_add_message(line_user_id, 'IN', kind=kind, body=body, image_url=image_url)
        except Exception as exc:
            print(f"Store incoming chat failed: {exc}")

    def handle_webhook(self, body, signature):
        """處理 LINE Webhook 簽章驗證與事件派發。

        簽章驗證失敗一律回傳 False（對應 400），不處理 payload、不記錄訊息內容。
        """
        if not self.handler:
            print("WARNING: LINE_CHANNEL_SECRET 未設定，無法驗證 Webhook 簽章")
            return False
        try:
            self.handler.handle(body, signature)
            return True
        except InvalidSignatureError:
            print("❌ LINE Webhook Signature Validation Failed")
            return False
        except Exception as e:
            print(f"❌ LINE Webhook Handler Error: {e}")
            return False

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

    def push_flex(self, group_id, alt_text, contents):
        """推播 Flex 訊息（匯款回報的三個按鈕）。"""
        target = group_id or self.group_id
        if not self.access_token or not target:
            print("LINE Bot API or Group ID not configured.")
            return False
        try:
            response = requests.post(
                'https://api.line.me/v2/bot/message/push',
                headers={'Authorization': f'Bearer {self.access_token}'},
                json={'to': target, 'messages': [
                    {'type': 'flex', 'altText': alt_text, 'contents': contents}]},
                timeout=(3, 8),
            )
            if response.status_code == 200:
                return True
            print(f"LINE flex push failed: HTTP {response.status_code}")
        except requests.RequestException as exc:
            print(f"LINE flex push error: {exc}")
        return False

    def push_messages_chunked(self, group_id, message_objects):
        """
        分批發送訊息物件列表至 LINE 群組，每 5 則訊息切分為一包 (LINE API 單次上限為 5 則)
        """
        target_group = group_id or self.group_id
        if not self.line_bot_api or not target_group:
            print("LINE Bot API or Group ID not configured.")
            return False

        if not message_objects:
            return False

        success = True
        for i in range(0, len(message_objects), 5):
            chunk = message_objects[i:i+5]
            try:
                self.line_bot_api.push_message(target_group, chunk)
                print(f"✅ LINE Push chunk {i//5 + 1} ({len(chunk)} items) to {target_group} success.")
            except LineBotApiError as e:
                print(f"❌ LINE Bot Push Chunk Error: {e.status_code} - {e.error.message}")
                if e.error.details:
                    for detail in e.error.details:
                        print(f"Detail: {detail.property} - {detail.message}")
                success = False

        return success

    def get_login_url(self, state, redirect_uri=None, add_friend=False):
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
        if add_friend:
            params["bot_prompt"] = "aggressive"
        query_string = urlencode(params)
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
            res = requests.post(token_url, headers=headers, data=data, timeout=(3, 8))
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
            res = requests.get(profile_url, headers=headers, timeout=(3, 8))
            if res.status_code == 200:
                return res.json()
            else:
                print(f"LINE Profile Error: {res.text}")
                return None
        except Exception as e:
            print(f"Failed to get LINE user profile: {e}")
            return None

    def get_friendship_status(self, access_token):
        try:
            response = requests.get('https://api.line.me/friendship/v1/status',
                headers={'Authorization': f'Bearer {access_token}'}, timeout=(3, 8))
            if response.status_code == 200:
                return response.json().get('friendFlag') is True
        except (requests.RequestException, ValueError):
            pass
        return None

    def push_user_text(self, user_id, content, retry_key):
        """個人預約通知；禁止退回管理群組，回傳值不代表已讀或送達。"""
        if not isinstance(user_id, str) or not re.fullmatch(r'U[0-9a-f]{32}', user_id):
            return False, '缺少有效的 LINE 個人收件人'
        if not self.access_token:
            return False, '尚未設定 LINE Messaging API'
        try:
            response = requests.post('https://api.line.me/v2/bot/message/push',
                headers={'Authorization': f'Bearer {self.access_token}', 'X-Line-Retry-Key': retry_key},
                json={'to': user_id, 'messages': [{'type': 'text', 'text': content}]}, timeout=(3, 8))
            if response.status_code == 200 or (response.status_code == 409 and response.headers.get('x-line-accepted-request-id')):
                return True, ''
            return False, self._push_error(response.status_code, response.text)
        except requests.RequestException:
            return False, 'LINE 連線中斷或逾時，可重試'

    @staticmethod
    def _push_error(status_code, body=''):
        text = (body or '').lower()
        if status_code == 400:
            if 'blocked' in text:
                return '對方已封鎖官方帳號，無法推播'
            if 'friend' in text or 'not have added' in text:
                return '對方尚未加入官方帳號，無法推播'
            return 'LINE 拒絕推播（400），請確認對方狀態'
        if status_code == 401:
            return 'LINE 授權失效，請更新 Channel Access Token'
        if status_code == 403:
            return 'LINE 權限不足，請確認 Messaging API 設定'
        if status_code == 429:
            return 'LINE 訊息額度已用完或傳送太頻繁，請稍後再試'
        if status_code >= 500:
            return 'LINE 暫時無法連線，請稍後重試'
        return f'LINE 回應 HTTP {status_code}'

    @staticmethod
    def _cloudinary_variant(url, transform):
        if not url:
            return url
        if '/upload/' in url:
            return url.replace('/upload/', f'/upload/{transform}/', 1)
        return url

    def push_user_image(self, user_id, image_url, retry_key):
        """推播單張圖片給個人；圖片需為公開 HTTPS 網址。"""
        if not isinstance(user_id, str) or not re.fullmatch(r'U[0-9a-f]{32}', user_id):
            return False, '缺少有效的 LINE 個人收件人'
        if not self.access_token:
            return False, '尚未設定 LINE Messaging API'
        if not isinstance(image_url, str) or not image_url.startswith('https://'):
            return False, '圖片必須是公開的 HTTPS 網址'
        payload = {
            'to': user_id,
            'messages': [{
                'type': 'image',
                'originalContentUrl': self._cloudinary_variant(image_url, 'w_1600,q_auto'),
                'previewImageUrl': self._cloudinary_variant(image_url, 'w_400,q_auto'),
            }],
        }
        try:
            response = requests.post('https://api.line.me/v2/bot/message/push',
                headers={'Authorization': f'Bearer {self.access_token}', 'X-Line-Retry-Key': retry_key},
                json=payload, timeout=(5, 20))
            if response.status_code == 200 or (response.status_code == 409 and response.headers.get('x-line-accepted-request-id')):
                return True, ''
            return False, self._push_error(response.status_code, response.text)
        except requests.RequestException:
            return False, 'LINE 連線中斷或逾時，可重試'
