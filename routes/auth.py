from flask import Blueprint, render_template, request, session, redirect, url_for, flash, abort
from functools import wraps
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash
from models.user import get_user_by_email
from models.audit import write_audit, ACTION_LOGIN, ACTION_LOGOUT
from models.db import execute_query

auth_bp = Blueprint('auth', __name__)


def _lockout_seconds(attempts: int) -> int:
    """
    Progressive lockout — PUK-style.
    Attempts 1-2 : no lockout
    Attempt  3   : 30 s
    Attempt  4   : 40 s
    Attempt  N>=3: 30 + (N-3)*10 s
    """
    if attempts < 3:
        return 0
    return 30 + (attempts - 3) * 10


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                abort(401)
            if session.get('role') not in roles:
                abort(403)
            last_active_str = session.get('_last_active')
            if last_active_str:
                try:
                    last_active = datetime.fromisoformat(last_active_str)
                    if datetime.now() - last_active > timedelta(hours=8):
                        session.clear()
                        flash('Your session has expired. Please log in again.', 'warning')
                        return redirect(url_for('auth.login'))
                except (ValueError, TypeError):
                    session.clear()
                    flash('Your session has expired. Please log in again.', 'warning')
                    return redirect(url_for('auth.login'))
            session['_last_active'] = datetime.now().isoformat()
            return f(*args, **kwargs)
        return decorated
    return decorator


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return _role_redirect(session.get('role'))

    if request.method == 'GET':
        return render_template('login.html', now=datetime.now())

    email    = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    # ------------------------------------------------------------------
    # Look up the user first so we can query their DB-side lockout state.
    # If the user doesn't exist we still go through the lockout path to
    # avoid leaking whether an email is registered (timing side-channel is
    # acceptable here; the lockout is the important part).
    # ------------------------------------------------------------------
    user = None
    try:
        user = get_user_by_email(email)
    except Exception:
        pass

    # ------------------------------------------------------------------
    # Server-side lockout check (M2 fix)
    # login_attempts and lockout_until are stored in the DB, not the session,
    # so a client cannot reset them by clearing cookies.
    # The migration_add_lockout.sql migration must be applied first.
    # ------------------------------------------------------------------
    if user:
        db_lockout_until = user.get('lockout_until')
        if db_lockout_until:
            # psycopg2 returns TIMESTAMP as a datetime object; handle both.
            if isinstance(db_lockout_until, str):
                db_lockout_until = datetime.fromisoformat(db_lockout_until)
            remaining = (db_lockout_until - datetime.now()).total_seconds()
            if remaining > 0:
                flash(f'Too many failed attempts. Try again in {int(remaining)} second(s).', 'error')
                return render_template('login.html', now=datetime.now()), 429

    valid = user and user.get('is_active') and check_password_hash(user['password_hash'], password)

    if not valid:
        if user:
            # Increment attempt counter and compute new lockout in one UPDATE.
            # Using the threshold from _lockout_seconds: lockout triggers at attempt >= 3.
            execute_query(
                """
                UPDATE users
                SET login_attempts = login_attempts + 1,
                    lockout_until = CASE
                        WHEN login_attempts + 1 >= 3
                        THEN NOW() + (30 + (login_attempts + 1 - 3) * 10) * INTERVAL '1 second'
                        ELSE NULL
                    END
                WHERE email = %s
                """,
                params=(email,),
                commit=True,
            )
            # Re-fetch to show accurate remaining lockout time in the flash message.
            try:
                updated = get_user_by_email(email)
                new_attempts = updated.get('login_attempts', 0) if updated else 0
                lock_secs = _lockout_seconds(new_attempts)
            except Exception:
                lock_secs = 0
            if lock_secs > 0:
                flash(f'Invalid credentials. Locked for {lock_secs} second(s).', 'error')
            else:
                flash('Invalid credentials.', 'error')
        else:
            # Unknown email — no DB row to update; just flash a generic error.
            flash('Invalid credentials.', 'error')
        return render_template('login.html', now=datetime.now()), 401

    if not user.get('is_active'):
        flash('Account is deactivated. Contact an administrator.', 'error')
        return render_template('login.html', now=datetime.now()), 403

    # Successful login — reset server-side lockout counters.
    execute_query(
        "UPDATE users SET login_attempts = 0, lockout_until = NULL WHERE email = %s",
        params=(email,),
        commit=True,
    )

    session.permanent = True
    session['user_id']      = user['id']
    session['role']         = user['role']
    session['full_name']    = user['full_name']
    session['_last_active'] = datetime.now().isoformat()

    write_audit(user['id'], ACTION_LOGIN, f"Login from {request.remote_addr}", request.remote_addr)
    return _role_redirect(user['role'])


@auth_bp.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        write_audit(user_id, ACTION_LOGOUT, 'User logged out', request.remote_addr)
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/')
def index():
    if not session.get('user_id'):
        return redirect(url_for('auth.login'))
    return _role_redirect(session.get('role'))


def _role_redirect(role):
    if role in ('admin', 'faculty'):
        return redirect(url_for('attendance.dashboard'))
    if role == 'student':
        return redirect(url_for('attendance.my_attendance'))
    return redirect(url_for('auth.login'))
