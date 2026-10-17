"""線上結帳的共用規則與 LINE 訊息內容（不依賴 Flask）。"""
import json
import os
import re
from decimal import Decimal
from urllib.parse import urlsplit

FREE_SHIPPING_THRESHOLD = Decimal('500')
SHIPPING_FEE = Decimal('50')

METHOD_LABEL = {'HOME': '郵寄到家', 'SEVEN': '7-11 收件'}
PAYMENT_TEXT = {
    'CONFIRMED': '您好，已確認收到您的匯款（訂單 {oid}，金額 NT$ {amount}）。我們將立即安排製作與出貨，寄出後會再通知您，謝謝！',
    'NOT_RECEIVED': '您好，目前尚未查到訂單 {oid} 的匯款紀錄。請您再次確認轉帳是否成功，或回覆匯款時間，我們會再幫您核對，謝謝！',
    'AMOUNT_MISMATCH': '您好，我們已收到訂單 {oid} 的匯款，但金額與應付的 NT$ {amount} 似乎不一致。將有專人與您聯繫確認，請稍候，謝謝！',
}


def money(value):
    try:
        d = Decimal(str(value or 0))
    except Exception:
        d = Decimal('0')
    if d == d.to_integral_value():
        return f'{d:,.0f}'
    return f'{d:,.2f}'


def amount_due(order):
    return Decimal(str(order.get('total_amount') or 0)) + Decimal(str(order.get('shipping_fee') or 0))


def public_base(request_root=''):
    """對外網址：優先用環境變數，其次從 LINE 回呼網址推斷，最後才用請求來源。"""
    env = (os.getenv('SHOP_PUBLIC_BASE_URL') or os.getenv('RESERVATION_PUBLIC_BASE_URL') or '').strip()
    if env:
        return env.rstrip('/')
    login = (os.getenv('LINE_LOGIN_REDIRECT_URI') or '').strip()
    if login.startswith('https://'):
        parts = urlsplit(login)
        return f'{parts.scheme}://{parts.netloc}'
    return (request_root or '').rstrip('/')


def shipping_fee_for(subtotal):
    return Decimal('0') if Decimal(str(subtotal)) >= FREE_SHIPPING_THRESHOLD else SHIPPING_FEE


def validate_shipping(data):
    if not isinstance(data, dict):
        return False, '請填寫收件資訊', None
    method = str(data.get('method') or '').strip().upper()
    recipient = str(data.get('recipient') or '').strip()
    phone = str(data.get('phone') or '').strip()
    address = str(data.get('address') or '').strip()
    store = str(data.get('store') or '').strip()
    if method not in METHOD_LABEL:
        return False, '請選擇寄送方式', None
    if not recipient or len(recipient) > 100:
        return False, '請填寫收件者姓名（1～100 字）', None
    if not re.fullmatch(r'[0-9+\-\s()]{6,30}', phone):
        return False, '請填寫有效的手機或電話', None
    if not address or len(address) > 200:
        return False, ('請填寫收件地址' if method == 'HOME' else '請填寫 7-11 門市地址'), None
    if method == 'SEVEN' and (not store or len(store) > 100):
        return False, '請填寫 7-11 門市名稱', None
    return True, '', {
        'method': method, 'recipient': recipient, 'phone': phone,
        'address': address, 'store': store if method == 'SEVEN' else '',
    }


def _items(order):
    try:
        items = json.loads(order.get('items_json') or '[]')
        return items if isinstance(items, list) else []
    except (ValueError, TypeError):
        return []


def _item_line(item):
    name = item.get('name') or '商品'
    variant = ' '.join(x for x in (item.get('variant_name'), item.get('variant_color')) if x)
    label = f'{name}（{variant}）' if variant else name
    qty = int(item.get('qty') or 1)
    price = Decimal(str(item.get('price') or 0)) * qty
    return f'• {label} ×{qty}　NT$ {money(price)}'


def _shipping_lines(order):
    method = order.get('shipping_method') or 'HOME'
    label = METHOD_LABEL.get(method, '郵寄到家')
    lines = [f'寄送方式：{label}',
             f'收件人：{order.get("shipping_recipient") or order.get("user_name") or "-"}／{order.get("shipping_phone") or "-"}']
    if method == 'SEVEN' and order.get('shipping_store'):
        lines.append(f'門市：{order["shipping_store"]}')
    lines.append(f'地址：{order.get("shipping_address") or "-"}')
    return lines


