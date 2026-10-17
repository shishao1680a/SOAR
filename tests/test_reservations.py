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

    def call(self,ticket):
        return self.post(self.client,f'/api/admin/reservations/sessions/{self.sid}/call-next',{'ticket_id':ticket['id']})

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
        t=self.book(items=[{'id':'res-a','qty':2},{'id':'res-b','qty':11}]).json['ticket'];self.call(t)
        r=self.checkin(t);self.assertEqual(r.status_code,409,r.json)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM orders')['n'],0)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM sales_logs')['n'],0)
        self.assertEqual(db._fetch_one('SELECT status FROM reservations')['status'],'CALLED')
        db.add_inventory_log('res-b','res-b','-',2,30,'隔離測試','補貨')
        self.assertEqual(self.checkin(t).status_code,200)

    def test_competing_reports_never_oversell(self):
        tickets=[self.book(self.guest(n),[{'id':'res-a','qty':8}]).json['ticket'] for n in (1,2)]
        for t in tickets:self.call(t)
        def arrive(t):
            c=app.test_client();self.as_admin(c);c.get('/api/reservations/state');return self.checkin(t,c).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(arrive,tickets))
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

    def test_fifo_call_retry_does_not_advance_again(self):
        a=self.book(self.guest()).json['ticket'];b=self.book(self.guest(2)).json['ticket']
        self.assertEqual(self.call(b).status_code,409)
        self.assertEqual(self.call(a).status_code,200)
        self.assertEqual(self.call(a).status_code,200)
        self.assertEqual(service.scene(self.sid)['current_number'],1)
        self.assertEqual(self.call(b).status_code,200)

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
        t=self.book(items=[{'id':'res-a','qty':2,'variant_name':'大','variant_color':'綠','price':1}]).json['ticket']
        self.assertEqual(float(t['total_amount']),300)
        self.call(t)
        db._execute("UPDATE products SET items_json='[]' WHERE id='res-a'")
        self.assertEqual(self.checkin(t).status_code,409)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) n FROM orders')['n'],0)

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
        self.assertEqual(r.status_code,200);self.assertIn('取號不保留庫存'.encode(),r.data)

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


if __name__=='__main__':unittest.main()
