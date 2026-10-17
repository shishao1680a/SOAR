"""Real PostgreSQL acceptance checks; never accepts an operational database."""
import os
import unittest
from urllib.parse import urlsplit
url = os.getenv('SOAR_TEST_DATABASE_URL')
if not url:
    raise unittest.SkipTest('Requires isolated local PostgreSQL /soar_validation')
parsed = urlsplit(url.replace('postgresql+psycopg2:', 'postgresql:'))
if parsed.hostname != '127.0.0.1' or parsed.path != '/soar_validation':
    raise RuntimeError('Reservation tests only accept localhost /soar_validation')
os.environ.update(DATABASE_URL=url, PYTHON_DOTENV_DISABLED='1', SECRET_KEY='reservation-isolated-test-only')
for secret in ('LINE_CHANNEL_ACCESS_TOKEN','LINE_CHANNEL_SECRET','LINE_LOGIN_CHANNEL_ID','LINE_LOGIN_CHANNEL_SECRET'):
    os.environ.pop(secret, None)
import concurrent.futures
import json
import uuid
from unittest.mock import patch
from sqlalchemy import text
from app import app
from extensions import db_service as db, reservation_service as service, line_service
from reservation_service import ReservationError


class Reservations(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.push = patch.object(line_service, 'push_user_text', return_value=(True, ''))
        self.mock_push = self.push.start()
        self.addCleanup(self.push.stop)
        with db.engine.begin() as c:
            c.execute(text('TRUNCATE reservation_notifications,reservations,reservation_sessions,sales_logs,inventory_logs,orders RESTART IDENTITY CASCADE'))
        db.save_or_update_user('res-admin','res-admin','test-password','管理員','','','','admin')
        db.save_or_update_user('res-coach','res-coach','test-password','助教','','','','assistant_coach')
        for pid in ('res-a','res-b'):
            self.assertTrue(db.save_product(pid,pid,'3d-print','PLA_PRO',100,30,0,0,'','','[]','說明',False))
            db._execute('UPDATE products SET onsite_enabled=TRUE WHERE id=:id', {'id':pid})
            self.assertTrue(db.add_inventory_log(pid,pid,'-',10,30,'隔離測試','預約測試'))
        service.migrate_stock()
        self.sid = service.create_scene('現場測試')['id']
        self.as_admin(self.client)
        self.csrf = self.client.get('/api/reservations/state').json['csrf']

    def as_admin(self, client, uid='res-admin'):
        with client.session_transaction() as s:
            s['user']={'id':uid,'role':'admin','name':'管理員'}

    def guest(self, n=1):
        client=app.test_client()
        with client.session_transaction() as s:
            s['reservation_identity']={'line_id':'U'+format(n,'032x'),'name':'客人','friend':True}
        client.get('/api/reservations/state')
        return client

    def post(self, client, path, body=None):
        with client.session_transaction() as s:
            token=s.get('reservation_csrf','')
        return client.post(path,json=body or {},headers={'X-Reservation-CSRF':token})

    def book(self, client=None, items=None, key=None):
        client=client or self.guest()
        return self.post(client,'/api/reservations',{'session_id':self.sid,'name':'測試客人',
            'items':items or [{'id':'res-a','qty':2}], 'request_key':key or str(uuid.uuid4())})

    def call(self,ticket,key=None):
        return self.post(self.client,f'/api/admin/reservations/tickets/{ticket["id"]}/notify',{'session_id':self.sid,'request_key':key or str(uuid.uuid4())})

    def checkin(self,ticket,client=None):
        return self.post(client or self.client,f'/api/admin/reservations/tickets/{ticket["id"]}/check-in',{'session_id':self.sid})

    def test_complete_multi_item_frozen_price_and_order_cancel(self):
        g=self.guest();r=self.book(g,[{'id':'res-a','qty':2},{'id':'res-b','qty':1}]);self.assertEqual(r.status_code,200,r.json)
        t=r.json['ticket'];self.assertEqual(t['number'],1)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM orders')['n'],0)
        db._execute("UPDATE products SET price=999,onsite_enabled=FALSE WHERE id='res-a'")
        self.assertEqual(self.call(t).status_code,200)
        r=self.checkin(t);self.assertEqual(r.status_code,200,r.json)
        order=db._fetch_one('SELECT * FROM orders WHERE id=:id',{'id':r.json['ticket']['order_id']})
        self.assertEqual(float(order['total_amount']),300)
        self.assertEqual(float(order['shipping_cost']),0)
        self.assertEqual(order['source'],'onsite')
        self.assertEqual(order['reservation_number'],1)
        self.assertEqual(db._fetch_one('SELECT SUM(qty) n FROM sales_logs')['n'],3)
        self.assertTrue(db.cancel_order(order['id'])[0])
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM sales_logs')['n'],0)

    def test_same_line_parallel_and_retry_key_after_call(self):
        key=str(uuid.uuid4())
        def take(_):
            return self.book(self.guest(),key=key).json['ticket']
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(take,range(12)))
        self.assertEqual(len({t['id'] for t in results}),1)
        t=results[0];self.call(t)
        self.assertEqual(self.book(self.guest(),key=key).json['ticket']['id'],t['id'])
        self.assertEqual(self.book(self.guest()).json['ticket']['number'],2)
        self.assertEqual(self.book(self.guest(),key=key).json['ticket']['id'],t['id'])
        self.assertEqual(self.book(self.guest()).status_code,409)
        self.assertEqual(self.mock_push.call_count,3)

    def test_different_guests_parallel_unique_numbers(self):
        db.add_inventory_log('res-a','res-a','-',30,30,'隔離測試','補貨')
        def take(n):return self.book(self.guest(n)).json['ticket']['number']
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            numbers=list(pool.map(take,range(1,13)))
        self.assertEqual(sorted(numbers),list(range(1,13)))

    def test_parallel_checkin_once(self):
        t=self.book().json['ticket'];self.call(t)
        def arrive(_):
            c=app.test_client();self.as_admin(c);c.get('/api/reservations/state');return self.checkin(t,c).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            codes=list(pool.map(arrive,range(8)))
        self.assertEqual(codes,[200]*8)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM orders')['n'],1)
        self.assertEqual(db._fetch_one('SELECT SUM(qty) n FROM sales_logs')['n'],2)

    def test_stock_shortage_rolls_back_whole_ticket_then_retry(self):
        g=self.guest();items=[{'id':'res-a','qty':2},{'id':'res-b','qty':11}]
        r=self.book(g,items);self.assertEqual(r.status_code,409,r.json)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM reservations')['n'],0)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM sales_logs')['n'],0)
        self.assertEqual(service.scene(self.sid)['next_number'],1)
        db.add_inventory_log('res-b','res-b','-',2,30,'隔離測試','補貨')
        t=self.book(g,items).json['ticket'];self.assertEqual(t['number'],1)
        self.call(t);self.assertEqual(self.checkin(t).status_code,200)

    def test_competing_reservations_never_oversell(self):
        def reserve(n):return self.book(self.guest(n),[{'id':'res-a','qty':8}]).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(reserve,(1,2)))
        self.assertEqual(sorted(codes),[200,409])
        self.assertEqual(db._fetch_one('SELECT SUM(qty) n FROM sales_logs')['n'],8)

    def test_permission_csrf_and_public_privacy(self):
        g=self.guest();t=self.book(g).json['ticket'];other=self.guest(2)
        state=other.get('/api/reservations/state').json
        self.assertNotIn('line_id',json.dumps(state));self.assertNotIn('測試客人',json.dumps(state,ensure_ascii=False))
        self.assertEqual(other.get('/api/reservations/mine').json['tickets'],[])
        self.assertEqual(self.post(other,f'/api/reservations/{t["id"]}/cancel',{'session_id':self.sid}).status_code,409)
        self.assertEqual(self.post(g,'/api/admin/reservations/sessions',{'name':'偷開'}).status_code,403)
        self.as_admin(other,'res-coach')
        self.assertEqual(other.get('/api/admin/reservations').status_code,403)
        self.assertEqual(self.client.post('/api/admin/reservations/sessions',json={'name':'CSRF'}).status_code,403)
        forged=app.test_client();forged.get('/api/reservations/state')
        self.assertEqual(self.book(forged).status_code,401)

    def test_pause_cancel_no_show_end_and_new_scene(self):
        g=self.guest();t=self.book(g).json['ticket']
        service.update_scene(self.sid,'pause')
        self.assertEqual(self.book(self.guest(2)).status_code,409)
        self.assertEqual(self.call(t).status_code,200)
        self.assertEqual(self.post(g,f'/api/reservations/{t["id"]}/cancel',{'session_id':self.sid}).status_code,200)
        service.update_scene(self.sid,'resume')
        t=self.book(g).json['ticket'];self.call(t)
        self.assertEqual(self.post(self.client,f'/api/admin/reservations/tickets/{t["id"]}/no-show',{'session_id':self.sid}).status_code,200)
        waiting=self.book(g).json['ticket']
        service.update_scene(self.sid,'end',confirmed=True)
        self.assertEqual(db._fetch_one('SELECT status FROM reservations WHERE id=:id',{'id':waiting['id']})['status'],'CANCELLED')
        self.sid=service.create_scene('第二場')['id']
        self.assertEqual(self.book(g).json['ticket']['number'],1)

    def test_arbitrary_repeated_notify_and_monotonic_progress(self):
        a=self.book(self.guest()).json['ticket'];b=self.book(self.guest(2)).json['ticket']
        key=str(uuid.uuid4())
        self.assertEqual(self.call(b,key).status_code,200)
        self.assertEqual(self.call(b,key).status_code,200)
        self.assertEqual(self.mock_push.call_count,3)
        self.assertEqual(self.call(a).status_code,200)
        self.assertEqual(self.call(a).status_code,200)
        self.assertEqual(service.scene(self.sid)['current_number'],2)
        self.assertEqual(self.mock_push.call_count,5)
        self.assertEqual(self.post(self.client,f'/api/admin/reservations/sessions/{self.sid}/call-next',{'ticket_id':a['id']}).status_code,409)
        self.checkin(a);self.assertEqual(self.call(a).status_code,409)

    def test_product_flag_and_active_delete_guard(self):
        self.post(self.client,'/api/admin/reservations/products/res-a',{'enabled':False})
        self.assertEqual(self.book().status_code,409)
        self.post(self.client,'/api/admin/reservations/products/res-a',{'enabled':True})
        t=self.book().json['ticket']
        self.assertEqual(self.client.delete('/api/admin/products/res-a').status_code,409)
        service.ticket_action(self.sid,t['id'],'cancel')
        self.assertEqual(self.client.delete('/api/admin/products/res-a').status_code,200)

    def test_variants_colors_price_validation_and_reporting_change(self):
        variant=[{'name':'大','price':150,'colors':[{'name':'綠'}]}]
        db._execute('UPDATE products SET items_json=:items WHERE id=:id',{'items':json.dumps(variant),'id':'res-a'})
        self.assertEqual(self.book().status_code,409)
        db.add_inventory_log('res-a','res-a','大',2,30,'隔離測試','顏色',sub_option='綠')
        t=self.book(items=[{'id':'res-a','qty':2,'variant_name':'大','variant_color':'綠','price':1}]).json['ticket']
        self.assertEqual(float(t['total_amount']),300)
        self.call(t)
        db._execute("UPDATE products SET items_json='[]' WHERE id='res-a'")
        self.assertEqual(self.checkin(t).status_code,200)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM orders')['n'],1)

    def test_notification_failure_persists_and_retry_deduplicated(self):
        self.mock_push.side_effect=TimeoutError
        t=self.book().json['ticket'];nid=t['notifications'][0]['id']
        self.assertEqual(t['notifications'][0]['status'],'FAILED')
        self.mock_push.side_effect=None;self.mock_push.return_value=(True,'')
        for _ in range(2):self.assertEqual(self.post(self.client,f'/api/admin/reservations/notifications/{nid}/retry').status_code,200)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM reservations')['n'],1)
        self.assertEqual(self.mock_push.call_count,2)
        self.assertEqual(self.call(t).status_code,200)
        self.assertEqual(self.mock_push.call_count,3)

    def test_oauth_guest_name_only_and_friend_gate(self):
        g=app.test_client()
        with patch.object(line_service,'get_login_url',return_value='https://access.line.me/test'):
            r=g.get('/api/reservations/login?scene='+self.sid);self.assertEqual(r.status_code,200)
        with g.session_transaction() as s:state=s['oauth_state']
        with patch.object(line_service,'exchange_code_for_token',return_value={'access_token':'fake-not-a-secret'}),patch.object(line_service,'get_line_user_profile',return_value={'userId':'U'+'f'*32,'displayName':'LINE客人'}),patch.object(line_service,'get_friendship_status',return_value=False):
            r=g.get('/api/line/callback?code=fake&state='+state)
        self.assertTrue(r.location.endswith('/reservations?scene='+self.sid),r.location)
        self.assertEqual(g.get('/api/user/current').status_code,401)
        g.get('/api/reservations/state');self.assertEqual(self.book(g).status_code,409)
        self.assertEqual(g.get('/api/line/callback?code=fake&state='+state).status_code,400)
        with g.session_transaction() as s:s['reservation_identity']['friend']=True;s.modified=True
        self.assertEqual(self.book(g).status_code,200)

    def test_qr_and_mobile_page_routes(self):
        r=self.client.get(f'/api/admin/reservations/sessions/{self.sid}/qr.svg')
        self.assertEqual(r.status_code,200,r.data[:100]);self.assertIn(b'<svg',r.data)
        r=self.client.get('/reservations?scene='+self.sid)
        self.assertEqual(r.status_code,200);self.assertIn('預約成功即扣庫存'.encode(),r.data)

    def test_retry_expired_key_and_cancelled_notification_not_sent(self):
        self.mock_push.return_value=(False,'額度不足')
        g=self.guest();t=self.book(g).json['ticket'];nid=t['notifications'][0]['id']
        db._execute("UPDATE reservation_notifications SET created_at=LOCALTIMESTAMP-INTERVAL '25 hours' WHERE id=:id",{'id':nid})
        service.dispatch(nid,line_service)
        self.assertEqual(self.mock_push.call_count,1)
        self.assertIn('安全重試期限',db._fetch_one('SELECT last_error FROM reservation_notifications WHERE id=:id',{'id':nid})['last_error'])
        self.post(g,f'/api/reservations/{t["id"]}/cancel',{'session_id':self.sid})
        service.dispatch(nid,line_service)
        self.assertEqual(self.mock_push.call_count,1)

    def test_personal_line_sender_never_falls_back_to_group(self):
        # 停止 mock，驗證真正個人推播函式；HTTP 仍以 mock 攔截。
        from line_service import LineService
        sender=LineService();sender.access_token='local-fake-token';sender.group_id='test-group'
        with patch('line_service.requests.post') as send:
            self.assertFalse(sender.push_user_text('', '測試','key')[0]);send.assert_not_called()
            send.return_value.status_code=429
            self.assertFalse(sender.push_user_text('U'+'a'*32,'測試','retry-key')[0])
            self.assertEqual(send.call_args.kwargs['json']['to'],'U'+'a'*32)
            self.assertEqual(send.call_args.kwargs['headers']['X-Line-Retry-Key'],'retry-key')


    def test_sellout_checkin_and_cancel_return_once(self):
        t=self.book(items=[{'id':'res-a','qty':10}]).json['ticket']
        stock=next(p for p in db.get_products() if p['id']=='res-a')['stock_qty'];self.assertEqual(stock,0)
        self.assertEqual(self.book(self.guest(2)).status_code,409)
        self.call(t);r=self.checkin(t);self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(db._fetch_one('SELECT SUM(qty) n FROM sales_logs')['n'],10)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM sales_logs WHERE reservation_id IS NOT NULL AND order_id IS NOT NULL')['n'],1)
        self.assertEqual(self.post(self.client,f'/api/admin/reservations/tickets/{t["id"]}/cancel',{'session_id':self.sid}).status_code,409)
        self.assertTrue(db.cancel_order(r.json['ticket']['order_id'])[0]);self.assertFalse(db.cancel_order(r.json['ticket']['order_id'])[0])
        self.assertEqual(next(p for p in db.get_products() if p['id']=='res-a')['stock_qty'],10)

    def test_duplicate_lines_aggregate_and_cancel_repeated(self):
        self.assertEqual(self.book(items=[{'id':'res-a','qty':6},{'id':'res-a','qty':6}]).status_code,409)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM sales_logs')['n'],0)
        g=self.guest();t=self.book(g,items=[{'id':'res-a','qty':5},{'id':'res-a','qty':5}]).json['ticket']
        for _ in range(3):self.assertEqual(self.post(g,f'/api/reservations/{t["id"]}/cancel',{'session_id':self.sid}).status_code,200)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM sales_logs')['n'],0)

    def test_no_show_keeps_stock_can_notify_report_or_end(self):
        t=self.book(items=[{'id':'res-a','qty':3}]).json['ticket'];self.call(t)
        def miss(t):return self.post(self.client,f'/api/admin/reservations/tickets/{t["id"]}/no-show',{'session_id':self.sid})
        self.assertEqual(miss(t).status_code,200)
        self.assertEqual(db._fetch_one('SELECT SUM(qty) n FROM sales_logs')['n'],3)
        self.assertEqual(self.client.delete('/api/admin/products/res-a').status_code,409)
        self.assertEqual(self.call(t).status_code,200)
        miss(t);self.assertEqual(self.checkin(t).status_code,200)
        t2=self.book(self.guest(2)).json['ticket'];self.call(t2);miss(t2)
        service.update_scene(self.sid,'end',confirmed=True)
        self.assertEqual(db._fetch_one('SELECT status FROM reservations WHERE id=:id',{'id':t2['id']})['status'],'CANCELLED')
        self.assertEqual(db._fetch_one('SELECT SUM(qty) n FROM sales_logs')['n'],3)

    def test_reservation_and_web_checkout_race(self):
        from db_service import StockError
        def take(kind):
            if kind=='reservation':return self.book(items=[{'id':'res-a','qty':10}]).status_code==200
            try:return db.save_order_with_stock('race-web','test','test','', [{'id':'res-a','name':'res-a','qty':10,'price':100}],1000)
            except StockError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(take,('reservation','web')))
        self.assertEqual(sum(results),1)
        self.assertEqual(db._fetch_one('SELECT SUM(qty) n FROM sales_logs')['n'],10)

    def test_notify_parallel_same_key_and_failed_retry_key(self):
        t=self.book().json['ticket'];key=str(uuid.uuid4());self.mock_push.return_value=(False,'額度不足')
        def notify(_):
            c=app.test_client();self.as_admin(c);c.get('/api/reservations/state')
            return self.post(c,f'/api/admin/reservations/tickets/{t["id"]}/notify',{'session_id':self.sid,'request_key':key}).status_code
        # 失敗通知的 HTTP 重送可重試同一 LINE retry key，不能建立新業務事件。
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:codes=list(pool.map(notify,range(3)))
        self.assertEqual(codes,[200]*3)
        calls=db._fetch_dicts("SELECT * FROM reservation_notifications WHERE kind='CALLED'")
        self.assertEqual(len(calls),1)
        keys={c.args[2] for c in self.mock_push.call_args_list[1:]};self.assertEqual(keys,{calls[0]['retry_key']})
        self.mock_push.return_value=(True,'');service.dispatch(calls[0]['id'],line_service)
        self.assertEqual(self.call(t).status_code,200)
        self.assertEqual(db._fetch_one("SELECT COUNT(*) n FROM reservation_notifications WHERE kind='CALLED'")['n'],2)

    def legacy(self,n=1,qty=2,status='WAITING'):
        rid=uuid.uuid4().hex
        db._execute("""INSERT INTO reservations(id,session_id,number,line_id,name,items_json,total_amount,request_key,status)
            VALUES(:id,:sid,:n,:uid,'舊預約',:items,200,:key,:status)""",{'id':rid,'sid':self.sid,'n':n,'uid':'U'+format(n,'032x'),
            'items':json.dumps([{'id':'res-a','name':'舊名稱','qty':qty,'price':'77','variant_name':'','variant_color':''}]),'key':str(uuid.uuid4()),'status':status})
        return rid

    def test_migration_atomic_idempotent_dry_run_and_rollback(self):
        ids=[self.legacy(n,status=status) for n,status in enumerate(('WAITING','CALLED','NO_SHOW'),1)]
        db._execute("UPDATE reservation_stock_mode SET mode='MAINTENANCE'")
        self.assertEqual(service.migrate_stock(dry_run=True)['backfilled'],3)
        self.assertFalse(service.ready());self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM sales_logs')['n'],0)
        self.assertEqual(service.migrate_stock()['backfilled'],3)
        self.assertEqual(service.migrate_stock()['backfilled'],0)
        self.assertEqual(db._fetch_one('SELECT SUM(qty) n FROM sales_logs')['n'],6)
        self.assertEqual(json.loads(db._fetch_one('SELECT items_json FROM reservations WHERE id=:id',{'id':ids[0]})['items_json'])[0]['price'],'77')
        self.call({'id':ids[0]});self.checkin({'id':ids[0]})
        self.assertEqual(service.rollback_stock(),2)
        self.assertEqual(db._fetch_one('SELECT SUM(qty) n FROM sales_logs')['n'],2)
        self.assertFalse(service.ready())

    def test_migration_shortage_stops_whole_batch_and_writes_blocked(self):
        self.legacy(1,6);self.legacy(2,6,status='NO_SHOW')
        db._execute("UPDATE reservation_stock_mode SET mode='MAINTENANCE'")
        from db_service import StockError
        with self.assertRaises(StockError):service.migrate_stock()
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM sales_logs')['n'],0)
        self.assertEqual(db._fetch_one("SELECT COUNT(*) n FROM reservations WHERE stock_state='HELD'")['n'],0)
        for path in ('/api/reservations','/api/orders','/api/admin/products','/api/admin/reservations/sessions'):
            self.assertEqual(self.post(self.client,path,{}).status_code,503)

    def test_management_roles_and_notify_permissions(self):
        db.save_or_update_user('res-user','res-user','test-password','會員','','','','user')
        t=self.book().json['ticket']
        for uid in (None,'res-user','res-coach'):
            c=app.test_client()
            if uid:self.as_admin(c,uid)
            state=c.get('/api/reservations/state').json;self.assertFalse(state['is_admin'])
            self.assertEqual(c.get('/api/admin/reservations').status_code,403)
            for action in ('notify','cancel','check-in','no-show'):
                self.assertEqual(self.post(c,f'/api/admin/reservations/tickets/{t["id"]}/{action}',{'session_id':self.sid,'request_key':str(uuid.uuid4())}).status_code,403)

    def test_color_stock_and_order_edit_cannot_take_held_units(self):
        variants=[{'name':'大','price':150,'colors':[{'name':'綠'},{'name':'紅'}]}]
        db._execute('UPDATE products SET items_json=:items WHERE id=:id',{'items':json.dumps(variants),'id':'res-a'})
        db.add_inventory_log('res-a','res-a','大',2,30,'測試','綠色',sub_option='綠')
        held=[{'id':'res-a','name':'res-a','qty':2,'price':150,'variant_name':'大','variant_color':'綠'}]
        t=self.book(items=held).json['ticket']
        self.assertEqual(self.book(self.guest(2),held).status_code,409)
        db.save_order_with_stock('edit-test','test','test','',[{'id':'res-b','name':'res-b','qty':1,'price':100}],100)
        self.assertFalse(db.update_order_items('edit-test',held)[0])
        self.assertFalse(db.update_order_settlement('edit-test',held,[],{},make_settlement=False)[0])
        alias_items=[dict(held[0],item_name='大')]
        alias_items[0].pop('variant_name')
        self.assertFalse(db.update_order_items('edit-test',alias_items)[0])
        self.assertFalse(db.update_order_settlement('edit-test',alias_items,[],{},make_settlement=False)[0])
        self.assertEqual(db._fetch_one("SELECT SUM(qty) n FROM sales_logs WHERE product_id='res-b'")['n'],1)
        p=next(p for p in db.get_products() if p['id']=='res-a')
        self.assertEqual(json.loads(p['items_json'])[0]['colors'][0]['stock_qty'],0)
        self.call(t);self.assertEqual(self.checkin(t).status_code,200)


if __name__=='__main__':unittest.main()
