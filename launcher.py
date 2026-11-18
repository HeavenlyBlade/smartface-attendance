"""
launcher.py — SmartFace desktop launcher
Starts Flask via waitress in a background thread, waits for the server
to be ready, then opens http://localhost:5000 in the default browser.
"""
import threading
import time
import webbrowser
import urllib.request
import urllib.error
import sys
import os

# When running as a PyInstaller bundle, sys._MEIPASS is the temp extraction dir.
# Add it to sys.path so imports resolve correctly.
if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
    if bundle_dir not in sys.path:
        sys.path.insert(0, bundle_dir)
    os.chdir(bundle_dir)

    # Patch face_recognition_models to find its .dat files inside the bundle
    import face_recognition_models as _frm
    _frm_models_path = os.path.join(bundle_dir, 'face_recognition_models', 'models')
    if os.path.isdir(_frm_models_path):
        # Monkey-patch all model path functions
        def _make_path(filename):
            return os.path.join(_frm_models_path, filename)
        _frm.pose_predictor_model_location      = lambda: _make_path('shape_predictor_68_face_landmarks.dat')
        _frm.pose_predictor_five_point_model_location = lambda: _make_path('shape_predictor_5_face_landmarks.dat')
        _frm.face_recognition_model_location    = lambda: _make_path('dlib_face_recognition_resnet_model_v1.dat')
        _frm.cnn_face_detector_model_location   = lambda: _make_path('mmod_human_face_detector.dat')

URL = 'http://localhost:5000'

def _serve():
    from waitress import serve
    from app import create_app
    app = create_app()
    serve(app, host='0.0.0.0', port=5000, threads=4)

def _wait_for_server(timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(URL + '/login', timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False

if __name__ == '__main__':
    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    print('SmartFace is starting...')
    if _wait_for_server():
        webbrowser.open(URL)
        print(f'SmartFace is running at {URL} — close this window to stop.')
    else:
        print('Warning: server did not respond within 10 seconds. Check for errors above.')
    try:
        t.join()
    except KeyboardInterrupt:
        print('SmartFace stopped.')
