import os
import json
import sqlite3
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone, timedelta

class DBService:
    def __init__(self, db_url=None):
        url = (db_url or 
               os.getenv("DATABASE_URL") or 
               os.getenv("DATABASE_PRIVATE_URL") or 
               os.getenv("DATABASE_PUBLIC_URL") or 
               os.getenv("POSTGRES_URL"))

        if url and url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)

        self.db_url = url
        self.use_sqlite = False
        self.sqlite_file = os.path.join(os.path.dirname(__file__), "uxprint_fallback.db")

        print(f"DEBUG: Initializing DBService (PG URL: {self.db_url})")
        self._ensure_tables_exist()

    def _get_connection(self):
        if self.use_sqlite:
            conn = sqlite3.connect(self.sqlite_file)
            conn.row_factory = sqlite3.Row
            return conn
        try:
            return psycopg2.connect(self.db_url)
        except Exception as e:
            print(f"WARNING: PostgreSQL Connection failed ({e}). Switching to local SQLite fallback database.")
            self.use_sqlite = True
            conn = sqlite3.connect(self.sqlite_file)
            conn.row_factory = sqlite3.Row
            self._ensure_tables_exist()
            return conn

    def _get_taiwan_now_str(self):
        tw_now = datetime.now(timezone.utc) + timedelta(hours=8)
        return tw_now.strftime("%Y-%m-%d %H:%M:%S")

    def _ensure_tables_exist(self):
        """建立資料庫與備用 SQLite 資料表"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if self.use_sqlite:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        username TEXT UNIQUE,
                        password TEXT,
                        name TEXT,
                        line_id TEXT,
                        avatar_url TEXT,
                        phone TEXT,
                        role TEXT DEFAULT 'user',
                        register_date TEXT
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        category TEXT NOT NULL,
                        material TEXT NOT NULL,
                        price REAL NOT NULL,
                        cost_price REAL DEFAULT 0.00,
                        stock_qty INTEGER DEFAULT 50,
                        badge TEXT,
                        image_url TEXT,
                        images_json TEXT,
                        description TEXT,
                        is_uv INTEGER DEFAULT 0,
                        created_at TEXT
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS inventory_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id TEXT,
                        product_name TEXT,
                        purchase_qty INTEGER,
                        purchase_cost REAL,
                        supplier TEXT,
                        purchase_date TEXT,
                        remark TEXT
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS line_groups (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        created_at TEXT
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS bulletins (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        date_str TEXT,
                        tag TEXT,
                        is_pinned INTEGER DEFAULT 0,
                        summary TEXT,
                        content TEXT,
                        line_broadcasted INTEGER DEFAULT 1,
                        created_at TEXT
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS orders (
                        id TEXT PRIMARY KEY,
                        user_id TEXT,
                        user_name TEXT,
                        user_line_id TEXT,
                        items_json TEXT,
                        total_amount REAL,
                        status TEXT DEFAULT 'PENDING',
                        created_at TEXT
                    )
                ''')
            else:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id VARCHAR(255) PRIMARY KEY,
                        username VARCHAR(255) UNIQUE,
                        password VARCHAR(255),
                        name VARCHAR(255),
                        line_id VARCHAR(255),
                        avatar_url TEXT,
                        phone VARCHAR(255),
                        role VARCHAR(50) DEFAULT 'user',
                        register_date VARCHAR(100)
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id VARCHAR(100) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        category VARCHAR(50) NOT NULL,
                        material VARCHAR(50) NOT NULL,
                        price NUMERIC(10, 2) NOT NULL,
                        cost_price NUMERIC(10, 2) DEFAULT 0.00,
                        uv_cost_price NUMERIC(10, 2) DEFAULT 0.00,
                        stock_qty INTEGER DEFAULT 50,
                        badge VARCHAR(100),
                        image_url TEXT,
                        images_json TEXT,
                        items_json TEXT DEFAULT '[]',
                        description TEXT,
                        is_uv BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS product_categories (
                        id SERIAL PRIMARY KEY,
                        code VARCHAR(100) UNIQUE,
                        name VARCHAR(255) NOT NULL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS product_materials (
                        id SERIAL PRIMARY KEY,
                        code VARCHAR(100) UNIQUE,
                        name VARCHAR(255) NOT NULL
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS inventory_logs (
                        id SERIAL PRIMARY KEY,
                        product_id VARCHAR(100),
                        product_name VARCHAR(255),
                        item_name VARCHAR(255) DEFAULT '-',
                        purchase_qty INTEGER,
                        purchase_cost NUMERIC(10, 2),
                        supplier VARCHAR(255),
                        purchase_date VARCHAR(100),
                        remark TEXT
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS line_groups (
                        id VARCHAR(255) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        created_at VARCHAR(100)
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS bulletins (
                        id VARCHAR(100) PRIMARY KEY,
                        title VARCHAR(255) NOT NULL,
                        date_str VARCHAR(50),
                        tag VARCHAR(50),
                        is_pinned BOOLEAN DEFAULT FALSE,
                        summary TEXT,
                        content TEXT,
                        line_broadcasted BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS orders (
                        id VARCHAR(100) PRIMARY KEY,
                        user_id VARCHAR(255),
                        user_name VARCHAR(255),
                        user_line_id VARCHAR(255),
                        items_json TEXT,
                        total_amount NUMERIC(10, 2),
                        status VARCHAR(50) DEFAULT 'PENDING',
                        created_at VARCHAR(100)
                    )
                ''')

            # 數據表欄位自動補全與檢核遷移 (Migration)
            try:
                if self.use_sqlite:
                    cursor.execute("PRAGMA table_info(products)")
                    p_cols = [r[1] for r in cursor.fetchall()]
                    if 'uv_cost_price' not in p_cols:
                        cursor.execute("ALTER TABLE products ADD COLUMN uv_cost_price REAL DEFAULT 0.0")
                    if 'items_json' not in p_cols:
                        cursor.execute("ALTER TABLE products ADD COLUMN items_json TEXT DEFAULT '[]'")

                    cursor.execute("PRAGMA table_info(inventory_logs)")
                    inv_cols = [r[1] for r in cursor.fetchall()]
                    if 'item_name' not in inv_cols:
                        cursor.execute("ALTER TABLE inventory_logs ADD COLUMN item_name TEXT DEFAULT '-'")
                else:
                    cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS uv_cost_price NUMERIC(10, 2) DEFAULT 0.00")
                    cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS items_json TEXT DEFAULT '[]'")
                    cursor.execute("ALTER TABLE inventory_logs ADD COLUMN IF NOT EXISTS item_name VARCHAR(255) DEFAULT '-'")
            except Exception as mig_err:
                print(f"Migration notice: {mig_err}")

            conn.commit()
            conn.close()
            self._seed_initial_data()
        except Exception as e:
            print(f"ERROR: Table initialization failed: {e}")

    def _seed_initial_data(self):
        """播種三種角色的範例帳號與初始資料"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM users")
            row = cursor.fetchone()
            count = row[0] if row else 0

            if count == 0:
                now_str = self._get_taiwan_now_str()
                initial_users = [
                    ("u_admin", "admin", "admin123", "系統超級管理員", "U84920491823901", "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80", "0912345678", "admin", now_str),
                    ("u_coach", "coach1", "coach123", "陳教練 (助理教練)", "U22345678901234", "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=150&q=80", "0922334455", "assistant_coach", now_str),
                    ("u_user1", "alex88", "123456", "賽車選手 Alex #88", "U12345678901234", "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?auto=format&fit=crop&w=150&q=80", "0987654321", "user", now_str)
                ]
                for u in initial_users:
                    cursor.execute('''
                        INSERT INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''' if not self.use_sqlite else '''
                        INSERT INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', u)

            cursor.execute("SELECT COUNT(*) FROM products")
            row = cursor.fetchone()
            p_count = row[0] if row else 0

            if p_count == 0:
                initial_products = [
                    ("p1", "VORTEX H-BLOCK 避震套件", "3d-print", "TPU_95A", 45.00, 18.00, 50, "TPU HIGH-IMPACT", 
                     "https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=600&q=80",
                     json.dumps(["https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=600&q=80"]),
                     "Reinforced lattice structure for maximum sliding speed and impact absorption. 高密度 TPU 3D 列印套件。", False),
                    ("p2", "GLITCH DECAL UV炫彩貼紙包", "uv-print", "UV_RESIN", 18.00, 5.00, 120, "UV REACTIVE", 
                     "https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=600&q=80",
                     json.dumps(["https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=600&q=80"]),
                     "Ultra-durable UV resin prints. Scuff-resistant and glow-active under city lights. 高精度 UV 浮雕圖騰貼紙。", True)
                ]
                for p in initial_products:
                    cursor.execute('''
                        INSERT INTO products (id, name, category, material, price, cost_price, stock_qty, badge, image_url, images_json, description, is_uv)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''' if not self.use_sqlite else '''
                        INSERT INTO products (id, name, category, material, price, cost_price, stock_qty, badge, image_url, images_json, description, is_uv)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', p)

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"ERROR: Initial seed failed: {e}")

    def get_user_by_line_id(self, line_id):
        """根據 LINE User ID 尋找已綁定之使用者"""
        if not line_id:
            return None
        try:
            conn = self._get_connection()
            if self.use_sqlite:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE line_id = ?", (line_id,))
                row = cursor.fetchone()
                conn.close()
                return dict(row) if row else None
            else:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM users WHERE line_id = %s", (line_id,))
                user = cursor.fetchone()
                conn.close()
                return dict(user) if user else None
        except Exception as e:
            print(f"Error fetching user by LINE ID: {e}")
            return None

    def bind_line_to_account(self, username, password, line_id, avatar_url=""):
        """將 LINE ID 與已存在之會員帳號綁定"""
        user = self.authenticate_user(username, password)
        if not user:
            return False, "查無此帳號或密碼錯誤，請確認輸入資料或前往【建立會員帳號】！", None

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "UPDATE users SET line_id = %s, avatar_url = CASE WHEN %s <> '' THEN %s ELSE avatar_url END WHERE id = %s" if not self.use_sqlite else "UPDATE users SET line_id = ?, avatar_url = CASE WHEN ? <> '' THEN ? ELSE avatar_url END WHERE id = ?"
            cursor.execute(query, (line_id, avatar_url, avatar_url, user['id']))
            conn.commit()
            conn.close()

            user['line_id'] = line_id
            if avatar_url:
                user['avatar_url'] = avatar_url
            return True, "LINE 帳號成功綁定！", user
        except Exception as e:
            return False, f"綁定失敗: {str(e)}", None

    def register_user(self, username, password, name, phone, role='user', line_id='', avatar_url=''):
        """註冊新使用者 (預設角色為 user)"""
        try:
            now_str = self._get_taiwan_now_str()
            user_id = f"u_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            avatar = avatar_url or "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80"
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            query_check = "SELECT COUNT(*) FROM users WHERE username = %s" if not self.use_sqlite else "SELECT COUNT(*) FROM users WHERE username = ?"
            cursor.execute(query_check, (username,))
            row = cursor.fetchone()
            if row and row[0] > 0:
                conn.close()
                return False, "該電話/帳號已註冊過，請直接進行帳號綁定或登入！"

            query_ins = '''
                INSERT INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''' if not self.use_sqlite else '''
                INSERT INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            cursor.execute(query_ins, (user_id, username, password, name, line_id, avatar, phone, role, now_str))
            conn.commit()
            conn.close()
            return True, "註冊成功！"
        except Exception as e:
            print(f"Error registering user: {e}")
            return False, f"註冊失敗: {str(e)}"

    def authenticate_user(self, username, password):
        """一般帳/密 登入驗證"""
        try:
            conn = self._get_connection()
            if self.use_sqlite:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
                row = cursor.fetchone()
                conn.close()
                return dict(row) if row else None
            else:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
                user = cursor.fetchone()
                conn.close()
                return dict(user) if user else None
        except Exception as e:
            print(f"Error authenticating user: {e}")
            return None

    def get_all_users(self):
        try:
            conn = self._get_connection()
            if self.use_sqlite:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users ORDER BY register_date DESC")
                rows = cursor.fetchall()
                conn.close()
                return [dict(r) for r in rows]
            else:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM users ORDER BY register_date DESC")
                users = cursor.fetchall()
                conn.close()
                return [dict(u) for u in users]
        except Exception as e:
            print(f"Error fetching users: {e}")
            return []

    def save_or_update_user(self, user_id, username, password, name, line_id, avatar_url, phone, role):
        try:
            now_str = self._get_taiwan_now_str()
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if self.use_sqlite:
                cursor.execute('''
                    INSERT OR REPLACE INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, username, password, name, line_id, avatar_url, phone, role, now_str))
            else:
                cursor.execute('''
                    INSERT INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        username = EXCLUDED.username,
                        password = CASE WHEN EXCLUDED.password <> '' THEN EXCLUDED.password ELSE users.password END,
                        name = EXCLUDED.name,
                        line_id = EXCLUDED.line_id,
                        avatar_url = EXCLUDED.avatar_url,
                        phone = EXCLUDED.phone,
                        role = EXCLUDED.role
                ''', (user_id, username, password, name, line_id, avatar_url, phone, role, now_str))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving user: {e}")
            return False

    def delete_user(self, user_id):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id = %s" if not self.use_sqlite else "DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            return False

    # --- Products & Inventory ---
    def get_products(self):
        try:
            conn = self._get_connection()
            if self.use_sqlite:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM products ORDER BY id ASC")
                rows = cursor.fetchall()
                conn.close()
                return [dict(r) for r in rows]
            else:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM products ORDER BY created_at ASC")
                prods = cursor.fetchall()
                conn.close()
                return [dict(p) for p in prods]
        except Exception as e:
            return []

    def save_product(self, prod_id, name, category, material, price, cost_price, uv_cost_price, stock_qty, badge, image_url, images_json, description, is_uv, items_json='[]'):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            if self.use_sqlite:
                cursor.execute('''
                    INSERT OR REPLACE INTO products (id, name, category, material, price, cost_price, uv_cost_price, stock_qty, badge, image_url, images_json, items_json, description, is_uv)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (prod_id, name, category, material, price, cost_price, uv_cost_price, stock_qty, badge, image_url, images_json, items_json, description, 1 if is_uv else 0))
            else:
                cursor.execute('''
                    INSERT INTO products (id, name, category, material, price, cost_price, uv_cost_price, stock_qty, badge, image_url, images_json, items_json, description, is_uv)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name, category = EXCLUDED.category, material = EXCLUDED.material,
                        price = EXCLUDED.price, cost_price = EXCLUDED.cost_price, uv_cost_price = EXCLUDED.uv_cost_price,
                        stock_qty = EXCLUDED.stock_qty, badge = EXCLUDED.badge, image_url = EXCLUDED.image_url,
                        images_json = EXCLUDED.images_json, items_json = EXCLUDED.items_json,
                        description = EXCLUDED.description, is_uv = EXCLUDED.is_uv
                ''', (prod_id, name, category, material, price, cost_price, uv_cost_price, stock_qty, badge, image_url, images_json, items_json, description, is_uv))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving product: {e}")
            return False

    def get_custom_categories(self):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            if self.use_sqlite:
                cursor.execute("SELECT * FROM product_categories ORDER BY id ASC")
            else:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM product_categories ORDER BY id ASC")
            rows = cursor.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def add_custom_category(self, code, name):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO product_categories (code, name) VALUES (%s, %s)" if not self.use_sqlite else "INSERT INTO product_categories (code, name) VALUES (?, ?)", (code, name))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding custom category: {e}")
            return False

    def get_custom_materials(self):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            if self.use_sqlite:
                cursor.execute("SELECT * FROM product_materials ORDER BY id ASC")
            else:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM product_materials ORDER BY id ASC")
            rows = cursor.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def add_custom_material(self, code, name):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO product_materials (code, name) VALUES (%s, %s)" if not self.use_sqlite else "INSERT INTO product_materials (code, name) VALUES (?, ?)", (code, name))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding custom material: {e}")
            return False

    def delete_product(self, prod_id):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products WHERE id = %s" if not self.use_sqlite else "DELETE FROM products WHERE id = ?", (prod_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            return False

    def add_inventory_log(self, product_id, product_name, item_name, purchase_qty, purchase_cost, supplier, remark):
        try:
            now_str = self._get_taiwan_now_str()
            item_name = item_name or '-'
            conn = self._get_connection()
            cursor = conn.cursor()
            if self.use_sqlite:
                cursor.execute('''
                    INSERT INTO inventory_logs (product_id, product_name, item_name, purchase_qty, purchase_cost, supplier, purchase_date, remark)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (product_id, product_name, item_name, purchase_qty, purchase_cost, supplier, now_str, remark))
                cursor.execute('''
                    UPDATE products SET stock_qty = stock_qty + ?, cost_price = ? WHERE id = ?
                ''', (purchase_qty, purchase_cost, product_id))
            else:
                cursor.execute('''
                    INSERT INTO inventory_logs (product_id, product_name, item_name, purchase_qty, purchase_cost, supplier, purchase_date, remark)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (product_id, product_name, item_name, purchase_qty, purchase_cost, supplier, now_str, remark))
                cursor.execute('''
                    UPDATE products SET stock_qty = stock_qty + %s, cost_price = %s WHERE id = %s
                ''', (purchase_qty, purchase_cost, product_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding inventory log: {e}")
            return False

    def get_inventory_logs(self):
        try:
            conn = self._get_connection()
            if self.use_sqlite:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM inventory_logs ORDER BY id DESC")
                rows = cursor.fetchall()
                conn.close()
                return [dict(r) for r in rows]
            else:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM inventory_logs ORDER BY id DESC")
                logs = cursor.fetchall()
                conn.close()
                return [dict(l) for l in logs]
        except Exception as e:
            return []

    def update_inventory_log(self, log_id, item_name, purchase_qty, purchase_cost, supplier, remark):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            if self.use_sqlite:
                cursor.execute('''
                    UPDATE inventory_logs 
                    SET item_name = ?, purchase_qty = ?, purchase_cost = ?, supplier = ?, remark = ?
                    WHERE id = ?
                ''', (item_name, purchase_qty, purchase_cost, supplier, remark, log_id))
            else:
                cursor.execute('''
                    UPDATE inventory_logs 
                    SET item_name = %s, purchase_qty = %s, purchase_cost = %s, supplier = %s, remark = %s
                    WHERE id = %s
                ''', (item_name, purchase_qty, purchase_cost, supplier, remark, log_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating inventory log {log_id}: {e}")
            return False

    def delete_inventory_log(self, log_id):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            if self.use_sqlite:
                cursor.execute("DELETE FROM inventory_logs WHERE id = ?", (int(log_id),))
            else:
                cursor.execute("DELETE FROM inventory_logs WHERE id = %s", (int(log_id),))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deleting inventory log {log_id}: {e}")
            return False

    # --- LINE Groups & Bulletins ---
    def get_line_groups(self):
        try:
            conn = self._get_connection()
            if self.use_sqlite:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM line_groups ORDER BY created_at DESC")
                rows = cursor.fetchall()
                conn.close()
                return [dict(r) for r in rows]
            else:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM line_groups ORDER BY created_at DESC")
                groups = cursor.fetchall()
                conn.close()
                return [dict(g) for g in groups]
        except Exception as e:
            return []

    def save_line_group(self, group_id, name, description):
        try:
            now_str = self._get_taiwan_now_str()
            conn = self._get_connection()
            cursor = conn.cursor()
            if self.use_sqlite:
                cursor.execute('''
                    INSERT OR REPLACE INTO line_groups (id, name, description, created_at) VALUES (?, ?, ?, ?)
                ''', (group_id, name, description, now_str))
            else:
                cursor.execute('''
                    INSERT INTO line_groups (id, name, description, created_at) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description
                ''', (group_id, name, description, now_str))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            return False

    def delete_line_group(self, group_id):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM line_groups WHERE id = %s" if not self.use_sqlite else "DELETE FROM line_groups WHERE id = ?", (group_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            return False

    def get_bulletins(self):
        try:
            conn = self._get_connection()
            if self.use_sqlite:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM bulletins ORDER BY is_pinned DESC, date_str DESC")
                rows = cursor.fetchall()
                conn.close()
                return [dict(r) for r in rows]
            else:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT * FROM bulletins ORDER BY is_pinned DESC, date_str DESC")
                b = cursor.fetchall()
                conn.close()
                return [dict(item) for item in b]
        except Exception as e:
            return []

    def save_bulletin(self, b_id, title, date_str, tag, is_pinned, summary, content, line_broadcasted):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            if self.use_sqlite:
                cursor.execute('''
                    INSERT OR REPLACE INTO bulletins (id, title, date_str, tag, is_pinned, summary, content, line_broadcasted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (b_id, title, date_str, tag, 1 if is_pinned else 0, summary, content, 1 if line_broadcasted else 0))
            else:
                cursor.execute('''
                    INSERT INTO bulletins (id, title, date_str, tag, is_pinned, summary, content, line_broadcasted)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, date_str = EXCLUDED.date_str, tag = EXCLUDED.tag,
                    is_pinned = EXCLUDED.is_pinned, summary = EXCLUDED.summary, content = EXCLUDED.content, line_broadcasted = EXCLUDED.line_broadcasted
                ''', (b_id, title, date_str, tag, is_pinned, summary, content, line_broadcasted))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            return False

    def delete_bulletin(self, b_id):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM bulletins WHERE id = %s" if not self.use_sqlite else "DELETE FROM bulletins WHERE id = ?", (b_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            return False

    def save_order(self, order_id, user_id, user_name, user_line_id, items, total_amount):
        try:
            now_str = self._get_taiwan_now_str()
            items_json = json.dumps(items, ensure_ascii=False)
            conn = self._get_connection()
            cursor = conn.cursor()
            if self.use_sqlite:
                cursor.execute('''
                    INSERT INTO orders (id, user_id, user_name, user_line_id, items_json, total_amount, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)
                ''', (order_id, user_id, user_name, user_line_id, items_json, total_amount, now_str))
            else:
                cursor.execute('''
                    INSERT INTO orders (id, user_id, user_name, user_line_id, items_json, total_amount, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', %s)
                ''', (order_id, user_id, user_name, user_line_id, items_json, total_amount, now_str))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            return False
