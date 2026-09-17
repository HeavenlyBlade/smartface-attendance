"""Temporary verification script — safe to delete after task 1.5 is confirmed."""
import sys
print(f"Python {sys.version}")

try:
    import flask
    print(f"Flask {flask.__version__} — OK")
except ImportError as e:
    print(f"Flask not found: {e}")
    sys.exit(1)

try:
    from app import app
    blueprints = list(app.blueprints.keys())
    print(f"app.py loaded — blueprints registered: {blueprints}")
    expected = {"auth", "admin", "attendance", "api"}
    missing = expected - set(blueprints)
    if missing:
        print(f"MISSING blueprints: {missing}")
        sys.exit(1)
    else:
        print("All 4 blueprints registered — PASS")
except Exception as e:
    print(f"app.py failed to import: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)
