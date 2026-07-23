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
        """自動建立所需的 PostgreSQL 資料表並匯入初始範例資料"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. users 表
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS users (
                            id VARCHAR(255) PRIMARY KEY,
                            name VARCHAR(255),
                            line_id VARCHAR(255),
                            avatar_url TEXT,
                            phone VARCHAR(255),
                            role VARCHAR(50) DEFAULT 'member',
                            register_date VARCHAR(100)
                        )
                    ''')

                    # 2. products 表
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS products (
                            id VARCHAR(100) PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            category VARCHAR(50) NOT NULL,
                            material VARCHAR(50) NOT NULL,
                            price NUMERIC(10, 2) NOT NULL,
                            badge VARCHAR(100),
                            image_url TEXT,
                            description TEXT,
                            is_uv BOOLEAN DEFAULT FALSE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')

                    # 3. bulletins 表 (公佈欄)
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

                    # 4. orders 表 (購物車訂單)
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
        """若商品與公告表為空，播種初始範例資料"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 檢查 products 表數量
                    cursor.execute("SELECT COUNT(*) FROM products")
                    if cursor.fetchone()[0] == 0:
                        initial_products = [
                            ("p1", "VORTEX H-BLOCK 避震套件", "3d-print", "TPU_95A", 45.00, "TPU HIGH-IMPACT", "https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=600&q=80", "Reinforced lattice structure for maximum sliding speed and impact absorption.", False),
                            ("p2", "GLITCH DECAL UV炫彩貼紙包", "uv-print", "UV_RESIN", 18.00, "UV REACTIVE", "https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=600&q=80", "Ultra-durable UV resin prints. Scuff-resistant and glow-active under city lights.", True),
                            ("p3", "PRO SPACER PA12 精密墊片", "3d-print", "NYLON_CF", 22.00, "NYLON-PA12", "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=600&q=80", "Precision spacers engineered for zero-wiggle performance and heat dissipation.", False),
                            ("p4", "TITAN SOUL PLATE 魂板底座", "3d-print", "PLA_PRO", 65.00, "PLA-PRO", "https://images.unsplash.com/photo-1508614589041-895b88991e3e?auto=format&fit=crop&w=600&q=80", "Custom-fit soul plates with reinforced mounting points and ultra-slick formula.", False),
                            ("p5", "NEON_HELMET UV戰術彩繪徽章", "uv-print", "UV_RESIN", 28.00, "UV TACTICAL", "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=600&q=80", "直噴 UV 立體多層印刷於安全帽與車身硬殼，立體紋理手感，耐刮擦且不退色。", True),
                            ("p6", "FLEX_STRAP R1 運動綁帶組", "custom", "TPU_95A", 15.00, "CLUB EXCLUSIVE", "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?auto=format&fit=crop&w=600&q=80", "社團限定版柔性 3D 列印固定扣帶，可客製印製個人選手號碼與社團 Logo。", False)
                        ]
                        cursor.executemany('''
                            INSERT INTO products (id, name, category, material, price, badge, image_url, description, is_uv)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''', initial_products)

                    # 檢查 bulletins 表數量
                    cursor.execute("SELECT COUNT(*) FROM bulletins")
                    if cursor.fetchone()[0] == 0:
                        initial_bulletins = [
                            ("b1", "🔥 【社團賽事】2026 夏季極限 3D/UV 作品改裝大賽開始報名！", "2026-07-20", "賽事公告", True, "本屆改裝大賽包含 3D 列印機構件設計組與 UV 炫彩彩繪組，獎品包含 Bambu 3D 列印機與客製列印資材！", "親愛的社友們：\n2026 夏季極限 3D/UV 作品改裝大賽即日起開放報名！\n\n【參賽組別】\n1. 3D 列印極限性能組：著重於機件避震、強度與輕量化。\n2. UV 炫彩美學組：著重於金屬、壓克力與安全帽等表面 UV 浮雕彩繪質感。\n\n【報名方式】\n點擊下方 LINE 服務按鈕即可直接以 LINE 帳號完成一鍵報名並領取參賽編號！", True),
                            ("b2", "📦 新進資材通知：Nylon-CF 碳纖維尼龍與亮面 UV 樹脂已上架", "2026-07-15", "資材更新", False, "全新批次高剛性碳纖維線材與日本進口 UV 抗黃化樹脂已抵達社團工坊，歡迎訂購套件。", "工坊目前已完成 Bambu X1C 8台機器聯網，提供更快速的 3D 打樣與 UV 少量多樣客製化印刷服務。", True),
                            ("b3", "🤖 LINE 官方 Bot 功能升級：支援訂單進度查詢與自動推播", "2026-07-10", "系統更新", False, "參考第一金人壽專案 LINE API 服務，現已支援一鍵 LINE 快速登入與群組動態廣播通知。", "社友登入 LINE 後即可在個人中心查看 3D 列印排單列印進度（切片中 / 列印中 / UV後處理 / 已出貨）。", True)
                        ]
                        cursor.executemany('''
                            INSERT INTO bulletins (id, title, date_str, tag, is_pinned, summary, content, line_broadcasted)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ''', initial_bulletins)
                conn.commit()
        except Exception as e:
            print(f"ERROR: Initial seed failed: {e}")

    def get_products(self):
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM products ORDER BY created_at ASC")
                    return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching products: {e}")
            return []

    def get_bulletins(self):
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM bulletins ORDER BY is_pinned DESC, date_str DESC")
                    return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching bulletins: {e}")
            return []

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
