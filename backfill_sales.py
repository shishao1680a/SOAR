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


def main():
    db = DBService()
    orders = db.get_all_orders()
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
                item_name = (
                    it.get('variant_name')
                    or it.get('item_name')
                    or it.get('itemName')
                    or '-'
                )
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
