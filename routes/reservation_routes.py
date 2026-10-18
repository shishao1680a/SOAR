"""Public queue, verified LINE guests and admin-only onsite operations."""
import hmac
import os
import secrets
import uuid
from functools import wraps
from io import BytesIO
from urllib.parse import urlsplit, urlencode
from flask import Blueprint, Response, jsonify, render_template, request, session, url_for
from sqlalchemy import text
from extensions import db_service, line_service, reservation_service as service
from reservation_service import ReservationError, decode_items
from db_service import StockError
from routes.product_routes import to_public_product

reservation_bp = Blueprint('reservation', __name__)


def csrf_token():
    if 'reservation_csrf' not in session:
        session['reservation_csrf'] = secrets.token_urlsafe(32)
    return session['reservation_csrf']


def reservation_url(sid):
    # HTTPS 代理後的 request.scheme 可能是 http；優先沿用設定好的正式入口。
    base = os.getenv('RESERVATION_PUBLIC_BASE_URL', '').rstrip('/')
    if not base:
        login_uri = urlsplit(os.getenv('LINE_LOGIN_REDIRECT_URI', ''))
        base = f'{login_uri.scheme}://{login_uri.netloc}' if login_uri.scheme and login_uri.netloc else request.host_url.rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
        raise ReservationError('預約入口網址設定錯誤，請洽管理者')
    return base + '/reservations?' + urlencode({'scene': sid})


def admin_user():
    user = session.get('user') or {}
    if not user.get('id'):
        return None
    row = db_service._fetch_one('SELECT id,role FROM users WHERE id=:id', {'id': user['id']})
    return row if row and row['role'] == 'admin' else None


def endpoint(admin=False, guest=False):
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            try:
                if admin and not admin_user():
                    return jsonify(status='error', message='此功能僅限管理員操作'), 403
                if guest and not (session.get('reservation_identity') or {}).get('line_id'):
                    return jsonify(status='error', message='請先使用 LINE 登入現場預約'), 401
                if request.method != 'GET':
                    expected = session.get('reservation_csrf', '')
                    supplied = request.headers.get('X-Reservation-CSRF', '')
                    if not expected or not hmac.compare_digest(expected, supplied):
                        return jsonify(status='error', message='頁面驗證逾時，請重新整理'), 403
                    if not request.is_json or not isinstance(request.get_json(silent=True), dict):
                        return jsonify(status='error', message='請提交有效的表單資料'), 400
                return fn(*args, **kwargs)
            except (ReservationError, StockError) as exc:
                return jsonify(status='error', message=str(exc)), 409
            except Exception:
                from flask import current_app
                current_app.logger.error('Reservation operation failed: %s %s', request.method, request.path)
                return jsonify(status='error', message='預約服務暫時無法使用，請稍後重試'), 503
        return run
    return decorate


def ticket_output(ticket):
    result = {k: ticket.get(k) for k in ('id', 'session_id', 'number', 'name', 'status', 'total_amount', 'order_id')}
    result['items'] = decode_items(ticket['items_json'])
    result['notifications'] = db_service._fetch_dicts('''SELECT id,kind,status,attempts,last_error
        FROM reservation_notifications WHERE reservation_id=:id ORDER BY created_at''', {'id': ticket['id']})
    return result


@reservation_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'same-origin'
    return response


@reservation_bp.get('/reservations')
def page():
    return render_template('reservations.html')


@reservation_bp.get('/api/reservations/state')
@endpoint()
def state():
    sid = request.args.get('scene') or None
    scene = service.public_scene(sid)
    identity = session.get('reservation_identity') or {}
    products = [to_public_product(p) for p in db_service.get_products() if p.get('onsite_enabled')]
    return jsonify(status='success', scene=scene, products=products, csrf=csrf_token(), is_admin=bool(admin_user()),
                   identity={'name': identity.get('name', ''), 'friend': identity.get('friend', False)} if identity else None)


@reservation_bp.get('/api/reservations/login')
@endpoint()
def login():
    scene = service.scene(request.args.get('scene'))
    if not scene or scene['status'] == 'ENDED':
        raise ReservationError('請選擇尚未結束的場次')
    state = uuid.uuid4().hex
    session['oauth_state'] = state
    session['reservation_oauth_scene'] = scene['id']
    redirect_uri = os.getenv('LINE_LOGIN_REDIRECT_URI', f"{request.host_url.rstrip('/')}/api/line/callback")
    url = line_service.get_login_url(state, redirect_uri=redirect_uri, add_friend=True)
    if not url:
        raise ReservationError('尚未設定 LINE Login，請洽管理者')
    return jsonify(status='success', url=url)


