"""Integration regressions. Requires an explicitly isolated local PostgreSQL URL."""
import os
import unittest
from urllib.parse import urlsplit
url = os.getenv('SOAR_TEST_DATABASE_URL')
if not url:
    raise unittest.SkipTest('Set SOAR_TEST_DATABASE_URL to an isolated local PostgreSQL database')
parsed = urlsplit(url.replace('postgresql+psycopg2:', 'postgresql:'))
if parsed.hostname != '127.0.0.1' or parsed.path != '/soar_validation':
    raise RuntimeError('Tests only accept localhost /soar_validation')
os.environ.update(DATABASE_URL=url, SECRET_KEY='soar-validation-only', PYTHON_DOTENV_DISABLED='1',
                  CLOUDINARY_CLOUD_NAME='soar-test', LOGIN_TRUSTED_PROXY_HOPS='0')
import json
import io
import concurrent.futures
from unittest.mock import patch
from sqlalchemy import text
from werkzeug.security import check_password_hash
from app import app
from extensions import db_service
from detail_content import validate_detail_blocks


class SoarImprovements(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        db_service._execute('TRUNCATE login_attempts')
        db_service.save_or_update_user('soar-test-admin','soar-test-admin','test-password','測試管理員','','','', 'admin')
        db_service.save_or_update_user('soar-test-user','soar-test-user','test-password','測試會員','','','', 'user')

    def admin(self):
        with self.client.session_transaction() as s:
            s['user']={'id':'soar-test-admin','role':'admin','name':'測試管理員'}

    def login(self,username='soar-test-user', password='wrong', source='127.0.0.1', client=None):
        return (client or self.client).post('/api/login',json={'username':username,'password':password},environ_base={'REMOTE_ADDR':source})

    def product(self,blocks=None):
        self.admin()
        payload={'id':'soar-test-product','name':'測試收納盒','category':'3d-print','material':'PLA_PRO','price':280,
                 'description':'舊版簡短介紹','images':[], 'items':[], 'detail_blocks':blocks or []}
        r=self.client.post('/api/admin/products',json=payload)
        self.assertEqual(r.status_code,200,r.json)
        return payload

    def test_member_api_has_no_password_and_edit_keeps_password(self):
        self.admin();r=self.client.get('/api/admin/users');self.assertEqual(r.status_code,200)
        self.assertTrue(all('password' not in u for u in r.json['data']))
        self.assertTrue(all('password' not in u for u in db_service.get_all_users()))
        db_service.save_or_update_user('soar-test-user','soar-test-user','','改名','','','','user')
        self.assertEqual(self.login(password='test-password').status_code,200)

    def test_account_limit_and_bind_share_counter(self):
        for _ in range(3):self.assertEqual(self.login().status_code,401)
        for _ in range(2):self.assertEqual(self.client.post('/api/line/bind-account',json={'username':'soar-test-user','password':'wrong','line_id':'TEST'}).status_code,400)
        r=self.login(password='test-password');self.assertEqual(r.status_code,429);self.assertGreater(int(r.headers['Retry-After']),0)
        r=self.client.post('/api/line/bind-account',json={'username':'soar-test-user','password':'wrong','line_id':'TEST'});self.assertEqual(r.status_code,429)

    def test_success_reset_and_legacy_password_upgrade(self):
        for _ in range(4):self.assertEqual(self.login().status_code,401)
        self.assertEqual(self.login(password='test-password').status_code,200)
        for _ in range(4):self.assertEqual(self.login().status_code,401)
        db_service._execute("UPDATE users SET password='legacy-test' WHERE id='soar-test-user'")
        self.assertEqual(self.login(password='legacy-test').status_code,200)
        stored=db_service._fetch_one("SELECT password FROM users WHERE id='soar-test-user'")['password']
        self.assertTrue(check_password_hash(stored,'legacy-test'))

    def test_limit_expiry_and_source(self):
        for _ in range(5):self.login()
        db_service._execute('UPDATE login_attempts SET blocked_until=0, window_start=0')
        self.assertEqual(self.login(password='test-password').status_code,200)
        db_service._execute('TRUNCATE login_attempts')
        for i in range(30):self.assertEqual(self.login(username='missing'+str(i)).status_code,401)
        self.assertEqual(self.login(username='another').status_code,429)
        self.assertEqual(self.login(username='another',source='127.0.0.2').status_code,401)

    def test_parallel_attempts_and_new_service_share_limit(self):
        def attempt(_):
            with app.test_client() as c:return self.login(client=c).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:results=list(pool.map(attempt,range(12)))
        self.assertEqual(results.count(401),5,results);self.assertEqual(results.count(429),7,results)
        from db_service import DBService
        from login_guard import password_attempt,LoginLimited
        other=DBService(url)
        with self.assertRaises(LoginLimited):
            with password_attempt(other.engine,'soar-test-user','127.0.0.2'):pass
        other.engine.dispose()

    def test_forwarded_header_not_trusted_and_database_failure_closed(self):
        for i in range(5):self.client.post('/api/login',json={'username':'soar-test-user','password':'wrong'},headers={'X-Forwarded-For':'10.0.0.'+str(i)})
        self.assertEqual(self.login().status_code,429)
        with patch('routes.auth_routes.password_attempt',side_effect=RuntimeError('offline')):
            self.assertEqual(self.login(password='test-password').status_code,503)

    def test_detail_content_roundtrip_escaping_and_legacy_fallback(self):
        blocks=[{'type':'text','text':'第一段\n<img src=x onerror=alert(1)>'},
                {'type':'image','url':'https://res.cloudinary.com/soar-test/image/upload/v1/uxprint/products/test.png','caption':'圖片介紹'},
                {'type':'text','text':'最後一段'}]
        payload=self.product(blocks)
        row=db_service._fetch_one("SELECT detail_blocks_json FROM products WHERE id='soar-test-product'")
        self.assertEqual(json.loads(row['detail_blocks_json']),blocks)
        page=self.client.get('/products/soar-test-product');self.assertEqual(page.status_code,200)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;',page.text)
        self.assertEqual(self.client.get('/products/missing').status_code,404)
        # Old callers omitting new field must preserve it.
        del payload['detail_blocks'];self.client.post('/api/admin/products',json=payload)
        self.assertEqual(json.loads(db_service._fetch_one("SELECT detail_blocks_json FROM products WHERE id='soar-test-product'")['detail_blocks_json']),blocks)
        self.product();self.assertIn('舊版簡短介紹',self.client.get('/products/soar-test-product').text)

    def test_detail_rejects_html_and_foreign_images(self):
        for block in [{'type':'html','text':'<script>x</script>'},{'type':'image','url':'javascript:alert(1)'},
                      {'type':'image','url':'https://res.cloudinary.com/other/image/upload/v1/uxprint/products/t.png'},
                      {'type':'image','url':'https://res.cloudinary.com.evil.test/soar-test/image/upload/v1/uxprint/products/t.png'}]:
            with self.assertRaises(ValueError):validate_detail_blocks([block])
        self.admin();self.assertEqual(self.client.post('/api/admin/products',json={'detail_blocks':[{'type':'image','url':'/uploads/t.png'}]}).status_code,400)

    def test_upload_failure_and_success_no_external_call(self):
        self.admin()
        from PIL import Image
        def form():
            data=io.BytesIO();Image.new('RGB',(1,1)).save(data,format='PNG');data.seek(0)
            return {'require_cloud':'1','file':(data,'test.png')}
        with patch('routes.admin_routes.cloudinary_service.upload_image',return_value=None):
            self.assertEqual(self.client.post('/api/admin/upload-image',data=form()).status_code,503)
        with patch('routes.admin_routes.cloudinary_service.upload_image',return_value='https://res.cloudinary.com/soar-test/image/upload/v1/uxprint/products/test.png'):
            r=self.client.post('/api/admin/upload-image',data=form());self.assertEqual(r.status_code,200);self.assertTrue(r.json['is_cloud'])


    def test_separate_process_shares_account_limit(self):
        for _ in range(5):self.login()
        import subprocess,sys
        code = "from sqlalchemy import create_engine; from login_guard import password_attempt,LoginLimited; import os; e=create_engine(os.environ['SOAR_TEST_DATABASE_URL']);\ntry:\n with password_attempt(e,'soar-test-user','127.0.0.2'): print('BYPASS')\nexcept LoginLimited: print('LIMITED')"
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.strip(),'LIMITED')

    def test_required_variant_color_and_atomic_color_stock(self):
        payload=self.product()
        payload['items']=[{'name':'款式 A','price':360,'colors':[{'name':'綠色'}]}]
        self.assertEqual(self.client.post('/api/admin/products',json=payload).status_code,200)
        db_service._execute("DELETE FROM inventory_logs WHERE product_id='soar-test-product'")
        db_service._execute("DELETE FROM sales_logs WHERE product_id='soar-test-product'")
        self.assertTrue(db_service.add_inventory_log('soar-test-product','測試收納盒','款式 A',3,100,'測試','','測試','綠色'))
        for item in [{'id':'soar-test-product','qty':1}, {'id':'soar-test-product','qty':1,'variant_name':'款式 A'},
                     {'id':'soar-test-product','qty':1.5,'variant_name':'款式 A','color_name':'綠色'}]:
            self.assertEqual(self.client.post('/api/orders',json={'cart':[item]}).status_code,400)
        body={'cart':[{'id':'soar-test-product','qty':2,'variant_name':'款式 A','color_name':'綠色','price':1}]}
        def order(_):
            with app.test_client() as c:return c.post('/api/orders',json=body).status_code
        with patch('routes.product_routes._run_in_background'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(order,range(2)))
        self.assertEqual(sorted(results),[200,400],results)
        rows=db_service._fetch_dicts("SELECT total_amount FROM orders WHERE id IN (SELECT order_id FROM sales_logs WHERE product_id='soar-test-product')")
        self.assertEqual(len(rows),1);self.assertEqual(float(rows[0]['total_amount']),720)


if __name__=='__main__':unittest.main()
