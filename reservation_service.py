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
                "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS stock_state VARCHAR(12) NOT NULL DEFAULT 'LEGACY'",
                "ALTER TABLE reservation_notifications ADD COLUMN IF NOT EXISTS request_key VARCHAR(40)",
                "ALTER TABLE reservation_notifications DROP CONSTRAINT IF EXISTS reservation_notifications_reservation_id_kind_key",
                "CREATE UNIQUE INDEX IF NOT EXISTS reservation_notification_action ON reservation_notifications(reservation_id,kind,request_key)",
                "CREATE UNIQUE INDEX IF NOT EXISTS reservation_single_booked ON reservation_notifications(reservation_id) WHERE kind='BOOKED'",
                "CREATE TABLE IF NOT EXISTS reservation_stock_mode (id INTEGER PRIMARY KEY CHECK(id=1), mode VARCHAR(12) NOT NULL CHECK(mode IN ('MAINTENANCE','READY')))",
                "INSERT INTO reservation_stock_mode(id,mode) VALUES(1,'MAINTENANCE') ON CONFLICT(id) DO NOTHING",
            ):
                c.execute(text(statement))

    def ready(self):
        return self.db._fetch_one('SELECT mode FROM reservation_stock_mode WHERE id=1')['mode'] == 'READY'

    def require_ready(self, c):
        # 分享鎖維持到交易結束，維護切換會等待已開始的交易完成。
        if c.execute(text('SELECT mode FROM reservation_stock_mode WHERE id=1 FOR SHARE')).scalar() != 'READY':
            raise ReservationError('庫存切換維護中，請稍後重試')

    def verify_hold(self, c, ticket):
        items = decode_items(ticket['items_json'])
        rows = c.execute(text('SELECT * FROM sales_logs WHERE reservation_id=:id ORDER BY reservation_line'), {'id':ticket['id']}).fetchall()
        if ticket['stock_state'] != 'HELD' or len(rows) != len(items):
            raise ReservationError('預約庫存紀錄不完整，請洽管理者核對')
        for index, (row, it) in enumerate(zip(rows, items)):
            r = row._mapping
            if (r['reservation_line'],r['product_id'],r['item_name'],r['sub_option'],r['qty'],r['order_id']) != (index,it['id'],it.get('variant_name') or '-',it.get('variant_color') or '',it['qty'],None):
                raise ReservationError('預約庫存明細不符，請洽管理者核對')
        return items

    def release_hold(self, c, ticket):
        items = self.verify_hold(c, ticket)
        self.db.lock_stock_products(c, items)
        c.execute(text('DELETE FROM sales_logs WHERE reservation_id=:id AND order_id IS NULL'), {'id':ticket['id']})
        c.execute(text("UPDATE reservations SET stock_state='RELEASED' WHERE id=:id"), {'id':ticket['id']})

    def migrate_stock(self, dry_run=False):
        """維護期間一次補扣舊預約；全部成功才開放。dry_run 永遠 rollback。"""
        with self.db.engine.connect() as c:
            tx = c.begin()
            try:
                c.execute(text('SELECT mode FROM reservation_stock_mode WHERE id=1 FOR UPDATE'))
                c.execute(text('SELECT id FROM reservation_sessions ORDER BY id FOR UPDATE')).fetchall()
                tickets = [dict(r._mapping) for r in c.execute(text("SELECT * FROM reservations WHERE status IN ('WAITING','CALLED','NO_SHOW') ORDER BY session_id,number FOR UPDATE"))]
                all_items = [it for t in tickets for it in decode_items(t['items_json'])]
                self.db.lock_stock_products(c, all_items)
                added = 0
                for t in tickets:
                    if t['stock_state'] == 'HELD':
                        self.verify_hold(c,t)
                        continue
                    if t['stock_state'] != 'LEGACY':
                        raise ReservationError('既有預約庫存狀態不符，停止切換')
                    if c.execute(text('SELECT 1 FROM sales_logs WHERE reservation_id=:id'), {'id':t['id']}).first():
                        raise ReservationError('既有預約已有未核對的扣減，停止切換')
                    items = decode_items(t['items_json'])
                    self.snapshot(c,items,onsite=False)  # 驗證現存商品、款色，不改舊單價。
                    self.db.deduct_stock(c,items,reservation_id=t['id'])
                    c.execute(text("UPDATE reservations SET stock_state='HELD' WHERE id=:id"), {'id':t['id']})
                    added += 1
                c.execute(text("UPDATE reservation_stock_mode SET mode='READY' WHERE id=1"))
                result = {'active':len(tickets),'backfilled':added,'dry_run':dry_run}
                tx.rollback() if dry_run else tx.commit()
                return result
            except Exception:
                tx.rollback()
                raise

    def rollback_stock(self):
        """先由部署工具停止所有新舊工作程序，再解除未報到扣減；訂單扣減保留。"""
        with self.db.engine.begin() as c:
            c.execute(text("UPDATE reservation_stock_mode SET mode='MAINTENANCE' WHERE id=1"))
            c.execute(text('SELECT id FROM reservation_sessions ORDER BY id FOR UPDATE')).fetchall()
            tickets = [dict(r._mapping) for r in c.execute(text("SELECT * FROM reservations WHERE stock_state='HELD' ORDER BY session_id,number FOR UPDATE"))]
            self.db.lock_stock_products(c,[it for t in tickets for it in decode_items(t['items_json'])])
            for ticket in tickets:
                self.release_hold(c,ticket)
                c.execute(text("UPDATE reservations SET stock_state='LEGACY' WHERE id=:id"), {'id':ticket['id']})
            return len(tickets)

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
                tickets = [dict(r._mapping) for r in c.execute(text("SELECT * FROM reservations WHERE session_id=:id AND status IN ('WAITING','CALLED','NO_SHOW') ORDER BY number FOR UPDATE"), {'id':sid})]
                self.db.lock_stock_products(c,[it for t in tickets for it in decode_items(t['items_json'])])
                for ticket in tickets:
                    self.release_hold(c,ticket)
                c.execute(text("UPDATE reservations SET status='CANCELLED' WHERE session_id=:id AND status IN ('WAITING','CALLED','NO_SHOW')"), {'id': sid})
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

    def add_notification(self, c, ticket, kind, body, key=None):
        nid = uuid.uuid4().hex
        c.execute(text("""INSERT INTO reservation_notifications(id,reservation_id,kind,body,retry_key,request_key)
            VALUES(:id,:rid,:kind,:body,:retry,:key)"""),
            {'id':nid,'rid':ticket['id'],'kind':kind,'body':body,'retry':str(uuid.uuid4()),'key':key})
        return nid

    def reserve(self, sid, identity, name, requested, key, query_url):
        name = str(name or '').strip()
        if not name or len(name) > 100:
            raise ReservationError('姓名請輸入 1～100 字')
        try:
            key = str(uuid.UUID(str(key)))
        except (ValueError, TypeError, AttributeError):
            raise ReservationError('請重新整理頁面後取號')
        with self.db.engine.begin() as c:
            self.require_ready(c)
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
            self.db.deduct_stock(c, items, reservation_id=ticket['id'])
            c.execute(text("UPDATE reservations SET stock_state='HELD' WHERE id=:id"), {'id':ticket['id']})
            c.execute(text('UPDATE reservation_sessions SET next_number=next_number+1 WHERE id=:id'), {'id': sid})
            summary = '\n'.join(f'• {it["name"]} {it["variant_name"]} {it["variant_color"]} ×{it["qty"]}' for it in items)
            if len(summary) > 3500:
                summary = summary[:3500] + '\n（完整明細請開啟查詢頁）'
            body = f'【現場預約】{scene["name"]}\n您的號碼：{ticket["number"]:03d}\n{summary}\n合計：NT$ {total:,.2f}\n預約成功即扣庫存，取消預約才釋放。\n查詢：{query_url}'
            self.add_notification(c, ticket, 'BOOKED', body)
            return self.row(c.execute(text('SELECT * FROM reservations WHERE id=:id'), {'id': ticket['id']}))

    def tickets(self, sid, line_id=None):
        sql = 'SELECT * FROM reservations WHERE session_id=:sid'
        if line_id:
            sql += ' AND line_id=:uid'
        return self.db._fetch_dicts(sql + ' ORDER BY number', {'sid': sid, 'uid': line_id})

    def notify(self, sid, rid, request_key):
        try:
            key = str(uuid.UUID(str(request_key)))
        except (ValueError,TypeError,AttributeError):
            raise ReservationError('請重新整理頁面後通知')
        with self.db.engine.begin() as c:
            self.require_ready(c)
            scene = self.scene(sid,c,True)
            ticket = self.row(c.execute(text('SELECT * FROM reservations WHERE id=:id AND session_id=:sid FOR UPDATE'), {'id':rid,'sid':sid}))
            if not ticket:
                raise ReservationError('找不到預約')
            existing = c.execute(text("SELECT id FROM reservation_notifications WHERE reservation_id=:id AND kind='CALLED' AND request_key=:key"), {'id':rid,'key':key}).scalar()
            if existing:
                return ticket,existing
            if not scene or scene['status']=='ENDED' or ticket['status'] not in ('WAITING','CALLED','NO_SHOW'):
                raise ReservationError('預約已結束，無法通知到場')
            c.execute(text("UPDATE reservations SET status='CALLED',called_at=CURRENT_TIMESTAMP WHERE id=:id"), {'id':rid})
            c.execute(text('UPDATE reservation_sessions SET current_number=GREATEST(COALESCE(current_number,0),:n) WHERE id=:id'), {'id':sid,'n':ticket['number']})
            nid = self.add_notification(c,ticket,'CALLED',f'【{scene["name"]} 到號通知】\n{ticket["name"]}，您的號碼 {ticket["number"]:03d} 已到號。\n{scene["call_message"]}',key)
            return self.row(c.execute(text('SELECT * FROM reservations WHERE id=:id'), {'id':rid})),nid

    def ticket_action(self, sid, rid, action, line_id=None):
        with self.db.engine.begin() as c:
            self.require_ready(c)
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
                if ticket['status'] not in ('CALLED','NO_SHOW'):
                    raise ReservationError('請先叫號，再標記報到')
                items = self.verify_hold(c, ticket)
                self.db.lock_stock_products(c,items)
                order_id = 'ONS-' + ticket['id']
                member = self.row(c.execute(text('SELECT id FROM users WHERE line_id=:uid ORDER BY id LIMIT 1'), {'uid': ticket['line_id']}))
                c.execute(text("""INSERT INTO orders(id,user_id,user_name,user_line_id,items_json,total_amount,status,created_at)
                    VALUES(:id,:uid,:name,:line,:items,:total,'PENDING',:now)"""),
                    {'id':order_id,'uid':member['id'] if member else 'ONSITE','name':ticket['name'],
                     'line':ticket['line_id'],'items':ticket['items_json'],'total':ticket['total_amount'],'now':self.db._get_taiwan_now_str()})
                c.execute(text('UPDATE sales_logs SET order_id=:oid WHERE reservation_id=:id AND order_id IS NULL'), {'oid':order_id,'id':rid})
                c.execute(text("UPDATE orders SET source='onsite',reservation_session_id=:sid,reservation_number=:n,shipping_cost=0 WHERE id=:id"),
                          {'sid': sid, 'n': ticket['number'], 'id': order_id})
                c.execute(text("UPDATE reservations SET status='CHECKED_IN',stock_state='TRANSFERRED',order_id=:oid,checked_in_at=CURRENT_TIMESTAMP WHERE id=:id"), {'oid': order_id, 'id': rid})
            elif action in ('cancel', 'no-show'):
                allowed = ('WAITING', 'CALLED', 'NO_SHOW') if action == 'cancel' else ('CALLED',)
                if ticket['status'] not in allowed or (line_id and action != 'cancel'):
                    raise ReservationError('此狀態無法執行操作；已報到請至訂單管理處理')
                if action == 'cancel':
                    self.release_hold(c,ticket)
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
            if ticket['status'] in ('CANCELLED', 'CHECKED_IN'):
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
