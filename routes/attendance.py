"""
routes/attendance.py — Attendance Blueprint (fully implemented)

Routes
------
GET  /kiosk              — Live recognition kiosk (Task 3.1)
GET  /dashboard          — Attendance dashboard with summary cards (Task 4.1)
GET  /reports            — Attendance reports with filters (Task 4.3)
GET  /reports/export     — CSV download (Task 4.4)
GET  /my-attendance      — Student self-service (Task 4.7)
POST /attendance/manual  — Admin manual override (Task 4.5)
"""

import csv
import io
import logging
from datetime import date as date_type, datetime, timedelta

import config as app_config
from flask import (
    Blueprint, flash, jsonify, redirect, render_template,
    request, session, url_for, Response,
)
from models.attendance import get_today_records, get_records, manual_override as db_manual_override
from models.audit import write_audit, ACTION_MANUAL_OVERRIDE
from models.db import execute_query
from models.user import get_user_by_id
from routes.auth import role_required

logger = logging.getLogger(__name__)

attendance_bp = Blueprint("attendance", __name__)


# ---------------------------------------------------------------------------
# Kiosk
# ---------------------------------------------------------------------------

@attendance_bp.route("/kiosk")
@role_required("admin", "faculty")
def kiosk():
    return render_template("kiosk.html", brightness_threshold=app_config.BRIGHTNESS_THRESHOLD)


# ---------------------------------------------------------------------------
# Dashboard  (Task 4.1 — Requirements 7.1, 7.2, 7.4, 7.5, 7.6)
# ---------------------------------------------------------------------------

@attendance_bp.route("/dashboard")
@role_required("admin", "faculty")
def dashboard():
    """
    GET /dashboard — summary cards + live-updating attendance table.
    Summary counts are computed server-side on page load; the table is
    refreshed every 3 s by dashboard.js polling GET /api/live-feed.
    """
    today = date_type.today().isoformat()

    try:
        present_count = (execute_query(
            "SELECT COUNT(*) AS c FROM attendance WHERE date=%s AND status='present'",
            params=(today,), fetchone=True) or {}).get("c", 0)

        late_count = (execute_query(
            "SELECT COUNT(*) AS c FROM attendance WHERE date=%s AND status='late'",
            params=(today,), fetchone=True) or {}).get("c", 0)

        total_users = (execute_query(
            "SELECT COUNT(*) AS c FROM users WHERE is_active=1",
            fetchone=True) or {}).get("c", 0)

        records = get_today_records()
    except Exception as exc:
        logger.error("dashboard: DB error — %s", exc)
        present_count = late_count = total_users = 0
        records = []

    return render_template(
        "dashboard.html",
        now=datetime.now(),
        present_count=present_count,
        late_count=late_count,
        total_users=total_users,
        records=records,
    )


# ---------------------------------------------------------------------------
# Reports  (Task 4.3 — Requirements 8.1, 8.2, 8.3)
# ---------------------------------------------------------------------------

@attendance_bp.route("/reports")
@role_required("admin", "faculty")
def reports():
    """
    GET /reports — filter controls + paginated attendance table.
    """
    start_date = request.args.get("start_date", "").strip()
    end_date   = request.args.get("end_date",   "").strip()
    role       = request.args.get("role",        "").strip()
    department = request.args.get("department",  "").strip()[:100]

    filter_error = None

    # Server-side date validation (mirrors client-side check — Req 8.3)
    if start_date and end_date and start_date > end_date:
        filter_error = "Start date cannot be after end date."

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    records = []
    total = pages = 0

    if not filter_error:
        filters = {
            "start_date": start_date or None,
            "end_date":   end_date   or None,
            "role":       role       or None,
            "department": department or None,
            "page":       page,
            "per_page":   50,
        }
        try:
            result = get_records(filters)
            records = result["records"]
            total   = result["total"]
            pages   = result["pages"]
        except Exception as exc:
            logger.error("reports: DB error — %s", exc)
            filter_error = "Database error — could not load records."

    return render_template(
        "reports.html",
        records=records,
        total=total,
        pages=pages,
        current_page=page,
        start_date=start_date,
        end_date=end_date,
        role=role,
        department=department,
        filter_error=filter_error,
    )


# ---------------------------------------------------------------------------
# Reports CSV Export  (Task 4.4 — Requirements 8.4, 8.5, 8.6)
# ---------------------------------------------------------------------------