def customer_order_message(order, base_url=''):
    items = _items(order)
    subtotal = Decimal(str(order.get('total_amount') or 0))
    fee = Decimal(str(order.get('shipping_fee') or 0))
    lines = ['【展夢.飛翔 訂單成立】',
             f'訂單編號：{order.get("id")}',
             f'訂購人：{order.get("user_name") or "-"}',
             '',
             '商品明細：']
    lines += [_item_line(it) for it in items]
    lines += [f'商品小計：NT$ {money(subtotal)}',
              f'運費：{"免運" if fee == 0 else "NT$ " + money(fee) + "（未滿 500 元）"}',
              f'應付金額：NT$ {money(subtotal + fee)}',
              ''] + _shipping_lines(order) + [
              '',
              '付款方式：匯款',
              '第一銀行（007）帳號 16168171704',
              '匯款完成後，請至訂單查詢填寫匯款帳號後 5 碼：',
              f'{base_url.rstrip("/")}/orders' if base_url else '/orders']
    return '\n'.join(lines)


def group_order_message(order):
    items = _items(order)
    summary = '、'.join(
        f'{(it.get("name") or "商品")}'
        f'{"（" + " ".join(x for x in (it.get("variant_name"), it.get("variant_color")) if x) + "）" if (it.get("variant_name") or it.get("variant_color")) else ""}'
        f'×{int(it.get("qty") or 1)}'
        for it in items
    )
    fee = Decimal(str(order.get('shipping_fee') or 0))
    method = METHOD_LABEL.get(order.get('shipping_method') or 'HOME', '郵寄到家')
    place = order.get('shipping_store') or order.get('shipping_address') or '-'
    return '\n'.join([
        '【新訂單】',
        f'訂單：{order.get("id")}',
        f'訂購人：{order.get("user_name") or "-"}',
        f'商品：{summary or "-"}',
        f'應付：NT$ {money(amount_due(order))}（{"免運" if fee == 0 else "含運 " + money(fee)}）',
        f'寄送：{method}｜{place}',
        f'收件人：{order.get("shipping_recipient") or "-"}／{order.get("shipping_phone") or "-"}',
    ])


def remit_group_text(order):
    return '\n'.join([
        '【匯款回報】',
        f'訂單：{order.get("id")}',
        f'客人：{order.get("user_name") or "-"}',
        f'應付：NT$ {money(amount_due(order))}',
        f'回報末五碼：{order.get("remit_last5") or "-"}',
    ] + _shipping_lines(order))


def remit_flex(order):
    """群組匯款通知 + 三個 postback 按鈕。"""
    oid = order.get('id')
    body = {
        'type': 'box', 'layout': 'vertical', 'spacing': 'sm', 'contents': [
            {'type': 'text', 'text': '【匯款回報】', 'weight': 'bold', 'size': 'md'},
            {'type': 'text', 'text': f'訂單：{oid}', 'size': 'sm', 'wrap': True},
            {'type': 'text', 'text': f'客人：{order.get("user_name") or "-"}', 'size': 'sm'},
            {'type': 'text', 'text': f'應付：NT$ {money(amount_due(order))}', 'size': 'sm'},
            {'type': 'text', 'text': f'回報末五碼：{order.get("remit_last5") or "-"}', 'size': 'sm', 'weight': 'bold'},
            {'type': 'text', 'text': f'寄送：{METHOD_LABEL.get(order.get("shipping_method") or "HOME", "郵寄到家")}',
             'size': 'xs', 'color': '#666666', 'wrap': True},
        ]
    }
    buttons = []
    for label, action_text, action in (
        ('確認收到', '確認收到', 'CONFIRMED'),
        ('尚未收到', '尚未收到', 'NOT_RECEIVED'),
        ('匯款金額有誤', '匯款金額有誤', 'AMOUNT_MISMATCH'),
    ):
        buttons.append({
            'type': 'button', 'style': 'primary' if action == 'CONFIRMED' else 'secondary',
            'height': 'sm', 'action': {
                'type': 'postback', 'label': label,
                'data': f'remit:{oid}:{action}', 'displayText': action_text,
            }
        })
    return {
        'type': 'bubble',
        'body': body,
        'footer': {'type': 'box', 'layout': 'vertical', 'spacing': 'sm', 'contents': buttons},
    }


def customer_payment_message(order, action):
    template = PAYMENT_TEXT.get(action)
    if not template:
        return ''
    return template.format(oid=order.get('id'), amount=money(amount_due(order)))
