"""線上結帳頁、訂單查詢與匯款回報（顧客端）。"""
import json
import re
import uuid
from decimal import Decimal

from flask import Blueprint, jsonify, redirect, render_template, request, session

from extensions import db_service, line_service, _run_in_background
import shop_service

shop_bp = Blueprint('shop', __name__)


def _current():
    user = session.get('user') or {}
    return user if user.get('id') else None


def _require_page(next_path):
    if not _current():
        return redirect('/login/line?next=' + next_path)
    return None


def _order_status_text(order):
    status = order.get('status')
    pay = order.get('payment_status') or 'UNPAID'
    if not order.get('shipping_method'):
        return '舊版訂單'
    if status == 'CANCELLED':
        return '已取消'
    if status == 'SHIPPED':
        return '已出貨'
    if status == 'COMPLETED':
        return '已完成'
    if pay == 'CONFIRMED':
        return '已確認收款，待出貨'
    if pay == 'NOT_RECEIVED':
        return '尚未收到款項'
    if pay == 'AMOUNT_MISMATCH':
        return '金額待確認'
    if pay == 'REPORTED':
        return '已回報匯款，待確認'
    return '待匯款'


def order_json(order):
    try:
        items = json.loads(order.get('items_json') or '[]')
    except (ValueError, TypeError):
        items = []
    if not isinstance(items, list):
        items = []
    fee = Decimal(str(order.get('shipping_fee') or 0))
    subtotal = Decimal(str(order.get('total_amount') or 0))
    method = order.get('shipping_method')
    pay = order.get('payment_status') or 'UNPAID'
    legacy = not method
    return {
        'id': order.get('id'),
        'created_at': order.get('created_at') or '',
        'status': order.get('status'),
        'payment_status': pay,
        'status_text': _order_status_text(order),
        'items': items,
        'subtotal': str(subtotal),
        'shipping_fee': str(fee),
        'amount_due': str(subtotal + fee),
        'shipping': {
            'method': method or '',
            'label': shop_service.METHOD_LABEL.get(method or '', '—'),
            'recipient': order.get('shipping_recipient') or '',
            'phone': order.get('shipping_phone') or '',
            'address': order.get('shipping_address') or '',
            'store': order.get('shipping_store') or '',
        },
        'remit_last5': order.get('remit_last5') or '',
        'remit_reported_at': str(order.get('remit_reported_at') or '')[:16],
        'legacy': legacy,
        'can_report': (not legacy) and order.get('status') == 'PENDING' and pay != 'CONFIRMED',
        'can_cancel': (not legacy) and order.get('status') == 'PENDING' and pay == 'UNPAID',
    }


def _group_id():
    try:
        groups = db_service.get_line_groups() or []
    except Exception:
        groups = []
    for g in groups:
        if g.get('id'):
            return g['id']
    return None


@shop_bp.get('/checkout')
def checkout_page():
    guard = _require_page('/checkout')
    if guard:
        return guard
    user = _current()
    member = db_service.get_user_by_id(user['id']) or {}
    return render_template(
        'checkout.html',
        member={'name': member.get('name') or user.get('name') or '',
                'phone': member.get('phone') or '',
                'address': member.get('address') or ''},
    )


@shop_bp.get('/orders')
def orders_page():
    guard = _require_page('/orders')
    if guard:
        return guard
    user = _current()
    return render_template('orders.html', member={'name': user.get('name') or ''})


@shop_bp.get('/api/orders/mine')
def my_orders():
    user = _current()
    if not user:
        return jsonify(status='error', code='login_required', message='請先登入'), 401
    try:
        page = int(request.args.get('page') or 1)
    except ValueError:
        page = 1
    data = db_service.get_user_orders(user['id'], user.get('line_id'), page)
    return jsonify(status='success', page=data['page'], pages=data['pages'],
                   total=data['total'], data=[order_json(o) for o in data['rows']])


@shop_bp.post('/api/orders/<order_id>/remit')
def report_remit(order_id):
    user = _current()
    if not user:
        return jsonify(status='error', code='login_required', message='請先登入'), 401
    data = request.get_json(silent=True) or {}
    last5 = str(data.get('last5') or '').strip()
    if not re.fullmatch(r'\d{5}', last5):
        return jsonify(status='error', message='請輸入匯款帳號後 5 碼（5 位數字）'), 400
    try:
        order = db_service.report_remittance(order_id, user['id'], user.get('line_id'), last5)
    except ValueError as exc:
        return jsonify(status='error', message=str(exc)), 400

    group = _group_id()
    if group:
        _run_in_background(line_service.push_flex, group,
                           f'匯款回報 {order_id}', shop_service.remit_flex(order))
    text = (f'已收到您的匯款回報（訂單 {order_id}，末五碼 {last5}）。'
            f'我們核對後會盡快通知您，謝謝！')
    _run_in_background(line_service.push_user_text, order.get('user_line_id') or '',
                       text, str(uuid.uuid4()))
    return jsonify(status='success', order=order_json(order))


@shop_bp.post('/api/orders/<order_id>/cancel')
def cancel_my_order(order_id):
    user = _current()
    if not user:
        return jsonify(status='error', code='login_required', message='請先登入'), 401
    ok, message = db_service.cancel_order_customer(order_id, user['id'], user.get('line_id'))
    if not ok:
        return jsonify(status='error', message=message), 400
    return jsonify(status='success', message=message)