@attendance_bp.route("/reports/export")
@role_required("admin", "faculty")
def reports_export():
    """
    GET /reports/export — download all matching records as CSV.
    """
    start_date = request.args.get("start_date", "").strip()
    end_date   = request.args.get("end_date",   "").strip()
    role       = request.args.get("role",        "").strip()
    department = request.args.get("department",  "").strip()[:100]

    # Validate date range (Req 8.6)
    if start_date and end_date and start_date > end_date:
        return jsonify({"error": "Start date cannot be after end date."}), 400

    # Validate role value (Req 8.6)
    valid_roles = {"", "admin", "faculty", "student"}
    if role not in valid_roles:
        return jsonify({"error": f"Unrecognized role: {role}"}), 400

    try:
        result = get_records({
            "start_date": start_date or None,
            "end_date":   end_date   or None,
            "role":       role       or None,
            "department": department or None,
            "page": 1, "per_page": 100000,   # export all matching rows
        })
        records = result["records"]
    except Exception as exc:
        logger.error("reports_export: DB error — %s", exc)
        return jsonify({"error": "Database error."}), 503

    # Build CSV in memory (Req 8.4 — exact column order)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "full_name", "id_number", "department", "role",
        "date", "time_in", "time_out", "status", "confidence",
    ])
    for r in records:
        writer.writerow([
            r.get("full_name", ""),
            r.get("id_number", ""),
            r.get("department", ""),
            r.get("role", ""),
            r.get("date", ""),
            str(r.get("time_in",  "") or ""),
            str(r.get("time_out", "") or ""),
            r.get("status", ""),
            r.get("confidence", ""),
        ])

    output.seek(0)
    filename = f"attendance_{date_type.today().isoformat()}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Manual Attendance Override  (Task 4.5 — Requirements 9.1–9.5)
# ---------------------------------------------------------------------------

@attendance_bp.route("/attendance/manual", methods=["POST"])
@role_required("admin")
def manual_override():
    """
    POST /attendance/manual
    JSON body: {user_id: int, date: "YYYY-MM-DD"}
    """
    admin_id = session["user_id"]
    data = request.get_json(silent=True) or {}

    target_user_id = data.get("user_id")
    target_date    = data.get("date", "").strip()

    # -- Validate user_id (Req 9.3) --
    if not target_user_id:
        return jsonify({"error": "user_id is required."}), 400
    try:
        target_user_id = int(target_user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "user_id must be an integer."}), 400

    user = get_user_by_id(target_user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    # -- Validate date (Req 9.4) --
    if not target_date:
        return jsonify({"error": "date is required (YYYY-MM-DD)."}), 400
    try:
        parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date format — use YYYY-MM-DD."}), 400

    today = date_type.today()
    if parsed_date > today:
        return jsonify({"error": "Date cannot be in the future."}), 400
    if (today - parsed_date).days > 365:
        return jsonify({"error": "Date must be within the past 365 days."}), 400

    # -- Apply override then write audit (Req 9.1, 9.2, 9.5) --
    try:
        db_manual_override(target_user_id, target_date, admin_id)
    except Exception as exc:
        logger.error("manual_override: DB error — %s", exc)
        return jsonify({"error": "Database error — override could not be applied."}), 503

    # Audit write — if it fails we must roll back the attendance change (Req 9.5)
    try:
        write_audit(
            user_id=admin_id,
            action=ACTION_MANUAL_OVERRIDE,
            details=(
                f"Admin user_id={admin_id} manually set "
                f"attendance for user_id={target_user_id} on {target_date} to 'manual'"
            ),
            ip_address=request.remote_addr or "",
        )
    except Exception as exc:
        logger.error("manual_override: audit write failed, rolling back — %s", exc)
        # Roll back: delete the row we just inserted/updated
        try:
            execute_query(
                "DELETE FROM attendance WHERE user_id=%s AND date=%s AND status='manual'",
                params=(target_user_id, target_date), commit=True,
            )
        except Exception:
            pass
        return jsonify({"error": "Audit log failure — override rolled back."}), 500

    return jsonify({"success": True, "message": "Attendance overridden successfully."}), 200


# ---------------------------------------------------------------------------
# Student self-service  (Task 4.7 — Requirements 12.1, 12.2, 12.3)
# ---------------------------------------------------------------------------

@attendance_bp.route("/my-attendance")
@role_required("student")
def my_attendance():
    """
    GET /my-attendance — only the current student's own records.
    """
    student_id = session["user_id"]
    try:
        records = execute_query(
            "SELECT date, time_in, time_out, status "
            "FROM attendance WHERE user_id=%s "
            "ORDER BY date DESC",
            params=(student_id,), fetchall=True,
        ) or []
    except Exception as exc:
        logger.error("my_attendance: DB error — %s", exc)
        records = []

    return render_template("my_attendance.html", records=records)
