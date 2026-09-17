"""
Helper script — writes all production-hardening files for SmartFace.
Run with: py -3.11 _write_files.py
"""
import os

BASE = r"c:\Users\Asus\Desktop\SmartFace"

# ── Task 1: serve.py ────────────────────────────────────────────────────────
SERVE_PY = '''\
import argparse
import socket

# ---------------------------------------------------------------------------
# serve.py — production entry-point for SmartFace
# Usage:
#   py -3.11 serve.py                        # waitress, 0.0.0.0:5000, 4 threads
#   py -3.11 serve.py --port 8080            # custom port
#   py -3.11 serve.py --threads 8            # more worker threads
#   py -3.11 serve.py --ssl                  # ad-hoc TLS dev mode (Flask dev server)
# ---------------------------------------------------------------------------


def get_lan_ip() -> str:
    """Return the LAN IP address of this machine, falling back to 127.0.0.1."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SmartFace production server (waitress) or SSL dev server."
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Bind port (default: 5000)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Number of waitress worker threads (default: 4, ignored with --ssl)",
    )
    parser.add_argument(
        "--ssl",
        action="store_true",
        help="Enable ad-hoc TLS via pyOpenSSL (uses Flask dev server, not waitress)",
    )
    return parser.parse_args()


def print_banner(host: str, port: int, ssl: bool, lan_ip: str) -> None:
    scheme = "https" if ssl else "http"
    local_url = f"{scheme}://127.0.0.1:{port}"
    lan_url   = f"{scheme}://{lan_ip}:{port}"

    print()
    print("  \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510")
    print("  \u2502            SmartFace  \u2014  Server Starting         \u2502")
    print("  \u251c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2524")
    print(f"  \u2502  Local : {local_url:<41}\u2502")
    print(f"  \u2502  LAN   : {lan_url:<41}\u2502")
    if ssl:
        print("  \u2502  Mode  : Flask dev server  (ad-hoc TLS)          \u2502")
    else:
        print("  \u2502  Mode  : Waitress WSGI server (production)       \u2502")
    print("  \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518")
    print()


def main() -> None:
    args = parse_args()

    # Import here so the banner prints before any heavy module loading
    from app import app as flask_app  # noqa: E402

    lan_ip = get_lan_ip()
    print_banner(args.host, args.port, args.ssl, lan_ip)

    if args.ssl:
        # Ad-hoc TLS requires: pip install pyOpenSSL
        flask_app.run(
            host=args.host,
            port=args.port,
            ssl_context="adhoc",
            use_reloader=False,
        )
    else:
        import waitress  # noqa: E402 — optional dep; import after banner
        waitress.serve(
            flask_app,
            host=args.host,
            port=args.port,
            threads=args.threads,
            channel_timeout=120,
            cleanup_interval=30,
        )


if __name__ == "__main__":
    main()
'''

with open(os.path.join(BASE, "serve.py"), "w", newline="\n") as f:
    f.write(SERVE_PY)
print("✓ serve.py written")

# ── Task 2: .gitignore ───────────────────────────────────────────────────────
GITIGNORE = """\
.env
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
.hypothesis/
uploads/
*.log
venv/
.venv/
instance/
*.egg-info/
"""

with open(os.path.join(BASE, ".gitignore"), "w", newline="\n") as f:
    f.write(GITIGNORE)
print("✓ .gitignore written")

# ── Task 3: requirements.txt — append waitress if missing ───────────────────
req_path = os.path.join(BASE, "requirements.txt")
with open(req_path, "r") as f:
    req_content = f.read()

if "waitress" not in req_content:
    with open(req_path, "a", newline="\n") as f:
        f.write("waitress==3.0.1\n")
    print("✓ waitress==3.0.1 appended to requirements.txt")
else:
    print("✓ waitress already in requirements.txt — no change needed")

# ── Task 4: static/audio/.gitkeep ───────────────────────────────────────────
audio_dir = os.path.join(BASE, "static", "audio")
os.makedirs(audio_dir, exist_ok=True)
gitkeep_path = os.path.join(audio_dir, ".gitkeep")
with open(gitkeep_path, "w") as f:
    f.write("")
print("✓ static/audio/.gitkeep created")

print("\nAll files written successfully.")
