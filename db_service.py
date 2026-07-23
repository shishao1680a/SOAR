import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone, timedelta

class DBService:
    def __init__(self, db_url=None):
        # 取得資料庫連接網址，預設相容 Railway DATABASE_URL 變數
        url = db_url or os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/uxprint_db")
        
        # 相容 Railway/Heroku 回傳 postgres:// 協定名
        if url and url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
            
        self.db_url = url
        print(f"DEBUG: Initializing DBService for PostgreSQL (Target DB: {self.db_url.split('@')[-1] if '@' in self.db_url else 'local'})")
        self._ensure_tables_exist()

    def _get_connection(self):
        return psycopg2.connect(self.db_url)

    def _get_taiwan_now_str(self):
        tw_now = datetime.now(timezone.utc) + timedelta(hours=8)
        return tw_now.strftime("%Y-%m-%d %H:%M:%S")

    def _ensure_tables_exist(self):
        """自動建立與擴充 PostgreSQL 資料表"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. users 表 (新增 username, password, phone, role)
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS users (
                            id VARCHAR(255) PRIMARY KEY,
                            username VARCHAR(255) UNIQUE,
                            password VARCHAR(255),
                            name VARCHAR(255),
                            line_id VARCHAR(255),
                            avatar_url TEXT,
                            phone VARCHAR(255),
                            role VARCHAR(50) DEFAULT 'member',
                            register_date VARCHAR(100)
                        )
                    ''')

                    # 2. products 表 (擴充 3D設計成本 cost_price, 庫存 stock_qty, 多照片 images_json)
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS products (
                            id VARCHAR(100) PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            category VARCHAR(50) NOT NULL,
                            material VARCHAR(50) NOT NULL,
                            price NUMERIC(10, 2) NOT NULL,
                            cost_price NUMERIC(10, 2) DEFAULT 0.00,
                            stock_qty INTEGER DEFAULT 50,
                            badge VARCHAR(100),
                            image_url TEXT,
                            images_json TEXT,
                            description TEXT,
                            is_uv BOOLEAN DEFAULT FALSE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')

                    # 3. inventory_logs 表 (商品進貨紀錄)
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS inventory_logs (
                            id SERIAL PRIMARY KEY,
                            product_id VARCHAR(100),
                            product_name VARCHAR(255),
                            purchase_qty INTEGER,
                            purchase_cost NUMERIC(10, 2),
                            supplier VARCHAR(255),
                            purchase_date VARCHAR(100),
                            remark TEXT
                        )
                    ''')

                    # 4. line_groups 表 (LINE 群組維護)
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS line_groups (
                            id VARCHAR(255) PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            description TEXT,
                            created_at VARCHAR(100)
                        )
                    ''')

                    # 5. bulletins 表 (公佈欄)
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

                    # 6. orders 表 (購物車與LINE推播訂單)
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

                conn.commit()
                print("DEBUG: PostgreSQL tables verified successfully.")
                self._seed_initial_data()
        except Exception as e:
            print(f"ERROR: Table initialization failed: {e}")

    def _seed_initial_data(self):
        """播種預設管理員、商品、LINE群組與公告"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 預設管理員與成員
                    cursor.execute("SELECT COUNT(*) FROM users")
                    if cursor.fetchone()[0] == 0:
                        now_str = self._get_taiwan_now_str()
                        initial_users = [
                            ("u_admin", "admin", "admin123", "系統超級管理員", "U84920491823901", "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80", "0912345678", "admin", now_str),
                            ("u_member1", "alex88", "123456", "賽車選手 Alex #88", "U12345678901234", "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?auto=format&fit=crop&w=150&q=80", "0987654321", "member", now_str)
                        ]
                        cursor.executemany('''
                            INSERT INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''', initial_users)

                    # 預設商品
                    cursor.execute("SELECT COUNT(*) FROM products")
                    if cursor.fetchone()[0] == 0:
                        initial_products = [
                            ("p1", "VORTEX H-BLOCK 避震套件", "3d-print", "TPU_95A", 45.00, 18.00, 50, "TPU HIGH-IMPACT", 
                             "https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=600&q=80",
                             json.dumps(["https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=600&q=80", "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=600&q=80"]),
                             "Reinforced lattice structure for maximum sliding speed and impact absorption. 高密度 TPU 3D 列印套件。", False),
                            ("p2", "GLITCH DECAL UV炫彩貼紙包", "uv-print", "UV_RESIN", 18.00, 5.00, 120, "UV REACTIVE", 
                             "https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=600&q=80",
                             json.dumps(["https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=600&q=80"]),
                             "Ultra-durable UV resin prints. Scuff-resistant and glow-active under city lights. 高精度 UV 浮雕圖騰貼紙。", True),
                            ("p3", "PRO SPACER PA12 精密墊片", "3d-print", "NYLON_CF", 22.00, 8.50, 80, "NYLON-PA12", 
                             "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=600&q=80",
                             json.dumps(["https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=600&q=80"]),
                             "Precision spacers engineered for zero-wiggle performance and heat dissipation. 碳纖維強化尼龍 PA12 超高硬度墊片。", False),
                            ("p4", "TITAN SOUL PLATE 魂板底座", "3d-print", "PLA_PRO", 65.00, 25.00, 35, "PLA-PRO", 
                             "https://images.unsplash.com/photo-1508614589041-895b88991e3e?auto=format&fit=crop&w=600&q=80",
                             json.dumps(["https://images.unsplash.com/photo-1508614589041-895b88991e3e?auto=format&fit=crop&w=600&q=80"]),
                             "Custom-fit soul plates with reinforced mounting points and ultra-slick formula. 特調低摩擦係數 3D 列印魂板。", False)
                        ]
                        cursor.executemany('''
                            INSERT INTO products (id, name, category, material, price, cost_price, stock_qty, badge, image_url, images_json, description, is_uv)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''', initial_products)

                    # 預設 LINE 群組
                    cursor.execute("SELECT COUNT(*) FROM line_groups")
                    if cursor.fetchone()[0] == 0:
                        now_str = self._get_taiwan_now_str()
                        initial_groups = [
                            ("g_main_club", "UX-PRINT 社團總群", "包含全體 3D/UV 列印玩家與教練成員", now_str),
                            ("g_vip_racers", "賽車與極限選手 VIP 群", "賽事通告、高階客製化改裝件與專屬優惠訊息", now_str)
                        ]
                        cursor.executemany('''
                            INSERT INTO line_groups (id, name, description, created_at)
                            VALUES (%s, %s, %s, %s)
                        ''', initial_groups)

                    # 預設公佈欄
                    cursor.execute("SELECT COUNT(*) FROM bulletins")
                    if cursor.fetchone()[0] == 0:
                        initial_bulletins = [
                            ("b1", "🔥 【社團賽事】2026 夏季極限 3D/UV 作品改裝大賽開始報名！", "2026-07-20", "賽事公告", True, "本屆改裝大賽包含 3D 列印機構件設計組與 UV 炫彩彩繪組，獎品包含 Bambu 3D 列印機與客製列印資材！", "親愛的社友們：\n2026 夏季極限 3D/UV 作品改裝大賽即日起開放報名！", True),
                            ("b2", "📦 新進資材通知：Nylon-CF 碳纖維尼龍與亮面 UV 樹脂已上架", "2026-07-15", "資材更新", False, "全新批次高剛性碳纖維線材與日本進口 UV 抗黃化樹脂已抵達社團工坊。", "工坊目前已完成 Bambu X1C 8台機器聯網，提供更快速的 3D 打樣服務。", True)
                        ]
                        cursor.executemany('''
                            INSERT INTO bulletins (id, title, date_str, tag, is_pinned, summary, content, line_broadcasted)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ''', initial_bulletins)

                conn.commit()
        except Exception as e:
            print(f"ERROR: Initial seed failed: {e}")

    # --- User Authentication & Management ---
    def authenticate_user(self, username, password):
        """一般帳/密 登入驗證"""
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
                    return cursor.fetchone()
        except Exception as e:
            print(f"Error authenticating user: {e}")
            return None

    def get_user_by_id(self, user_id):
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                    return cursor.fetchone()
        except Exception as e:
            return None

    def get_all_users(self):
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM users ORDER BY register_date DESC")
                    return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching users: {e}")
            return []

    def save_or_update_user(self, user_id, username, password, name, line_id, avatar_url, phone, role):
        try:
            now_str = self._get_taiwan_now_str()
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            username = EXCLUDED.username,
                            password = EXCLUDED.password,
                            name = EXCLUDED.name,
                            line_id = EXCLUDED.line_id,
                            avatar_url = EXCLUDED.avatar_url,
                            phone = EXCLUDED.phone,
                            role = EXCLUDED.role
                    ''', (user_id, username, password, name, line_id, avatar_url, phone, role, now_str))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving user: {e}")
            return False

    def delete_user(self, user_id):
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error deleting user: {e}")
            return False

    # --- Product & Inventory Management ---
    def get_products(self):
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM products ORDER BY created_at ASC")
                    return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching products: {e}")
            return []

    def save_product(self, prod_id, name, category, material, price, cost_price, stock_qty, badge, image_url, images_json, description, is_uv):
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO products (id, name, category, material, price, cost_price, stock_qty, badge, image_url, images_json, description, is_uv)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            category = EXCLUDED.category,
                            material = EXCLUDED.material,
                            price = EXCLUDED.price,
                            cost_price = EXCLUDED.cost_price,
                            stock_qty = EXCLUDED.stock_qty,
                            badge = EXCLUDED.badge,
                            image_url = EXCLUDED.image_url,
                            images_json = EXCLUDED.images_json,
                            description = EXCLUDED.description,
                            is_uv = EXCLUDED.is_uv
                    ''', (prod_id, name, category, material, price, cost_price, stock_qty, badge, image_url, images_json, description, is_uv))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving product: {e}")
            return False

    def delete_product(self, prod_id):
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM products WHERE id = %s", (prod_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error deleting product: {e}")
            return False

    def add_inventory_log(self, product_id, product_name, purchase_qty, purchase_cost, supplier, remark):
        try:
            now_str = self._get_taiwan_now_str()
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. 寫入進貨紀錄
                    cursor.execute('''
                        INSERT INTO inventory_logs (product_id, product_name, purchase_qty, purchase_cost, supplier, purchase_date, remark)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (product_id, product_name, purchase_qty, purchase_cost, supplier, now_str, remark))
                    
                    # 2. 自動增加商品的庫存數量與更新進貨成本
                    cursor.execute('''
                        UPDATE products SET 
                            stock_qty = stock_qty + %s,
                            cost_price = %s
                        WHERE id = %s
                    ''', (purchase_qty, purchase_cost, product_id))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error adding inventory log: {e}")
            return False

    def get_inventory_logs(self):
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM inventory_logs ORDER BY id DESC")
                    return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching inventory logs: {e}")
            return []

    # --- LINE Groups & Bulletins ---
    def get_line_groups(self):
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM line_groups ORDER BY created_at DESC")
                    return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching LINE groups: {e}")
            return []

    def save_line_group(self, group_id, name, description):
        try:
            now_str = self._get_taiwan_now_str()
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO line_groups (id, name, description, created_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            description = EXCLUDED.description
                    ''', (group_id, name, description, now_str))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving LINE group: {e}")
            return False

    def delete_line_group(self, group_id):
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM line_groups WHERE id = %s", (group_id,))
                conn.commit()
                return True
        except Exception as e:
            return False

    def get_bulletins(self):
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM bulletins ORDER BY is_pinned DESC, date_str DESC")
                    return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching bulletins: {e}")
            return []

    def save_bulletin(self, b_id, title, date_str, tag, is_pinned, summary, content, line_broadcasted):
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO bulletins (id, title, date_str, tag, is_pinned, summary, content, line_broadcasted)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            title = EXCLUDED.title,
                            date_str = EXCLUDED.date_str,
                            tag = EXCLUDED.tag,
                            is_pinned = EXCLUDED.is_pinned,
                            summary = EXCLUDED.summary,
                            content = EXCLUDED.content,
                            line_broadcasted = EXCLUDED.line_broadcasted
                    ''', (b_id, title, date_str, tag, is_pinned, summary, content, line_broadcasted))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving bulletin: {e}")
            return False

    def delete_bulletin(self, b_id):
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM bulletins WHERE id = %s", (b_id,))
                conn.commit()
                return True
        except Exception as e:
            return False

    def save_order(self, order_id, user_id, user_name, user_line_id, items, total_amount):
        try:
            now_str = self._get_taiwan_now_str()
            items_json = json.dumps(items, ensure_ascii=False)
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO orders (id, user_id, user_name, user_line_id, items_json, total_amount, status, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (order_id, user_id, user_name, user_line_id, items_json, total_amount, 'PENDING', now_str))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving order: {e}")
            return False
