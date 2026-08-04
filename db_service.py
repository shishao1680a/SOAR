import os
import json
import re
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash


class StockError(Exception):
    """下單時庫存不足（在資料庫交易內檢查後拋出）。"""


class DBService:
    """PostgreSQL 資料存取層（SQLAlchemy Core + 連線池）。

    - 使用 SQLAlchemy engine / QueuePool，避免每個請求重新建立連線
    - 密碼以 werkzeug 雜湊儲存，登入時自動將舊明文密碼升級為雜湊
    - 啟動時若資料庫無法連線會直接失敗（fail-fast），不做 SQLite 降級
    """

    POOL_SIZE = 5
    MAX_OVERFLOW = 10
    POOL_RECYCLE = 1800

    def __init__(self, db_url=None):
        url = (
            db_url
            or os.getenv("DATABASE_URL")
            or os.getenv("DATABASE_PRIVATE_URL")
            or os.getenv("DATABASE_PUBLIC_URL")
            or os.getenv("POSTGRES_URL")
        )
        if not url:
            raise RuntimeError("DATABASE_URL 未設定，無法初始化資料庫連線！")
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)

        self.db_url = url
        self.engine = create_engine(
            url,
            pool_size=self.POOL_SIZE,
            max_overflow=self.MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=self.POOL_RECYCLE,
        )

        self._log_db_target()
        self._ensure_tables_exist()

        # gunicorn --preload：啟動時完成建表/種子後釋放連線池，
        # 避免 fork 出的 worker 共用父程序建立的連線
        self.engine.dispose()

    # ---------- 連線管理 ----------

    def _log_db_target(self):
        """只輸出 host/db，避免把連線字串（含密碼）寫進 log。"""
        try:
            rest = self.db_url.split("@", 1)[1]
            host_part, _, db_part = rest.partition("/")
            dbname = db_part.split("?", 1)[0]
            print(f"DEBUG: Initializing DBService (host={host_part}, db={dbname or '-'})")
        except Exception:
            print("DEBUG: Initializing DBService")

    def _fetch_dicts(self, sql, params=None):
        """執行查詢並回傳 list[dict]。"""
        with self.engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            return [dict(row._mapping) for row in result]

    def _fetch_one(self, sql, params=None):
        """執行查詢並回傳單筆 dict 或 None。"""
        with self.engine.connect() as conn:
            row = conn.execute(text(sql), params or {}).first()
            return dict(row._mapping) if row else None

    def _execute(self, sql, params=None):
        """執行寫入並自動 commit（失敗自動 rollback）。"""
        with self.engine.begin() as conn:
            conn.execute(text(sql), params or {})

    def _get_taiwan_now_str(self):
        tw_now = datetime.now(timezone.utc) + timedelta(hours=8)
        return tw_now.strftime("%Y-%m-%d %H:%M:%S")

    # ---------- 建表 / 遷移 / 種子資料 ----------

    def _ensure_tables_exist(self):
        """建立 PostgreSQL 資料表、補欄位遷移與常用索引。"""
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
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
                """))
                conn.execute(text("""
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
                        designer_ratio NUMERIC(5, 2) DEFAULT 20,
                        packager_ratio NUMERIC(5, 2) DEFAULT 60,
                        platform_ratio NUMERIC(5, 2) DEFAULT 20,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS product_categories (
                        id SERIAL PRIMARY KEY,
                        code VARCHAR(100) UNIQUE,
                        name VARCHAR(255) NOT NULL
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS product_materials (
                        id SERIAL PRIMARY KEY,
                        code VARCHAR(100) UNIQUE,
                        name VARCHAR(255) NOT NULL
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS inventory_logs (
                        id SERIAL PRIMARY KEY,
                        product_id VARCHAR(100),
                        product_name VARCHAR(255),
                        item_name VARCHAR(255) DEFAULT '-',
                        purchase_qty INTEGER,
                        purchase_cost NUMERIC(10, 2),
                        supplier VARCHAR(255),
                        purchase_date VARCHAR(100),
                        remark TEXT,
                        operator_name VARCHAR(100) DEFAULT '管理員'
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS material_purchases (
                        id SERIAL PRIMARY KEY,
                        material_name VARCHAR(255) NOT NULL,
                        total_capacity VARCHAR(255),
                        purchase_cost NUMERIC(10, 2) NOT NULL,
                        purchase_qty INTEGER NOT NULL,
                        supplier VARCHAR(255),
                        purchase_date VARCHAR(100),
                        remark TEXT,
                        operator_name VARCHAR(100) DEFAULT '管理員'
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS line_groups (
                        id VARCHAR(255) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        created_at VARCHAR(100)
                    )
                """))
                conn.execute(text("""
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
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS orders (
                        id VARCHAR(100) PRIMARY KEY,
                        user_id VARCHAR(255),
                        user_name VARCHAR(255),
                        user_line_id VARCHAR(255),
                        items_json TEXT,
                        total_amount NUMERIC(10, 2),
                        status VARCHAR(50) DEFAULT 'PENDING',
                        other_cost NUMERIC(10, 2) DEFAULT 0,
                        shipping_cost NUMERIC(10, 2) DEFAULT 60,
                        net_profit NUMERIC(10, 2) DEFAULT 0,
                        shipped_at VARCHAR(100),
                        created_at VARCHAR(100)
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS sales_logs (
                        id SERIAL PRIMARY KEY,
                        order_id VARCHAR(100),
                        product_id VARCHAR(100),
                        product_name VARCHAR(255),
                        item_name VARCHAR(255) DEFAULT '-',
                        qty INTEGER DEFAULT 0,
                        created_at VARCHAR(100)
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS order_materials (
                        id SERIAL PRIMARY KEY,
                        order_id VARCHAR(100),
                        product_id VARCHAR(100),
                        item_name VARCHAR(255) DEFAULT '-',
                        material_name VARCHAR(255),
                        capacity_used NUMERIC(12, 3) DEFAULT 0,
                        unit_cost NUMERIC(10, 4) DEFAULT 0,
                        cost NUMERIC(10, 2) DEFAULT 0
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS order_settlements (
                        id SERIAL PRIMARY KEY,
                        order_id VARCHAR(100),
                        product_id VARCHAR(100),
                        item_name VARCHAR(255) DEFAULT '-',
                        sales_amount NUMERIC(10, 2) DEFAULT 0,
                        material_cost NUMERIC(10, 2) DEFAULT 0,
                        other_cost NUMERIC(10, 2) DEFAULT 0,
                        shipping_cost NUMERIC(10, 2) DEFAULT 0,
                        net_profit NUMERIC(10, 2) DEFAULT 0,
                        designer_user_id VARCHAR(255),
                        packager_user_id VARCHAR(255),
                        designer_ratio NUMERIC(5, 2) DEFAULT 20,
                        packager_ratio NUMERIC(5, 2) DEFAULT 60,
                        platform_ratio NUMERIC(5, 2) DEFAULT 20,
                        designer_amount NUMERIC(10, 2) DEFAULT 0,
                        packager_amount NUMERIC(10, 2) DEFAULT 0,
                        platform_amount NUMERIC(10, 2) DEFAULT 0,
                        settled_at VARCHAR(100)
                    )
                """))

                # 欄位補全遷移（舊資料庫）
                conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS uv_cost_price NUMERIC(10, 2) DEFAULT 0.00"))
                conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS items_json TEXT DEFAULT '[]'"))
                conn.execute(text("ALTER TABLE inventory_logs ADD COLUMN IF NOT EXISTS item_name VARCHAR(255) DEFAULT '-'"))
                conn.execute(text("ALTER TABLE inventory_logs ADD COLUMN IF NOT EXISTS operator_name VARCHAR(255) DEFAULT '管理員'"))
                conn.execute(text("ALTER TABLE material_purchases ADD COLUMN IF NOT EXISTS total_capacity VARCHAR(255) DEFAULT ''"))
                conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS other_cost NUMERIC(10, 2) DEFAULT 0"))
                conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_cost NUMERIC(10, 2) DEFAULT 60"))
                conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS net_profit NUMERIC(10, 2) DEFAULT 0"))
                conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipped_at VARCHAR(100)"))
                conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS designer_ratio NUMERIC(5, 2) DEFAULT 20"))
                conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS packager_ratio NUMERIC(5, 2) DEFAULT 60"))
                conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS platform_ratio NUMERIC(5, 2) DEFAULT 20"))

                # 常用索引
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_inventory_logs_product_id ON inventory_logs (product_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_inventory_logs_product_name ON inventory_logs (product_name)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_material_purchases_material_name ON material_purchases (material_name)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_line_id ON users (line_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sales_logs_product_id ON sales_logs (product_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sales_logs_order_id ON sales_logs (order_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_settlements_designer ON order_settlements (designer_user_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_settlements_packager ON order_settlements (packager_user_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_settlements_settled_at ON order_settlements (settled_at)"))

            self._seed_initial_data()
            self._normalize_material_capacity()
        except Exception as e:
            print(f"ERROR: Table initialization failed: {e}")
            raise

    def _seed_initial_data(self):
        """播種三種角色的範例帳號與初始資料（密碼一律存雜湊）。"""
        try:
            with self.engine.begin() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0

                if count == 0:
                    now_str = self._get_taiwan_now_str()
                    initial_users = [
                        ("u_admin", "admin", generate_password_hash("admin123"), "系統超級管理員",
                         "U84920491823901",
                         "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80",
                         "0912345678", "admin", now_str),
                        ("u_coach", "coach1", generate_password_hash("coach123"), "陳教練 (助理教練)",
                         "U22345678901234",
                         "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=150&q=80",
                         "0922334455", "assistant_coach", now_str),
                        ("u_user1", "alex88", generate_password_hash("123456"), "賽車選手 Alex #88",
                         "U12345678901234",
                         "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?auto=format&fit=crop&w=150&q=80",
                         "0987654321", "user", now_str),
                    ]
                    for u in initial_users:
                        conn.execute(text("""
                            INSERT INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                            VALUES (:id, :username, :password, :name, :line_id, :avatar_url, :phone, :role, :register_date)
                        """), {
                            "id": u[0], "username": u[1], "password": u[2], "name": u[3],
                            "line_id": u[4], "avatar_url": u[5], "phone": u[6],
                            "role": u[7], "register_date": u[8],
                        })

                p_count = conn.execute(text("SELECT COUNT(*) FROM products")).scalar() or 0

                if p_count == 0:
                    initial_products = [
                        ("p1", "VORTEX H-BLOCK 避震套件", "3d-print", "TPU_95A", 45.00, 18.00, 50,
                         "TPU HIGH-IMPACT",
                         "https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=600&q=80",
                         json.dumps(["https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=600&q=80"]),
                         "Reinforced lattice structure for maximum sliding speed and impact absorption. 高密度 TPU 3D 列印套件。",
                         False),
                        ("p2", "GLITCH DECAL UV炫彩貼紙包", "uv-print", "UV_RESIN", 18.00, 5.00, 120,
                         "UV REACTIVE",
                         "https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=600&q=80",
                         json.dumps(["https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=600&q=80"]),
                         "Ultra-durable UV resin prints. Scuff-resistant and glow-active under city lights. 高精度 UV 浮雕圖騰貼紙。",
                         True),
                    ]
                    for p in initial_products:
                        conn.execute(text("""
                            INSERT INTO products (id, name, category, material, price, cost_price, stock_qty, badge,
                                                  image_url, images_json, description, is_uv)
                            VALUES (:id, :name, :category, :material, :price, :cost_price, :stock_qty, :badge,
                                    :image_url, :images_json, :description, :is_uv)
                        """), {
                            "id": p[0], "name": p[1], "category": p[2], "material": p[3],
                            "price": p[4], "cost_price": p[5], "stock_qty": p[6], "badge": p[7],
                            "image_url": p[8], "images_json": p[9], "description": p[10], "is_uv": p[11],
                        })
        except Exception as e:
            print(f"ERROR: Initial seed failed: {e}")

    @staticmethod
    def _parse_capacity_number(value):
        """把容量文字（1kg / 500ml / 1000g / 1000）解析成公克數值；無法解析回傳 None。"""
        if value is None:
            return None
        s = str(value).strip().lower().replace(",", "")
        if not s:
            return None
        m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([a-z]*)$", s)
        if not m:
            return None
        num = float(m.group(1))
        unit = m.group(2)
        if unit in ("", "g", "ml", "cc"):
            return num
        if unit == "kg":
            return num * 1000
        if unit == "l":
            return num * 1000
        if unit == "mg":
            return num / 1000
        return None

    def _normalize_material_capacity(self):
        """一次性把 total_capacity 的舊文字值（1kg/500ml...）轉成數字（公克），重複執行安全。"""
        try:
            rows = self._fetch_dicts("SELECT id, total_capacity FROM material_purchases")
            with self.engine.begin() as conn:
                for r in rows:
                    cap = self._parse_capacity_number(r.get('total_capacity'))
                    if cap is None:
                        continue
                    new_val = f"{cap:g}"
                    if str(r.get('total_capacity') or '').strip() != new_val:
                        conn.execute(
                            text("UPDATE material_purchases SET total_capacity = :v WHERE id = :id"),
                            {"v": new_val, "id": r["id"]},
                        )
        except Exception as e:
            print(f"WARNING: normalize material capacity failed: {e}")

    # ---------- 使用者 / 認證 ----------

    def get_user_by_line_id(self, line_id):
        """根據 LINE User ID 尋找已綁定之使用者"""
        if not line_id:
            return None
        try:
            return self._fetch_one("SELECT * FROM users WHERE line_id = :line_id", {"line_id": line_id})
        except Exception as e:
            print(f"Error fetching user by LINE ID: {e}")
            return None

    def bind_line_to_account(self, username, password, line_id, avatar_url=""):
        """將 LINE ID 與已存在之會員帳號綁定"""
        user = self.authenticate_user(username, password)
        if not user:
            return False, "查無此帳號或密碼錯誤，請確認輸入資料或前往【建立會員帳號】！", None

        try:
            self._execute("""
                UPDATE users SET line_id = :line_id,
                    avatar_url = CASE WHEN :avatar_url <> '' THEN :avatar_url ELSE avatar_url END
                WHERE id = :id
            """, {"line_id": line_id, "avatar_url": avatar_url, "id": user['id']})

            user['line_id'] = line_id
            if avatar_url:
                user['avatar_url'] = avatar_url
            return True, "LINE 帳號成功綁定！", user
        except Exception as e:
            print(f"Error binding LINE account: {e}")
            return False, f"綁定失敗: {str(e)}", None

    def register_user(self, username, password, name, phone, role='user', line_id='', avatar_url=''):
        """註冊新使用者（密碼存雜湊，ID 用 uuid 避免撞號）"""
        try:
            now_str = self._get_taiwan_now_str()
            user_id = f"u_{uuid.uuid4().hex[:12]}"
            avatar = avatar_url or "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80"
            password_hash = generate_password_hash(password)

            with self.engine.begin() as conn:
                count = conn.execute(
                    text("SELECT COUNT(*) FROM users WHERE username = :username"),
                    {"username": username},
                ).scalar() or 0
                if count > 0:
                    return False, "該帳號已註冊過，請直接進行帳號綁定或登入！"

                conn.execute(text("""
                    INSERT INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                    VALUES (:id, :username, :password, :name, :line_id, :avatar_url, :phone, :role, :register_date)
                """), {
                    "id": user_id, "username": username, "password": password_hash,
                    "name": name, "line_id": line_id, "avatar_url": avatar,
                    "phone": phone, "role": role, "register_date": now_str,
                })
            return True, "註冊成功！"
        except Exception as e:
            print(f"Error registering user: {e}")
            return False, f"註冊失敗: {str(e)}"

    def authenticate_user(self, username, password):
        """帳號/密碼登入驗證（支援舊明文密碼自動升級為雜湊）"""
        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    text("SELECT * FROM users WHERE username = :username"),
                    {"username": username},
                ).first()
                if not row:
                    return None

                user = dict(row._mapping)
                stored = user['password'] or ''
                is_hash = stored.startswith(("pbkdf2:", "scrypt:", "sha256:", "md5:"))
                ok = check_password_hash(stored, password) if is_hash else (stored == password)

                if ok and not is_hash:
                    # 舊版明文密碼：登入成功後升級為雜湊
                    conn.execute(
                        text("UPDATE users SET password = :password WHERE id = :id"),
                        {"password": generate_password_hash(password), "id": user['id']},
                    )
                if ok:
                    return user
                return None
        except Exception as e:
            print(f"Error authenticating user: {e}")
            return None

    def get_all_users(self):
        try:
            return self._fetch_dicts("SELECT * FROM users ORDER BY register_date DESC")
        except Exception as e:
            print(f"Error fetching users: {e}")
            return []

    def save_or_update_user(self, user_id, username, password, name, line_id, avatar_url, phone, role):
        try:
            now_str = self._get_taiwan_now_str()
            # 密碼為空表示保留原密碼；非空且不是雜湊時才重新雜湊
            if password and not password.startswith(("pbkdf2:", "scrypt:", "sha256:", "md5:")):
                password = generate_password_hash(password)

            self._execute("""
                INSERT INTO users (id, username, password, name, line_id, avatar_url, phone, role, register_date)
                VALUES (:id, :username, :password, :name, :line_id, :avatar_url, :phone, :role, :register_date)
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    password = CASE WHEN EXCLUDED.password <> '' THEN EXCLUDED.password ELSE users.password END,
                    name = EXCLUDED.name,
                    line_id = EXCLUDED.line_id,
                    avatar_url = EXCLUDED.avatar_url,
                    phone = EXCLUDED.phone,
                    role = EXCLUDED.role
            """, {
                "id": user_id, "username": username, "password": password,
                "name": name, "line_id": line_id, "avatar_url": avatar_url,
                "phone": phone, "role": role, "register_date": now_str,
            })
            return True
        except Exception as e:
            print(f"Error saving user: {e}")
            return False

    def delete_user(self, user_id):
        try:
            self._execute("DELETE FROM users WHERE id = :id", {"id": user_id})
            return True
        except Exception as e:
            print(f"Error deleting user {user_id}: {e}")
            return False

    # ---------- 商品與庫存 ----------

    def get_products(self):
        """取得商品列表，並以單一 SQL 聚合計算庫存（避免在 Python 做 O(P×L) 巢狀迴圈）"""
        try:
            rows = self._fetch_dicts("""
                SELECT p.*, l.item_name AS log_item_name,
                       COALESCE(SUM(l.purchase_qty), 0) AS log_qty
                FROM products p
                LEFT JOIN inventory_logs l
                  ON (l.product_id IS NOT NULL AND l.product_id = p.id)
                  OR (l.product_name IS NOT NULL AND l.product_name = p.name)
                GROUP BY p.id, l.item_name
                ORDER BY p.id ASC
            """)

            sales_rows = self._fetch_dicts("""
                SELECT product_id, product_name, item_name, SUM(qty) AS sold_qty
                FROM sales_logs
                GROUP BY product_id, product_name, item_name
            """)

            prods = []
            by_id = {}
            for r in rows:
                pid = r['id']
                prod = by_id.get(pid)
                if prod is None:
                    prod = dict(r)
                    prod.pop('log_item_name', None)
                    prod.pop('log_qty', None)
                    prod['stock_qty'] = 0
                    prod['_item_stock'] = {}
                    by_id[pid] = prod
                    prods.append(prod)

                item_name = (r['log_item_name'] or '-').strip()
                qty = int(r['log_qty'] or 0)
                if item_name:
                    prod['stock_qty'] += qty
                    prod['_item_stock'][item_name] = prod['_item_stock'].get(item_name, 0) + qty

            # 以 product_id / product_name 建立索引，避免逐商品掃全部銷售紀錄
            sales_by_pid = {}
            sales_by_pname = {}
            for sg in sales_rows:
                if sg.get('product_id'):
                    sales_by_pid.setdefault(str(sg['product_id']).strip(), []).append(sg)
                if sg.get('product_name'):
                    sales_by_pname.setdefault(str(sg['product_name']).strip(), []).append(sg)

            for p in prods:
                try:
                    # 商品級已售數量（以 product_id 或 product_name 對應，同一批只算一次）
                    pid = str(p['id'])
                    pname = (p.get('name') or '').strip()
                    merged_sales = {}
                    for sg in sales_by_pid.get(pid, []) + sales_by_pname.get(pname, []):
                        key = (sg.get('product_id'), sg.get('product_name'), sg.get('item_name'))
                        merged_sales[key] = sg
                    sold_total = sum(int(sg.get('sold_qty') or 0) for sg in merged_sales.values())
                    p['stock_qty'] = max(0, int(p['stock_qty']) - sold_total)

                    raw = p.get('items_json') or '[]'
                    items_arr = json.loads(raw) if isinstance(raw, str) else (raw or [])
                    if isinstance(items_arr, list):
                        for itm in items_arr:
                            itm_name = (itm.get('name') or itm.get('item_name') or '').strip()
                            item_purchased = sum(
                                qty for key, qty in p['_item_stock'].items()
                                if key == itm_name or key == '-' or key == '-- 全品項預設/主商品 --'
                            )
                            item_sold = sum(
                                int(sg.get('sold_qty') or 0) for sg in merged_sales.values()
                                if (sg.get('item_name') or '-').strip() in (itm_name, '-', '-- 全品項預設/主商品 --')
                            )
                            itm['stock_qty'] = max(0, item_purchased - item_sold)
                        p['items_json'] = json.dumps(items_arr, ensure_ascii=False)
                except Exception as ex:
                    print(f"Error calculating item stock for product {p.get('id')}: {ex}")
                p.pop('_item_stock', None)

            return prods
        except Exception as e:
            print(f"Error fetching products: {e}")
            return []

    def save_product(self, prod_id, name, category, material, price, cost_price, uv_cost_price,
                     stock_qty, badge, image_url, images_json, description, is_uv, items_json='[]',
                     designer_ratio=20, packager_ratio=60, platform_ratio=20):
        try:
            self._execute("""
                INSERT INTO products (id, name, category, material, price, cost_price, uv_cost_price, stock_qty,
                                      badge, image_url, images_json, items_json, description, is_uv,
                                      designer_ratio, packager_ratio, platform_ratio)
                VALUES (:id, :name, :category, :material, :price, :cost_price, :uv_cost_price, :stock_qty,
                        :badge, :image_url, :images_json, :items_json, :description, :is_uv,
                        :designer_ratio, :packager_ratio, :platform_ratio)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, category = EXCLUDED.category, material = EXCLUDED.material,
                    price = EXCLUDED.price, cost_price = EXCLUDED.cost_price,
                    uv_cost_price = EXCLUDED.uv_cost_price, stock_qty = EXCLUDED.stock_qty,
                    badge = EXCLUDED.badge, image_url = EXCLUDED.image_url,
                    images_json = EXCLUDED.images_json, items_json = EXCLUDED.items_json,
                    description = EXCLUDED.description, is_uv = EXCLUDED.is_uv,
                    designer_ratio = EXCLUDED.designer_ratio,
                    packager_ratio = EXCLUDED.packager_ratio,
                    platform_ratio = EXCLUDED.platform_ratio
            """, {
                "id": prod_id, "name": name, "category": category, "material": material,
                "price": price, "cost_price": cost_price, "uv_cost_price": uv_cost_price,
                "stock_qty": stock_qty, "badge": badge, "image_url": image_url,
                "images_json": images_json, "items_json": items_json,
                "description": description, "is_uv": is_uv,
                "designer_ratio": designer_ratio, "packager_ratio": packager_ratio,
                "platform_ratio": platform_ratio,
            })
            return True
        except Exception as e:
            print(f"Error saving product: {e}")
            return False

    def get_custom_categories(self):
        try:
            return self._fetch_dicts("SELECT * FROM product_categories ORDER BY id ASC")
        except Exception as e:
            print(f"Error fetching custom categories: {e}")
            return []

    def add_custom_category(self, code, name):
        try:
            self._execute(
                "INSERT INTO product_categories (code, name) VALUES (:code, :name)",
                {"code": code, "name": name},
            )
            return True
        except Exception as e:
            print(f"Error adding custom category: {e}")
            return False

    def get_custom_materials(self):
        try:
            return self._fetch_dicts("SELECT * FROM product_materials ORDER BY id ASC")
        except Exception as e:
            print(f"Error fetching custom materials: {e}")
            return []

    def add_custom_material(self, code, name):
        try:
            self._execute(
                "INSERT INTO product_materials (code, name) VALUES (:code, :name)",
                {"code": code, "name": name},
            )
            return True
        except Exception as e:
            print(f"Error adding custom material: {e}")
            return False

    def delete_product(self, prod_id):
        try:
            self._execute("DELETE FROM products WHERE id = :id", {"id": prod_id})
            return True
        except Exception as e:
            print(f"Error deleting product {prod_id}: {e}")
            return False

    def add_inventory_log(self, product_id, product_name, item_name, purchase_qty, purchase_cost,
                          supplier, remark, operator_name='管理員'):
        try:
            now_str = self._get_taiwan_now_str()
            item_name = item_name or '-'
            operator_name = operator_name or '管理員'
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO inventory_logs (product_id, product_name, item_name, purchase_qty, purchase_cost,
                                                supplier, purchase_date, remark, operator_name)
                    VALUES (:product_id, :product_name, :item_name, :purchase_qty, :purchase_cost,
                            :supplier, :purchase_date, :remark, :operator_name)
                """), {
                    "product_id": product_id, "product_name": product_name, "item_name": item_name,
                    "purchase_qty": purchase_qty, "purchase_cost": purchase_cost,
                    "supplier": supplier, "purchase_date": now_str,
                    "remark": remark, "operator_name": operator_name,
                })
                conn.execute(text("""
                    UPDATE products SET stock_qty = stock_qty + :qty, cost_price = :cost WHERE id = :pid
                """), {"qty": purchase_qty, "cost": purchase_cost, "pid": product_id})
            return True
        except Exception as e:
            print(f"Error adding inventory log: {e}")
            return False

    def get_inventory_logs(self):
        try:
            return self._fetch_dicts("SELECT * FROM inventory_logs ORDER BY id DESC")
        except Exception as e:
            print(f"Error fetching inventory logs: {e}")
            return []

    def update_inventory_log(self, log_id, item_name, purchase_qty, purchase_cost, supplier,
                             remark, operator_name='管理員'):
        try:
            self._execute("""
                UPDATE inventory_logs
                SET item_name = :item_name, purchase_qty = :purchase_qty, purchase_cost = :purchase_cost,
                    supplier = :supplier, remark = :remark, operator_name = :operator_name
                WHERE id = :id
            """, {
                "item_name": item_name, "purchase_qty": purchase_qty,
                "purchase_cost": purchase_cost, "supplier": supplier,
                "remark": remark, "operator_name": operator_name, "id": log_id,
            })
            return True
        except Exception as e:
            print(f"Error updating inventory log {log_id}: {e}")
            return False

    def delete_inventory_log(self, log_id):
        try:
            self._execute("DELETE FROM inventory_logs WHERE id = :id", {"id": int(log_id)})
            return True
        except Exception as e:
            print(f"Error deleting inventory log {log_id}: {e}")
            return False

    # ---------- 耗材進貨 ----------

    def add_material_purchase(self, material_name, purchase_cost, purchase_qty, supplier='', remark='',
                              operator_name='管理員', purchase_date=None, total_capacity=''):
        try:
            now_str = purchase_date or self._get_taiwan_now_str()
            operator_name = operator_name or '管理員'
            total_capacity = total_capacity or ''
            self._execute("""
                INSERT INTO material_purchases (material_name, total_capacity, purchase_cost, purchase_qty,
                                                supplier, purchase_date, remark, operator_name)
                VALUES (:material_name, :total_capacity, :purchase_cost, :purchase_qty,
                        :supplier, :purchase_date, :remark, :operator_name)
            """, {
                "material_name": material_name, "total_capacity": total_capacity,
                "purchase_cost": purchase_cost, "purchase_qty": purchase_qty,
                "supplier": supplier, "purchase_date": now_str,
                "remark": remark, "operator_name": operator_name,
            })
            return True
        except Exception as e:
            print(f"Error adding material purchase: {e}")
            return False

    def get_material_purchases(self):
        try:
            return self._fetch_dicts("SELECT * FROM material_purchases ORDER BY id DESC")
        except Exception as e:
            print(f"Error fetching material purchases: {e}")
            return []

    def get_unique_material_names(self):
        try:
            rows = self._fetch_dicts("""
                SELECT DISTINCT material_name FROM material_purchases
                WHERE material_name IS NOT NULL AND material_name != ''
                ORDER BY material_name ASC
            """)
            return [r['material_name'] for r in rows]
        except Exception as e:
            print(f"Error fetching unique material names: {e}")
            return []

    def get_unique_material_suppliers(self):
        try:
            rows = self._fetch_dicts("""
                SELECT DISTINCT supplier FROM material_purchases
                WHERE supplier IS NOT NULL AND supplier != ''
                ORDER BY supplier ASC
            """)
            return [r['supplier'] for r in rows]
        except Exception as e:
            print(f"Error fetching unique material suppliers: {e}")
            return []

    def get_material_unit_costs(self):
        """各耗材的加權平均單位成本 = Σ進貨總成本 ÷ Σ容量（只計可解析且容量 > 0 的批次）。"""
        try:
            rows = self._fetch_dicts("""
                SELECT material_name, purchase_cost, total_capacity
                FROM material_purchases
                ORDER BY material_name ASC, purchase_date ASC
            """)
            agg = {}
            for r in rows:
                name = (r.get('material_name') or '').strip()
                if not name:
                    continue
                cap = self._parse_capacity_number(r.get('total_capacity'))
                if cap is None or cap <= 0:
                    continue
                d = agg.setdefault(name, {"cost": 0.0, "cap": 0.0})
                d["cost"] += float(r.get('purchase_cost') or 0)
                d["cap"] += cap
            result = {}
            for name, d in agg.items():
                if d["cap"] > 0:
                    result[name] = round(d["cost"] / d["cap"], 4)
            return result
        except Exception as e:
            print(f"Error computing material unit costs: {e}")
            return {}

    def update_material_purchase(self, log_id, material_name, purchase_cost, purchase_qty, supplier='',
                                 remark='', operator_name='管理員', purchase_date=None, total_capacity=''):
        try:
            now_str = purchase_date or self._get_taiwan_now_str()
            total_capacity = total_capacity or ''
            self._execute("""
                UPDATE material_purchases
                SET material_name = :material_name, total_capacity = :total_capacity,
                    purchase_cost = :purchase_cost, purchase_qty = :purchase_qty,
                    supplier = :supplier, remark = :remark, operator_name = :operator_name,
                    purchase_date = :purchase_date
                WHERE id = :id
            """, {
                "material_name": material_name, "total_capacity": total_capacity,
                "purchase_cost": purchase_cost, "purchase_qty": purchase_qty,
                "supplier": supplier, "remark": remark, "operator_name": operator_name,
                "purchase_date": now_str, "id": int(log_id),
            })
            return True
        except Exception as e:
            print(f"Error updating material purchase {log_id}: {e}")
            return False

    def delete_material_purchase(self, log_id):
        try:
            self._execute("DELETE FROM material_purchases WHERE id = :id", {"id": int(log_id)})
            return True
        except Exception as e:
            print(f"Error deleting material purchase {log_id}: {e}")
            return False

    # ---------- 訂單 ----------

    def get_all_orders(self):
        try:
            return self._fetch_dicts("SELECT * FROM orders ORDER BY id DESC")
        except Exception as e:
            print(f"Error fetching orders: {e}")
            return []

    def update_order_status_and_profit(self, order_id, status='SHIPPED', other_cost=0,
                                       shipping_cost=60, net_profit=0):
        """更新訂單狀態並實際寫入運費/其他成本/淨利潤"""
        try:
            self._execute("""
                UPDATE orders
                SET status = :status, other_cost = :other_cost,
                    shipping_cost = :shipping_cost, net_profit = :net_profit
                WHERE id = :id
            """, {
                "status": status, "other_cost": other_cost,
                "shipping_cost": shipping_cost, "net_profit": net_profit,
                "id": str(order_id),
            })
            return True
        except Exception as e:
            print(f"Error updating order {order_id}: {e}")
            return False

    def save_order(self, order_id, user_id, user_name, user_line_id, items, total_amount):
        try:
            now_str = self._get_taiwan_now_str()
            items_json = json.dumps(items, ensure_ascii=False)
            self._execute("""
                INSERT INTO orders (id, user_id, user_name, user_line_id, items_json, total_amount,
                                    status, created_at)
                VALUES (:id, :user_id, :user_name, :user_line_id, :items_json, :total_amount, 'PENDING', :created_at)
            """, {
                "id": order_id, "user_id": user_id, "user_name": user_name,
                "user_line_id": user_line_id, "items_json": items_json,
                "total_amount": total_amount, "created_at": now_str,
            })
            return True
        except Exception as e:
            print(f"Error saving order: {e}")
            return False

    def save_order_with_stock(self, order_id, user_id, user_name, user_line_id, items, total_amount):
        """原子下單：同一交易內鎖定商品列、檢查庫存並寫入 sales_logs 扣減庫存。

        items: [{id, name, price, qty, variant_name}]
        庫存不足時拋出 StockError（交易自動 rollback）。
        """
        try:
            now_str = self._get_taiwan_now_str()
            items_json = json.dumps(items, ensure_ascii=False)
            with self.engine.begin() as conn:
                pids = list({str(it['id']) for it in items})
                prod_rows = conn.execute(
                    text("SELECT id, name FROM products WHERE id = ANY(:pids) FOR UPDATE"),
                    {"pids": pids},
                ).fetchall()
                prod_map = {dict(r._mapping)['id']: dict(r._mapping)['name'] for r in prod_rows}
                missing = [pid for pid in pids if pid not in prod_map]
                if missing:
                    raise StockError("商品不存在或已下架，請重新整理頁面")

                conn.execute(text("""
                    INSERT INTO orders (id, user_id, user_name, user_line_id, items_json, total_amount,
                                        status, created_at)
                    VALUES (:id, :user_id, :user_name, :user_line_id, :items_json, :total_amount, 'PENDING', :created_at)
                """), {
                    "id": order_id, "user_id": user_id, "user_name": user_name,
                    "user_line_id": user_line_id, "items_json": items_json,
                    "total_amount": total_amount, "created_at": now_str,
                })

                for it in items:
                    pid = str(it['id'])
                    pname = prod_map[pid]
                    variant = (it.get('variant_name') or '').strip()
                    item_key = variant or '-'
                    qty = int(it.get('qty') or 0)

                    purchased = conn.execute(text("""
                        SELECT COALESCE(SUM(purchase_qty), 0) FROM inventory_logs
                        WHERE (product_id IS NOT NULL AND product_id = :pid)
                           OR (product_name IS NOT NULL AND product_name = :pname)
                    """), {"pid": pid, "pname": pname}).scalar() or 0
                    sold = conn.execute(text("""
                        SELECT COALESCE(SUM(qty), 0) FROM sales_logs
                        WHERE (product_id IS NOT NULL AND product_id = :pid)
                           OR (product_name IS NOT NULL AND product_name = :pname)
                    """), {"pid": pid, "pname": pname}).scalar() or 0
                    available = int(purchased) - int(sold)

                    if variant:
                        purch_item = conn.execute(text("""
                            SELECT COALESCE(SUM(purchase_qty), 0) FROM inventory_logs
                            WHERE ((product_id IS NOT NULL AND product_id = :pid)
                                OR (product_name IS NOT NULL AND product_name = :pname))
                              AND (item_name = :item OR item_name = '-' OR item_name = '-- 全品項預設/主商品 --')
                        """), {"pid": pid, "pname": pname, "item": variant}).scalar() or 0
                        sold_item = conn.execute(text("""
                            SELECT COALESCE(SUM(qty), 0) FROM sales_logs
                            WHERE ((product_id IS NOT NULL AND product_id = :pid)
                                OR (product_name IS NOT NULL AND product_name = :pname))
                              AND (item_name = :item OR item_name = '-' OR item_name = '-- 全品項預設/主商品 --')
                        """), {"pid": pid, "pname": pname, "item": variant}).scalar() or 0
                        available = min(available, int(purch_item) - int(sold_item))

                    if qty > available:
                        raise StockError(
                            f"商品「{it.get('name') or pname}」庫存不足（剩餘 {max(available, 0)} 件）"
                        )

                    conn.execute(text("""
                        INSERT INTO sales_logs (order_id, product_id, product_name, item_name, qty, created_at)
                        VALUES (:order_id, :product_id, :product_name, :item_name, :qty, :created_at)
                    """), {
                        "order_id": order_id, "product_id": pid, "product_name": pname,
                        "item_name": item_key, "qty": qty, "created_at": now_str,
                    })
            return True
        except StockError:
            raise
        except Exception as e:
            print(f"Error saving order with stock: {e}")
            return False

    def cancel_order(self, order_id):
        """取消訂單：狀態改 CANCELLED，並刪除 sales_logs 釋放庫存。"""
        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    text("SELECT status FROM orders WHERE id = :id FOR UPDATE"),
                    {"id": str(order_id)},
                ).first()
                if not row:
                    return False, "訂單不存在"
                if row["status"] in ("SHIPPED", "COMPLETED", "CANCELLED"):
                    return False, "已寄送或已取消的訂單無法取消"
                conn.execute(text("DELETE FROM sales_logs WHERE order_id = :id"), {"id": str(order_id)})
                conn.execute(text("UPDATE orders SET status = 'CANCELLED' WHERE id = :id"), {"id": str(order_id)})
            return True, "訂單已取消，庫存已釋放"
        except Exception as e:
            print(f"Error cancelling order {order_id}: {e}")
            return False, "取消訂單失敗"

    def save_order_settlement(self, order_id, products, order_totals):
        """寄送結算：寫入逐商品明細（order_settlements）與耗材消耗（order_materials），並更新訂單狀態。

        products: [{product_id, item_name, sales_amount, material_cost, other_cost, shipping_cost,
                    net_profit, designer_user_id, packager_user_id, designer_ratio, packager_ratio,
                    platform_ratio, designer_amount, packager_amount, platform_amount,
                    materials: [{material_name, capacity_used, unit_cost, cost}]}]
        """
        try:
            now_str = self._get_taiwan_now_str()
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE orders SET status = 'SHIPPED', other_cost = :oc, shipping_cost = :sc,
                        net_profit = :np, shipped_at = :shipped_at
                    WHERE id = :id
                """), {
                    "oc": order_totals.get("other_cost", 0),
                    "sc": order_totals.get("shipping_cost", 0),
                    "np": order_totals.get("net_profit", 0),
                    "shipped_at": now_str,
                    "id": str(order_id),
                })

                for p in products:
                    conn.execute(text("""
                        INSERT INTO order_settlements (order_id, product_id, item_name, sales_amount,
                            material_cost, other_cost, shipping_cost, net_profit,
                            designer_user_id, packager_user_id,
                            designer_ratio, packager_ratio, platform_ratio,
                            designer_amount, packager_amount, platform_amount, settled_at)
                        VALUES (:order_id, :product_id, :item_name, :sales_amount,
                            :material_cost, :other_cost, :shipping_cost, :net_profit,
                            :designer_user_id, :packager_user_id,
                            :designer_ratio, :packager_ratio, :platform_ratio,
                            :designer_amount, :packager_amount, :platform_amount, :settled_at)
                    """), {
                        "order_id": str(order_id),
                        "product_id": p.get("product_id"),
                        "item_name": p.get("item_name") or '-',
                        "sales_amount": p.get("sales_amount", 0),
                        "material_cost": p.get("material_cost", 0),
                        "other_cost": p.get("other_cost", 0),
                        "shipping_cost": p.get("shipping_cost", 0),
                        "net_profit": p.get("net_profit", 0),
                        "designer_user_id": p.get("designer_user_id") or None,
                        "packager_user_id": p.get("packager_user_id") or None,
                        "designer_ratio": p.get("designer_ratio", 20),
                        "packager_ratio": p.get("packager_ratio", 60),
                        "platform_ratio": p.get("platform_ratio", 20),
                        "designer_amount": p.get("designer_amount", 0),
                        "packager_amount": p.get("packager_amount", 0),
                        "platform_amount": p.get("platform_amount", 0),
                        "settled_at": now_str,
                    })

                    for m in p.get("materials", []):
                        conn.execute(text("""
                            INSERT INTO order_materials (order_id, product_id, item_name, material_name,
                                capacity_used, unit_cost, cost)
                            VALUES (:order_id, :product_id, :item_name, :material_name,
                                :capacity_used, :unit_cost, :cost)
                        """), {
                            "order_id": str(order_id),
                            "product_id": p.get("product_id"),
                            "item_name": p.get("item_name") or '-',
                            "material_name": m.get("material_name"),
                            "capacity_used": m.get("capacity_used", 0),
                            "unit_cost": m.get("unit_cost", 0),
                            "cost": m.get("cost", 0),
                        })
            return True
        except Exception as e:
            print(f"Error saving order settlement: {e}")
            return False

    def get_bonus_summary(self, date_from, date_to):
        """依結算時間區間回傳獎金統計：每人設計/包裝金額、每筆明細、平台收益總計。"""
        try:
            rows = self._fetch_dicts("""
                SELECT s.*, o.user_name AS order_user_name
                FROM order_settlements s
                JOIN orders o ON o.id = s.order_id
                WHERE s.settled_at >= :date_from AND s.settled_at <= :date_to
                ORDER BY s.settled_at ASC
            """, {"date_from": date_from, "date_to": date_to})

            users = {u['id']: u['name'] for u in self.get_all_users()}
            members = {}
            entries = []
            platform_total = 0.0

            for r in rows:
                platform_total += float(r.get('platform_amount') or 0)
                for role, uid_key, amt_key, ratio_key in (
                    ("designer", "designer_user_id", "designer_amount", "designer_ratio"),
                    ("packager", "packager_user_id", "packager_amount", "packager_ratio"),
                ):
                    uid = r.get(uid_key)
                    amount = float(r.get(amt_key) or 0)
                    if not uid or amount <= 0:
                        continue
                    member = members.setdefault(uid, {
                        "user_id": uid,
                        "name": users.get(uid, uid),
                        "designer_amount": 0.0,
                        "packager_amount": 0.0,
                        "total": 0.0,
                    })
                    member[f"{role}_amount"] += amount
                    member["total"] += amount
                    entries.append({
                        "user_id": uid,
                        "user_name": users.get(uid, uid),
                        "role": role,
                        "amount": round(amount, 2),
                        "ratio": float(r.get(ratio_key) or 0),
                        "order_id": r.get("order_id"),
                        "product_id": r.get("product_id"),
                        "item_name": r.get("item_name"),
                        "settled_at": r.get("settled_at"),
                        "net_profit": float(r.get("net_profit") or 0),
                    })

            members_list = sorted(members.values(), key=lambda x: -x["total"])
            for m in members_list:
                m["designer_amount"] = round(m["designer_amount"], 2)
                m["packager_amount"] = round(m["packager_amount"], 2)
                m["total"] = round(m["total"], 2)

            return {
                "platform_total": round(platform_total, 2),
                "members": members_list,
                "entries": entries,
            }
        except Exception as e:
            print(f"Error fetching bonus summary: {e}")
            return {"platform_total": 0, "members": [], "entries": []}

    # ---------- LINE 群組與公告 ----------

    def get_line_groups(self):
        try:
            return self._fetch_dicts("SELECT * FROM line_groups ORDER BY created_at DESC")
        except Exception as e:
            print(f"Error fetching line groups: {e}")
            return []

    def save_line_group(self, group_id, name, description):
        try:
            now_str = self._get_taiwan_now_str()
            self._execute("""
                INSERT INTO line_groups (id, name, description, created_at)
                VALUES (:id, :name, :description, :created_at)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description
            """, {"id": group_id, "name": name, "description": description, "created_at": now_str})
            return True
        except Exception as e:
            print(f"Error saving line group: {e}")
            return False

    def delete_line_group(self, group_id):
        try:
            self._execute("DELETE FROM line_groups WHERE id = :id", {"id": group_id})
            return True
        except Exception as e:
            print(f"Error deleting line group {group_id}: {e}")
            return False

    def get_bulletins(self):
        try:
            return self._fetch_dicts("SELECT * FROM bulletins ORDER BY is_pinned DESC, date_str DESC")
        except Exception as e:
            print(f"Error fetching bulletins: {e}")
            return []

    def save_bulletin(self, b_id, title, date_str, tag, is_pinned, summary, content, line_broadcasted):
        try:
            self._execute("""
                INSERT INTO bulletins (id, title, date_str, tag, is_pinned, summary, content, line_broadcasted)
                VALUES (:id, :title, :date_str, :tag, :is_pinned, :summary, :content, :line_broadcasted)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title, date_str = EXCLUDED.date_str, tag = EXCLUDED.tag,
                    is_pinned = EXCLUDED.is_pinned, summary = EXCLUDED.summary,
                    content = EXCLUDED.content, line_broadcasted = EXCLUDED.line_broadcasted
            """, {
                "id": b_id, "title": title, "date_str": date_str, "tag": tag,
                "is_pinned": is_pinned, "summary": summary,
                "content": content, "line_broadcasted": line_broadcasted,
            })
            return True
        except Exception as e:
            print(f"Error saving bulletin: {e}")
            return False

    def delete_bulletin(self, b_id):
        try:
            self._execute("DELETE FROM bulletins WHERE id = :id", {"id": b_id})
            return True
        except Exception as e:
            print(f"Error deleting bulletin {b_id}: {e}")
            return False
