from dotenv import load_dotenv
load_dotenv()
import argparse, logging, os, socket, sys

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("serve")

# Railway injects PORT as an env var; fall back to 5000 for local use
DEFAULT_PORT = int(os.environ.get("PORT", 5000))

p = argparse.ArgumentParser(description="SmartFace production server")
p.add_argument("--host",    default="0.0.0.0")
p.add_argument("--port",    default=DEFAULT_PORT, type=int)
p.add_argument("--threads", default=4,            type=int)
p.add_argument("--ssl",     action="store_true")
a = p.parse_args()

from app import app as fa

if a.ssl:
    try:
        import OpenSSL
    except ImportError:
        log.error("pyopenssl not installed. Run: pip install pyopenssl")
        sys.exit(1)
    log.info("SmartFace HTTPS starting on %s:%d", a.host, a.port)
    fa.run(host=a.host, port=a.port, ssl_context="adhoc",
           debug=False, use_reloader=False, threaded=True)
else:
    from waitress import serve as _ws
    try:
        lan = socket.gethostbyname(socket.gethostname())
    except Exception:
        lan = "?"
    log.info("=" * 52)
    log.info("SmartFace  |  Production  |  Waitress WSGI")
    log.info("  Local  : http://localhost:%d", a.port)
    log.info("  LAN    : http://%s:%d", lan, a.port)
    log.info("  Threads: %d", a.threads)
    log.info("=" * 52)
    _ws(fa, host=a.host, port=a.port, threads=a.threads,
        channel_timeout=120, ident="SmartFace/1.0")