@reservation_bp.get('/api/reservations/mine')
@endpoint(guest=True)
def mine():
    scene = service.scene(request.args.get('scene'))
    rows = service.tickets(scene['id'], session['reservation_identity']['line_id']) if scene else []
    return jsonify(status='success', tickets=[ticket_output(t) for t in rows])


@reservation_bp.post('/api/reservations')
@endpoint(guest=True)
def reserve():
    identity = session['reservation_identity']
    if identity.get('friend') is not True:
        raise ReservationError('請先加入官方帳號並重新使用 LINE 登入確認')
    data = request.get_json()
    sid = data.get('session_id')
    query_url = reservation_url(sid)
    ticket = service.reserve(sid, identity, data.get('name'), data.get('items'), data.get('request_key'), query_url)
    service.dispatch_ticket(ticket['id'], line_service)
    return jsonify(status='success', ticket=ticket_output(ticket))


@reservation_bp.post('/api/reservations/<rid>/cancel')
@endpoint(guest=True)
def cancel(rid):
    ticket = service.ticket_action(request.get_json().get('session_id'), rid, 'cancel', session['reservation_identity']['line_id'])
    return jsonify(status='success', ticket=ticket_output(ticket))


@reservation_bp.get('/api/admin/reservations')
@endpoint(admin=True)
def admin_state():
    scenes = db_service._fetch_dicts('SELECT * FROM reservation_sessions ORDER BY created_at DESC')
    scene = service.scene(request.args.get('scene'))
    tickets = service.tickets(scene['id']) if scene else []
    out = []
    for t in tickets:
        item = ticket_output(t)
        item['line_id'] = t.get('line_id') or ''
        out.append(item)
    return jsonify(status='success', scenes=scenes, scene=scene, tickets=out)


@reservation_bp.post('/api/admin/reservations/sessions')
@endpoint(admin=True)
def create_scene():
    return jsonify(status='success', scene=service.create_scene(request.get_json().get('name')))


@reservation_bp.post('/api/admin/reservations/sessions/<sid>/<action>')
@endpoint(admin=True)
def scene_action(sid, action):
    data = request.get_json()
    if action == 'call-next':
        raise ReservationError('已改為逐號通知，請重新整理頁面後使用「通知到場」')
    return jsonify(status='success', scene=service.update_scene(sid, action, data.get('message'), data.get('confirmed') is True))


@reservation_bp.post('/api/admin/reservations/tickets/<rid>/<action>')
@endpoint(admin=True)
def ticket_action(rid, action):
    data = request.get_json()
    if action == 'notify':
        ticket, nid = service.notify(data.get('session_id'), rid, data.get('request_key'), data.get('message'))
        service.dispatch(nid, line_service)
    else:
        ticket = service.ticket_action(data.get('session_id'), rid, action)
    return jsonify(status='success', ticket=ticket_output(ticket))


@reservation_bp.post('/api/admin/reservations/notifications/<nid>/retry')
@endpoint(admin=True)
def retry_notification(nid):
    service.dispatch(nid, line_service)
    return jsonify(status='success')


@reservation_bp.post('/api/admin/reservations/products/<pid>')
@endpoint(admin=True)
def product_flag(pid):
    enabled = request.get_json().get('enabled')
    if not isinstance(enabled, bool):
        raise ReservationError('現場製作勾選格式錯誤')
    with db_service.engine.begin() as c:
        row = c.execute(text('UPDATE products SET onsite_enabled=:flag WHERE id=:id RETURNING id'), {'flag': enabled, 'id': pid}).first()
        if not row:
            raise ReservationError('商品不存在')
    return jsonify(status='success')


@reservation_bp.get('/api/admin/reservations/sessions/<sid>/qr.svg')
@endpoint(admin=True)
def qr(sid):
    import qrcode
    import qrcode.image.svg
    if not service.scene(sid):
        raise ReservationError('場次不存在')
    image = qrcode.make(reservation_url(sid), image_factory=qrcode.image.svg.SvgPathImage)
    out = BytesIO()
    image.save(out)
    return Response(out.getvalue(), mimetype='image/svg+xml')
