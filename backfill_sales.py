"""一次性回補：把既有未取消訂單寫入 sales_logs（庫存扣減）。

用法（在 Railway 或本機有 DATABASE_URL 的環境執行）：
    python backfill_sales.py

重複執行安全：已有銷售紀錄的訂單會自動跳過；已取消訂單不處理。
回補後庫存會一次下降（等於把舊訂單已售數量扣掉），屬預期行為。
"""
import json

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv(override=False)

from db_service import DBService


def _resolve_variant_name(prod_map, pid, cart_key, item_name):
    """從商品規格資料推斷訂單項目的款式名稱；找不到回傳空字串。

    依序嘗試：
    1. cart_key 內含的規格編號（例如 p_xxx_v_123 → v_123）
    2. 商品名稱「商品 - 規格」的後綴（例如 紀念幣 - 單面印刷 → 單面印刷）
    """
    prod = prod_map.get(pid) if pid else None
    variants = []
    if prod:
        try:
            raw = prod.get('items_json') or '[]'
            arr = json.loads(raw) if isinstance(raw, str) else (raw or [])
            variants = arr if isinstance(arr, list) else []
        except (ValueError, TypeError):
            variants = []

    # 1) cart_key 內含規格編號
    if cart_key and pid and cart_key.startswith(pid + '_'):
        vkey = cart_key[len(pid) + 1:]
        if vkey:
            for v in variants:
                if str(v.get('id') or '') == vkey or (v.get('name') or '') == vkey:
                    return (v.get('name') or '').strip()

    # 2) 商品名稱「商品 - 規格」的後綴
    if item_name and prod:
        prefix = (prod.get('name') or '').strip() + ' - '
        if item_name.startswith(prefix):
            suffix = item_name[len(prefix):].strip()
            for v in variants:
                if (v.get('name') or '').strip() == suffix:
                    return suffix
    return ''


def main():
    db = DBService()
    orders = db.get_all_orders()
    prod_map = {p['id']: p for p in db.get_products()}
    inserted = 0
    skipped = 0

    for o in orders:
        if o.get('status') == 'CANCELLED':
            skipped += 1
            continue

        existing = db._fetch_one(
            "SELECT COUNT(*) AS c FROM sales_logs WHERE order_id = :order_id",
            {"order_id": o['id']},
        )
        if existing and existing.get('c'):
            skipped += 1
            continue

        try:
            raw = o.get('items_json') or '[]'
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (ValueError, TypeError):
            items = []

        if not isinstance(items, list) or not items:
            skipped += 1
            continue

        with db.engine.begin() as conn:
            for it in items:
                pid = str(it.get('id') or '').strip()
                item_name = (
                    it.get('variant_name')
                    or it.get('item_name')
                    or it.get('itemName')
                )
                item_name = (item_name or '').strip()
                if not item_name:
                    item_name = _resolve_variant_name(
                        prod_map,
                        pid,
                        str(it.get('cart_key') or ''),
                        str(it.get('name') or it.get('product_name') or ''),
                    )
                item_name = item_name or '-'
                conn.execute(text("""
                    INSERT INTO sales_logs (order_id, product_id, product_name, item_name, qty, created_at)
                    VALUES (:order_id, :product_id, :product_name, :item_name, :qty, :created_at)
                """), {
                    "order_id": o['id'],
                    "product_id": it.get('id'),
                    "product_name": it.get('name') or it.get('product_name'),
                    "item_name": item_name,
                    "qty": int(it.get('qty') or 1),
                    "created_at": o.get('created_at'),
                })
        inserted += 1

    print(f"回補完成：{inserted} 筆訂單已寫入銷售紀錄，{skipped} 筆跳過（已取消 / 已有紀錄 / 無商品明細）。")


if __name__ == '__main__':
    main()
