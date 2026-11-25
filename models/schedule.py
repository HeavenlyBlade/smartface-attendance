"""
models/schedule.py — Schedule data access and evaluation layer for SmartFace.
Provides schedule creation, listing, updating, deletion, and attendance evaluation.
Supports separate schedule rules for Students (BSA, BSBA, BSIT, BSCE, BSIE) and Faculty.
"""

import logging
from datetime import datetime, time as dt_time, timedelta
from typing import Optional, Dict, Any, List

from models.db import execute_query

logger = logging.getLogger(__name__)

DAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]

STUDENT_PROGRAMS = [
    "BSA",   # Bachelor of Science in Accountancy
    "BSBA",  # Bachelor of Science in Business Administration
    "BSIT",  # Bachelor of Science in Information Technology
    "BSCE",  # Bachelor of Science in Civil Engineering
    "BSIE",  # Bachelor of Science in Industrial Engineering
]


def get_all_schedules(only_active: bool = False, role: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all schedules, optionally filtered by active status and role."""
    conditions = []
    params = []
    if only_active:
        conditions.append("is_active = 1")
    if role:
        conditions.append("role = ?")
        params.append(role.lower().strip())

    sql = "SELECT * FROM schedules"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY role ASC, is_default DESC, name ASC"
    rows = execute_query(sql, params=tuple(params) if params else None, fetchall=True) or []
    return [dict(r) for r in rows]


def get_schedule_by_id(schedule_id: int) -> Optional[Dict[str, Any]]:
    """Fetch single schedule by ID."""
    sql = "SELECT * FROM schedules WHERE id = ? LIMIT 1"
    row = execute_query(sql, params=(schedule_id,), fetchone=True)
    return dict(row) if row else None


def create_schedule(
    name: str,
    department: str = "",
    days_of_week: str = "Monday,Tuesday,Wednesday,Thursday,Friday",
    start_time: str = "08:00:00",
    end_time: str = "17:00:00",
    grace_period_mins: int = 15,
    is_default: int = 0,
    is_active: int = 1,
    role: str = "student",
) -> int:
    """Create a new schedule (role: 'student' or 'faculty')."""
    role = (role or "student").strip().lower()
    if is_default:
        execute_query("UPDATE schedules SET is_default = 0 WHERE role = ?", params=(role,), commit=True)

    sql = (
        "INSERT INTO schedules (name, role, department, days_of_week, start_time, end_time, "
        "grace_period_mins, is_default, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    if len(start_time.split(":")) == 2:
        start_time = f"{start_time}:00"
    if len(end_time.split(":")) == 2:
        end_time = f"{end_time}:00"

    execute_query(
        sql,
        params=(
            name.strip(),
            role,
            department.strip(),
            days_of_week.strip(),
            start_time,
            end_time,
            int(grace_period_mins),
            int(is_default),
            int(is_active),
        ),
        commit=True,
    )
    row = execute_query("SELECT last_insert_rowid() AS id", fetchone=True)
    return int(row["id"]) if row else 0


def update_schedule(
    schedule_id: int,
    name: str,
    department: str = "",
    days_of_week: str = "Monday,Tuesday,Wednesday,Thursday,Friday",
    start_time: str = "08:00:00",
    end_time: str = "17:00:00",
    grace_period_mins: int = 15,
    is_default: int = 0,
    is_active: int = 1,
    role: str = "student",
) -> None:
    """Update an existing schedule."""
    role = (role or "student").strip().lower()
    if is_default:
        execute_query(
            "UPDATE schedules SET is_default = 0 WHERE role = ? AND id != ?",
            params=(role, schedule_id),
            commit=True,
        )

    if len(start_time.split(":")) == 2:
        start_time = f"{start_time}:00"
    if len(end_time.split(":")) == 2:
        end_time = f"{end_time}:00"

    sql = (
        "UPDATE schedules SET name = ?, role = ?, department = ?, days_of_week = ?, "
        "start_time = ?, end_time = ?, grace_period_mins = ?, is_default = ?, is_active = ? "
        "WHERE id = ?"
    )
    execute_query(
        sql,
        params=(
            name.strip(),
            role,
            department.strip(),
            days_of_week.strip(),
            start_time,
            end_time,
            int(grace_period_mins),
            int(is_default),
            int(is_active),
            schedule_id,
        ),
        commit=True,
    )


def delete_schedule(schedule_id: int) -> None:
    """Delete a schedule by ID."""
    execute_query("DELETE FROM schedules WHERE id = ?", params=(schedule_id,), commit=True)


def get_schedule_for_user(user_id: int, current_dt: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Find the best matching schedule for a user.
    Uses separate schedules for Students (BSA, BSBA, BSIT, BSCE, BSIE) and Faculty.
    """
    if current_dt is None:
        current_dt = datetime.now()

    day_name = DAY_NAMES[current_dt.weekday()]

    # Fetch user's department and role
    user_row = execute_query(
        "SELECT department, role FROM users WHERE id = ? LIMIT 1",
        params=(user_id,),
        fetchone=True,
    )
    user_dept = (user_row["department"] if user_row and user_row["department"] else "").strip().lower()
    user_role = (user_row["role"] if user_row and user_row["role"] else "student").strip().lower()

    # Retrieve schedules for this role
    schedules = get_all_schedules(only_active=True, role=user_role)
    if not schedules:
        schedules = get_all_schedules(only_active=True)

    dept_match = None
    default_match = None
    day_match = None

    for s in schedules:
        days = [d.strip() for d in s.get("days_of_week", "").split(",") if d.strip()]
        applies_today = not days or (day_name in days)

        s_dept = (s.get("department") or "").strip().lower()
        if applies_today:
            if user_dept and s_dept and (s_dept == user_dept or s_dept in user_dept or user_dept in s_dept):
                dept_match = s
                break
            if s.get("is_default"):
                default_match = s
            elif day_match is None:
                day_match = s

    chosen = dept_match or default_match or day_match

    if not chosen and schedules:
        chosen = schedules[0]

    if not chosen:
        if user_role == "faculty":
            return {
                "id": None,
                "name": "Standard Faculty Schedule",
                "role": "faculty",
                "department": "",
                "days_of_week": "Monday,Tuesday,Wednesday,Thursday,Friday",
                "start_time": "07:30:00",
                "end_time": "17:30:00",
                "grace_period_mins": 15,
                "is_default": 1,
                "is_active": 1,
            }
        return {
            "id": None,
            "name": "Standard Student Schedule",
            "role": "student",
            "department": "",
            "days_of_week": "Monday,Tuesday,Wednesday,Thursday,Friday",
            "start_time": "08:00:00",
            "end_time": "17:00:00",
            "grace_period_mins": 15,
            "is_default": 1,
            "is_active": 1,
        }

    return chosen


def evaluate_attendance_time(
    schedule: Dict[str, Any],
    check_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Evaluate arrival time against schedule start_time and grace_period_mins.
    """
    if check_time is None:
        check_time = datetime.now()

    start_str = schedule.get("start_time", "08:00:00")
    grace_mins = int(schedule.get("grace_period_mins", 15))

    parts = [int(p) for p in start_str.split(":")[:3]]
    while len(parts) < 3:
        parts.append(0)

    sched_start = check_time.replace(
        hour=parts[0], minute=parts[1], second=parts[2], microsecond=0
    )
    grace_cutoff = sched_start + timedelta(minutes=grace_mins)

    if check_time <= grace_cutoff:
        status = "present"
        late_minutes = 0
        explanation = f"On time (Arrived before grace cutoff {grace_cutoff.strftime('%I:%M %p')})"
    else:
        status = "late"
        diff_secs = (check_time - sched_start).total_seconds()
        late_minutes = max(1, int(round(diff_secs / 60.0)))
        mins_past_grace = int(round((check_time - grace_cutoff).total_seconds() / 60.0))
        explanation = (
            f"Late by {late_minutes} min(s) "
            f"(Arrived {check_time.strftime('%I:%M %p')}, "
            f"{mins_past_grace} min(s) past grace cutoff {grace_cutoff.strftime('%I:%M %p')})"
        )

    return {
        "status": status,
        "late_minutes": late_minutes,
        "schedule_id": schedule.get("id"),
        "schedule_name": schedule.get("name", "Standard Schedule"),
        "scheduled_start": start_str,
        "grace_cutoff": grace_cutoff.strftime("%H:%M:%S"),
        "explanation": explanation,
    }
