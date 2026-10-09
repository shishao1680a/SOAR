"""Shared PostgreSQL login guard; row locks serialize concurrent attempts."""
from contextlib import contextmanager
from hashlib import sha256
from math import ceil
from sqlalchemy import text


class LoginLimited(Exception):
    def __init__(self, seconds):
        self.seconds = max(1, ceil(seconds))


@contextmanager
def password_attempt(engine, username, source):
    keys = [('account:' + sha256(username.encode()).hexdigest(), 5),
            ('source:' + sha256(source.encode()).hexdigest(), 30)]
    keys.sort()
    with engine.begin() as conn:
        now = float(conn.execute(text('SELECT EXTRACT(EPOCH FROM clock_timestamp())')).scalar())
        rows = {}
        for key, threshold in keys:
            conn.execute(text('''INSERT INTO login_attempts (key, failures, window_start, blocked_until)
                VALUES (:key, 0, :now, 0) ON CONFLICT (key) DO NOTHING'''), {'key': key, 'now': now})
            rows[key] = dict(conn.execute(text('SELECT * FROM login_attempts WHERE key=:key FOR UPDATE'), {'key': key}).first()._mapping)
        # Use a fresh database clock after waiting for locks.
        now = float(conn.execute(text('SELECT EXTRACT(EPOCH FROM clock_timestamp())')).scalar())
        wait = max(float(r['blocked_until']) - now for r in rows.values())
        if wait > 0:
            raise LoginLimited(wait)
        outcome = {'success': False, 'connection': conn}
        yield outcome
        for key, threshold in keys:
            row = rows[key]
            expired = now - float(row['window_start']) >= 900
            failures = (0 if expired else int(row['failures']))
            start = now if expired else float(row['window_start'])
            if outcome['success'] and key.startswith('account:'):
                failures, start = 0, now
            elif not outcome['success']:
                failures += 1
            blocked = now + 900 if failures >= threshold else 0
            conn.execute(text('''UPDATE login_attempts SET failures=:failures,
                window_start=:start, blocked_until=:blocked WHERE key=:key'''),
                {'key': key, 'failures': failures, 'start': start, 'blocked': blocked})
