from flask import Blueprint, render_template, request, session, redirect, url_for, flash, abort
from functools import wraps
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash
from models.user import get_user_by_email
from models.audit import write_audit, ACTION_LOGIN, ACTION_LOGOUT

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
                    if datetime.now() - last_active > timedelta(minutes=30):
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


@auth_bp.route('/reset-session')
def reset_session():
    """Clears any active lockout — use when locked out during testing."""
    session.pop('lockout_until', None)
    session.pop('login_attempts', None)
    flash('Lockout cleared. You can log in now.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return _role_redirect(session.get('role'))

    if request.method == 'GET':
        return render_template('login.html', now=datetime.now())

    email    = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    # Active lockout check
    lockout_until = session.get('lockout_until')
    if lockout_until:
        if isinstance(lockout_until, str):
            lockout_until = datetime.fromisoformat(lockout_until)
        remaining = (lockout_until - datetime.now()).total_seconds()
        if remaining > 0:
            flash(f'Too many failed attempts. Try again in {int(remaining)} second(s).', 'error')
            return render_template('login.html', now=datetime.now()), 429
        else:
            session.pop('lockout_until', None)

    user = None
    try:
        user = get_user_by_email(email)
    except Exception:
        pass

    valid = user and user.get('is_active') and check_password_hash(user['password_hash'], password)

    if not valid:
        attempts = session.get('login_attempts', 0) + 1
        session['login_attempts'] = attempts
        lock_secs = _lockout_seconds(attempts)
        if lock_secs > 0:
            session['lockout_until'] = (datetime.now() + timedelta(seconds=lock_secs)).isoformat()
            flash(f'Invalid credentials. Locked for {lock_secs} second(s).', 'error')
        else:
            flash('Invalid credentials.', 'error')
        return render_template('login.html', now=datetime.now()), 401

    if not user.get('is_active'):
        flash('Account is deactivated. Contact an administrator.', 'error')
        return render_template('login.html', now=datetime.now()), 403

    session.permanent = True
    session['user_id']      = user['id']
    session['role']         = user['role']
    session['full_name']    = user['full_name']
    session['_last_active'] = datetime.now().isoformat()
    session.pop('login_attempts', None)
    session.pop('lockout_until',  None)

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
