"""
launcher.py -- SmartFace desktop launcher
Starts Flask via waitress silently in the background,
then opens http://localhost:5000 in the default browser.
No console window is shown. Errors are logged to
%APPDATA%\SmartFace\smartface.log
"""
import threading
import time
import webbrowser
import urllib.request
import sys
import os
import logging

# ---------------------------------------------------------------------------
# Resolve paths — works both frozen (.exe) and plain Python
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
else:
    bundle_dir = os.path.dirname(os.path.abspath(__file__))

if bundle_dir not in sys.path:
    sys.path.insert(0, bundle_dir)

os.chdir(bundle_dir)

# ---------------------------------------------------------------------------
# Robust logging to file (fallback to bundle dir, home, or temp)
# ---------------------------------------------------------------------------
import tempfile

def _setup_logger():
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else bundle_dir
    log_candidates = [
        os.path.join(exe_dir, 'smartface.log'),
        os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'SmartFace', 'smartface.log'),
        os.path.join(bundle_dir, 'smartface.log'),
        os.path.join(os.path.expanduser('~'), 'SmartFace', 'smartface.log'),
        os.path.join(os.path.expanduser('~'), 'smartface.log'),
        os.path.join(tempfile.gettempdir(), 'smartface.log'),
    ]
    chosen_path = None
    for p in log_candidates:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
            with open(p, 'a', encoding='utf-8') as f:
                f.write('')
            chosen_path = p
            break
        except Exception:
            continue

    handlers = []
    if chosen_path:
        try:
            handlers.append(logging.FileHandler(chosen_path, encoding='utf-8'))
        except Exception:
            pass
    if sys.stdout is not None:
        try:
            handlers.append(logging.StreamHandler(sys.stdout))
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=handlers,
    )
    return chosen_path or 'console'

_log_path = _setup_logger()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patch face_recognition_models paths when running frozen
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    try:
        import face_recognition_models as _frm
        _frm_models_path = os.path.join(bundle_dir, 'face_recognition_models', 'models')
        if os.path.isdir(_frm_models_path):
            def _make_path(filename):
                return os.path.join(_frm_models_path, filename)
            _frm.pose_predictor_model_location            = lambda: _make_path('shape_predictor_68_face_landmarks.dat')
            _frm.pose_predictor_five_point_model_location = lambda: _make_path('shape_predictor_5_face_landmarks.dat')
            _frm.face_recognition_model_location          = lambda: _make_path('dlib_face_recognition_resnet_model_v1.dat')
            _frm.cnn_face_detector_model_location         = lambda: _make_path('mmod_human_face_detector.dat')
            logger.info('face_recognition_models patched to %s', _frm_models_path)
    except Exception as e:
        logger.error('face_recognition_models patch failed: %s', e)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
URL = 'http://localhost:5000'
_server_error = None


def _is_port_in_use(host='127.0.0.1', port=5000) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _ensure_single_instance() -> bool:
    """
    Ensure no stale SmartFace.exe processes are holding port 5000.
    Returns True if we should start the server, or False if another
    server (e.g. `py app.py`) is already serving port 5000.
    """
    if getattr(sys, 'frozen', False):
        try:
            import subprocess
            subprocess.run(
                ['taskkill', '/F', '/FI', f'PID ne {os.getpid()}', '/IM', 'SmartFace.exe'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                timeout=5,
            )
            # Wait briefly for Windows to release port 5000
            for _ in range(15):
                if not _is_port_in_use():
                    break
                time.sleep(0.2)
        except Exception as exc:
            logger.warning('Single-instance cleanup warning: %s', exc)

    if _is_port_in_use():
        logger.info('Port 5000 already in use; opening existing server in browser.')
        webbrowser.open(URL)
        return False
    return True


def _serve():
    global _server_error
    try:
        from waitress import serve
        from app import create_app
        logger.info('SmartFace server starting...')
        app = create_app()
        logger.info('SmartFace server ready at %s', URL)
        serve(app, host='127.0.0.1', port=5000, threads=8)
    except Exception as exc:
        _server_error = str(exc)
        logger.exception('Server crashed: %s', exc)

def _wait_for_server(timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_error:
            return False
        try:
            urllib.request.urlopen(URL + '/login', timeout=1)
            return True
        except Exception:
            time.sleep(0.4)
    return False

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    if not _ensure_single_instance():
        sys.exit(0)

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    if _wait_for_server():
        logger.info('Browser opened at %s', URL)
        webbrowser.open(URL)
    else:
        logger.error('Server did not respond within 15 seconds: %s', _server_error)
        err_detail = f"\n\nError: {_server_error}" if _server_error else ""
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f'SmartFace failed to start.{err_detail}\n\nCheck the log at:\n{_log_path}',
                'SmartFace Error',
                0x10  # MB_ICONERROR
            )
        except Exception:
            pass

    # Keep the process alive — server thread is daemon so it stays up
    # as long as this main thread is alive
    try:
        t.join()
    except KeyboardInterrupt:
        logger.info('SmartFace stopped by user.')
