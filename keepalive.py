"""
keepalive.py - Supabase keepalive script
Run daily via Windows Task Scheduler to prevent Supabase free tier pausing.
Queries the users table -- counts as database activity.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

try:
    from models.db import execute_query
    row = execute_query("SELECT COUNT(*) AS c FROM users", fetchone=True)
    count = row["c"] if row else 0
    print(f"Supabase keepalive OK - {count} users in DB")
except Exception as e:
    print(f"Keepalive FAILED: {e}")
    sys.exit(1)