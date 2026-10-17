"""現場預約：資料庫保存隊伍、價格快照及可重試通知。"""
import json
import uuid
from decimal import Decimal, InvalidOperation
from sqlalchemy import text
from db_service import StockError


class ReservationError(ValueError):
    pass


def decode_items(raw):
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        raise ReservationError('商品款式資料錯誤，請洽管理者')
    return value


class ReservationService:
    def __init__(self, db):
        self.db = db
        with db.engine.begin() as c:
            for statement in (
                "ALTER TABLE products ADD COLUMN IF NOT EXISTS onsite_enabled BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS source VARCHAR(30) NOT NULL DEFAULT 'web'",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS reservation_session_id VARCHAR(40)",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS reservation_number INTEGER",
                """CREATE TABLE IF NOT EXISTS reservation_sessions (
                    id VARCHAR(40) PRIMARY KEY, name VARCHAR(100) NOT NULL,
                    status VARCHAR(12) NOT NULL CHECK(status IN ('OPEN','PAUSED','ENDED')),
                    next_number INTEGER NOT NULL DEFAULT 1, current_number INTEGER,
                    call_message VARCHAR(1000) NOT NULL DEFAULT '您的預約已到號，請至現場報到。',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, ended_at TIMESTAMP)""",
                "CREATE UNIQUE INDEX IF NOT EXISTS reservation_one_active ON reservation_sessions ((1)) WHERE status <> 'ENDED'",
                """CREATE TABLE IF NOT EXISTS reservations (
                    id VARCHAR(40) PRIMARY KEY, session_id VARCHAR(40) NOT NULL REFERENCES reservation_sessions(id),
                    number INTEGER NOT NULL, line_id VARCHAR(40) NOT NULL, name VARCHAR(100) NOT NULL,
                    items_json TEXT NOT NULL, total_amount NUMERIC(12,2) NOT NULL,
                    request_key VARCHAR(40) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'WAITING'
                    CHECK(status IN ('WAITING','CALLED','CHECKED_IN','CANCELLED','NO_SHOW')),
                    order_id VARCHAR(100) UNIQUE REFERENCES orders(id),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    called_at TIMESTAMP, checked_in_at TIMESTAMP,
                    UNIQUE(session_id,number), UNIQUE(session_id,line_id,request_key))""",
                "CREATE UNIQUE INDEX IF NOT EXISTS reservation_one_waiting ON reservations(session_id,line_id) WHERE status='WAITING'",
                """CREATE TABLE IF NOT EXISTS reservation_notifications (
                    id VARCHAR(40) PRIMARY KEY, reservation_id VARCHAR(40) NOT NULL REFERENCES reservations(id),
                    kind VARCHAR(12) NOT NULL, body TEXT NOT NULL, retry_key VARCHAR(40) NOT NULL,
                    status VARCHAR(12) NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
                    last_error VARCHAR(200) NOT NULL DEFAULT '', created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    attempted_at TIMESTAMP, UNIQUE(reservation_id,kind))""",
                "CREATE INDEX IF NOT EXISTS reservation_session_status ON reservations(session_id,status,number)",
            ):
                c.execute(text(statement))

    @staticmethod
    def row(result):
        row = result.first()
        return dict(row._mapping) if row else None

    def scene(self, scene_id=None, connection=None, lock=False):
        sql = 'SELECT * FROM reservation_sessions WHERE ' + ('id=:id' if scene_id else "status<>'ENDED'")
        if lock:
            sql += ' FOR UPDATE'
        if connection is not None:
            return self.row(connection.execute(text(sql), {'id': scene_id}))
        return self.db._fetch_one(sql, {'id': scene_id})

    def public_scene(self, scene_id=None):
        scene = self.scene(scene_id)
        return {k: scene[k] for k in ('id', 'name', 'status', 'current_number')} if scene else None

    def create_scene(self, name):
        name = str(name or '').strip()
        if not name or len(name) > 100:
            raise ReservationError('請輸入 1～100 字的場次名稱')
        with self.db.engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(72641801)"))
            if self.scene(connection=c):
                raise ReservationError('請先結束目前場次')
            sid = uuid.uuid4().hex
            c.execute(text("INSERT INTO reservation_sessions(id,name,status) VALUES(:id,:name,'OPEN')"), {'id': sid, 'name': name})
            return self.scene(sid, c)

    def update_scene(self, sid, action, message=None, confirmed=False):
        with self.db.engine.begin() as c:
            scene = self.scene(sid, c, True)
            if not scene or scene['status'] == 'ENDED':
                raise ReservationError('場次不存在或已結束')
            if action == 'message':
                if not isinstance(message, str) or not message.strip() or len(message) > 1000:
                    raise ReservationError('通知文字請輸入 1～1000 字')
                c.execute(text('UPDATE reservation_sessions SET call_message=:m WHERE id=:id'), {'m': message.strip(), 'id': sid})
            elif action in ('pause', 'resume'):
                c.execute(text('UPDATE reservation_sessions SET status=:status WHERE id=:id'), {'id': sid, 'status': 'PAUSED' if action == 'pause' else 'OPEN'})
            elif action == 'end':
                if not confirmed:
                    raise ReservationError('請確認取消所有未報到預約後結束場次')
                c.execute(text("UPDATE reservations SET status='CANCELLED' WHERE session_id=:id AND status IN ('WAITING','CALLED')"), {'id': sid})
                c.execute(text("UPDATE reservation_sessions SET status='ENDED',ended_at=CURRENT_TIMESTAMP WHERE id=:id"), {'id': sid})
            else:
                raise ReservationError('不支援的場次操作')
            return self.scene(sid, c)

    def snapshot(self, c, requested, onsite=True):
        if not isinstance(requested, list) or not requested or len(requested) > 50:
            raise ReservationError('請選擇 1～50 項商品')
        if any(not isinstance(it, dict) for it in requested):
            raise ReservationError('商品清單格式錯誤')
        pids = sorted({str(it.get('id') or '') for it in requested})
        rows = c.execute(text('SELECT * FROM products WHERE id=ANY(:ids) ORDER BY id FOR UPDATE'), {'ids': pids}).fetchall()
        products = {r._mapping['id']: dict(r._mapping) for r in rows}
        output = []
        for it in requested:
            p = products.get(str(it.get('id') or ''))
            if not p or (onsite and not p['onsite_enabled']):
                raise ReservationError('商品不存在或未開放現場製作，請重新選擇')
            qty = it.get('qty')
            if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 999:
                raise ReservationError('商品數量須為 1～999 的整數')
            variant = str(it.get('variant_name') or '').strip()
            color = str(it.get('variant_color') or '').strip()
            variants = decode_items(p.get('items_json') or '[]')
            selected = next((v for v in variants if str(v.get('name') or '').strip() == variant), None)
            if (variants and not selected) or (variant and not selected):
                raise ReservationError(f'商品「{p["name"]}」款式已變更，請重新選擇')
            colors = (selected or {}).get('colors') or []
            if (colors and not any(str(v.get('name') or '').strip() == color for v in colors)) or (color and not colors):
                raise ReservationError(f'商品「{p["name"]}」顏色已變更，請重新選擇')
            try:
                price = Decimal(str((selected or {}).get('price', p['price'])))
                if not price.is_finite() or price < 0 or price > Decimal('99999999.99'):
                    raise InvalidOperation
                price = price.quantize(Decimal('.01'))
            except (InvalidOperation, ValueError, TypeError):
                raise ReservationError('商品價格資料錯誤，請洽管理者')
            output.append({'id': p['id'], 'name': p['name'], 'price': str(price), 'qty': qty,
                           'variant_name': variant, 'variant_color': color})
        return output

    def add_notification(self, c, ticket, kind, body):
        c.execute(text('''INSERT INTO reservation_notifications(id,reservation_id,kind,body,retry_key)
            VALUES(:id,:rid,:kind,:body,:key) ON CONFLICT(reservation_id,kind) DO NOTHING'''),
            {'id': uuid.uuid4().hex, 'rid': ticket['id'], 'kind': kind, 'body': body, 'key': str(uuid.uuid4())})

    def reserve(self, sid, identity, name, requested, key, query_url):
        name = str(name or '').strip()
        if not name or len(name) > 100:
            raise ReservationError('姓名請輸入 1～100 字')
        try:
            key = str(uuid.UUID(str(key)))
        except (ValueError, TypeError, AttributeError):
            raise ReservationError('請重新整理頁面後取號')
        with self.db.engine.begin() as c:
            scene = self.scene(sid, c, True)
            if not scene:
                raise ReservationError('場次不存在')
            existing = self.row(c.execute(text('''SELECT * FROM reservations WHERE session_id=:sid AND line_id=:uid
                AND request_key=:key'''),
                {'sid': sid, 'uid': identity['line_id'], 'key': key}))
            if existing:
                return existing
            waiting = c.execute(text("SELECT 1 FROM reservations WHERE session_id=:sid AND line_id=:uid AND status='WAITING'"),
                                {'sid': sid, 'uid': identity['line_id']}).first()
            if waiting:
                raise ReservationError('已有等候中的預約，到號或取消後才能再取號')
            if scene['status'] != 'OPEN':
                raise ReservationError('目前未開放取號')
            items = self.snapshot(c, requested)
            total = sum(Decimal(it['price']) * it['qty'] for it in items)
            if total > Decimal('99999999.99'):
                raise ReservationError('預約金額超出上限，請減少商品數量')
            ticket = dict(id=uuid.uuid4().hex, session_id=sid, number=scene['next_number'],
                          line_id=identity['line_id'], name=name, items_json=json.dumps(items, ensure_ascii=False),
                          total_amount=total, request_key=key)
            c.execute(text('''INSERT INTO reservations(id,session_id,number,line_id,name,items_json,total_amount,request_key)
                VALUES(:id,:session_id,:number,:line_id,:name,:items_json,:total_amount,:request_key)'''), ticket)
            c.execute(text('UPDATE reservation_sessions SET next_number=next_number+1 WHERE id=:id'), {'id': sid})
            summary = '\n'.join(f'• {it["name"]} {it["variant_name"]} {it["variant_color"]} ×{it["qty"]}' for it in items)
            if len(summary) > 3500:
                summary = summary[:3500] + '\n（完整明細請開啟查詢頁）'
            body = f'【現場預約】{scene["name"]}\n您的號碼：{ticket["number"]:03d}\n{summary}\n合計：NT$ {total:,.2f}\n取號不保留庫存，報到時確認。\n查詢：{query_url}'
            self.add_notification(c, ticket, 'BOOKED', body)
            return self.row(c.execute(text('SELECT * FROM reservations WHERE id=:id'), {'id': ticket['id']}))

    def tickets(self, sid, line_id=None):
        sql = 'SELECT * FROM reservations WHERE session_id=:sid'
        if line_id:
            sql += ' AND line_id=:uid'
        return self.db._fetch_dicts(sql + ' ORDER BY number', {'sid': sid, 'uid': line_id})

    def call_next(self, sid, expected_id):
        with self.db.engine.begin() as c:
            scene = self.scene(sid, c, True)
            if not scene or scene['status'] == 'ENDED':
                raise ReservationError('場次不存在或已結束')
            previous = self.row(c.execute(text('SELECT * FROM reservations WHERE id=:id AND session_id=:sid'), {'id': expected_id, 'sid': sid}))
            if previous and previous['status'] == 'CALLED':
                return previous
            ticket = self.row(c.execute(text("SELECT * FROM reservations WHERE session_id=:sid AND status='WAITING' ORDER BY number LIMIT 1 FOR UPDATE"), {'sid': sid}))
            if not ticket or ticket['id'] != expected_id:
                raise ReservationError('隊伍已更新，請重新確認下一號')
            c.execute(text("UPDATE reservations SET status='CALLED',called_at=CURRENT_TIMESTAMP WHERE id=:id"), {'id': ticket['id']})
            c.execute(text('UPDATE reservation_sessions SET current_number=:n WHERE id=:id'), {'n': ticket['number'], 'id': sid})
            self.add_notification(c, ticket, 'CALLED', f'【{scene["name"]} 到號通知】\n{ticket["name"]}，您的號碼 {ticket["number"]:03d} 已到號。\n{scene["call_message"]}')
            return self.row(c.execute(text('SELECT * FROM reservations WHERE id=:id'), {'id': ticket['id']}))

    def ticket_action(self, sid, rid, action, line_id=None):
        with self.db.engine.begin() as c:
            scene = self.scene(sid, c, True)
            ticket = self.row(c.execute(text('SELECT * FROM reservations WHERE id=:id AND session_id=:sid FOR UPDATE'), {'id': rid, 'sid': sid}))
            if not ticket or (line_id and ticket['line_id'] != line_id):
                raise ReservationError('找不到可操作的預約')
            if action == 'check-in' and ticket['status'] == 'CHECKED_IN' and not line_id:
                return ticket
            if action == 'cancel' and ticket['status'] == 'CANCELLED':
                return ticket
            if not scene or scene['status'] == 'ENDED':
                raise ReservationError('場次已結束')
            if action == 'check-in' and not line_id:
                if ticket['status'] != 'CALLED':
                    raise ReservationError('請先叫號，再標記報到')
                items = decode_items(ticket['items_json'])
                self.snapshot(c, items, onsite=False)  # 驗證目前款式，保留原單價。
                order_id = 'ONS-' + ticket['id']
                member = self.row(c.execute(text('SELECT id FROM users WHERE line_id=:uid ORDER BY id LIMIT 1'), {'uid': ticket['line_id']}))
                self.db.save_order_with_stock(order_id, member['id'] if member else 'ONSITE', ticket['name'],
                                              ticket['line_id'], items, ticket['total_amount'], connection=c)
                c.execute(text("UPDATE orders SET source='onsite',reservation_session_id=:sid,reservation_number=:n,shipping_cost=0 WHERE id=:id"),
                          {'sid': sid, 'n': ticket['number'], 'id': order_id})
                c.execute(text("UPDATE reservations SET status='CHECKED_IN',order_id=:oid,checked_in_at=CURRENT_TIMESTAMP WHERE id=:id"), {'oid': order_id, 'id': rid})
            elif action in ('cancel', 'no-show'):
                allowed = ('WAITING', 'CALLED') if action == 'cancel' else ('CALLED',)
                if ticket['status'] not in allowed or (line_id and action != 'cancel'):
                    raise ReservationError('此狀態無法執行操作；已報到請至訂單管理處理')
                c.execute(text('UPDATE reservations SET status=:s WHERE id=:id'), {'s': 'CANCELLED' if action == 'cancel' else 'NO_SHOW', 'id': rid})
            else:
                raise ReservationError('不支援的預約操作')
            return self.row(c.execute(text('SELECT * FROM reservations WHERE id=:id'), {'id': rid}))

    def dispatch(self, nid, line_service):
        # 通知列鎖避免多人重試同一通知；不持有隊伍鎖。
        with self.db.engine.begin() as c:
            n = self.row(c.execute(text("SELECT *,created_at <= LOCALTIMESTAMP - INTERVAL '24 hours' AS retry_expired FROM reservation_notifications WHERE id=:id FOR UPDATE"), {'id': nid}))
            if not n or n['status'] in ('ACCEPTED', 'SKIPPED'):
                return
            if n['retry_expired']:
                c.execute(text("UPDATE reservation_notifications SET status='FAILED',last_error='通知超過安全重試期限，請人工核對收訊；為避免重複發送已停止重試' WHERE id=:id"), {'id': nid})
                return
            ticket = self.row(c.execute(text('SELECT * FROM reservations WHERE id=:id'), {'id': n['reservation_id']}))
            if ticket['status'] in ('CANCELLED', 'NO_SHOW'):
                c.execute(text("UPDATE reservation_notifications SET status='SKIPPED' WHERE id=:id"), {'id': nid})
                return
            try:
                ok, error = line_service.push_user_text(ticket['line_id'], n['body'], n['retry_key'])
            except Exception:
                ok, error = False, 'LINE 暫時無法連線'
            c.execute(text('''UPDATE reservation_notifications SET status=:s,attempts=attempts+1,
                last_error=:error,attempted_at=CURRENT_TIMESTAMP WHERE id=:id'''),
                {'id': nid, 's': 'ACCEPTED' if ok else 'FAILED', 'error': str(error)[:200]})

    def dispatch_ticket(self, rid, line_service):
        for n in self.db._fetch_dicts("SELECT id FROM reservation_notifications WHERE reservation_id=:id AND status IN ('PENDING','FAILED') ORDER BY created_at", {'id': rid}):
            self.dispatch(n['id'], line_service)
