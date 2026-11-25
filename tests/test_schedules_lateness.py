"""
tests/test_schedules_lateness.py -- Tests for Schedule Maker, Lateness Analysis, and Multi-Scanner support
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.schedule import (
    create_schedule,
    get_all_schedules,
    get_schedule_by_id,
    update_schedule,
    delete_schedule,
    get_schedule_for_user,
    evaluate_attendance_time,
)
from models.attendance import (
    get_lateness_records,
    update_late_details,
)
from services.attendance_service import (
    log_attendance,
    _determine_status,
    last_seen_dict,
)
from database.init_db import init_db
from models.db import execute_query
init_db()


def test_schedule_crud_and_evaluation():
    """Verify schedule creation, retrieval, evaluation, and update."""
    # 1. Create schedule
    sched_id = create_schedule(
        name="Test Morning Shift",
        department="Computer Science",
        days_of_week="Monday,Tuesday,Wednesday,Thursday,Friday",
        start_time="08:00:00",
        end_time="17:00:00",
        grace_period_mins=15,
        is_default=0,
        is_active=1,
    )
    assert sched_id > 0

    sched = get_schedule_by_id(sched_id)
    assert sched is not None
    assert sched["name"] == "Test Morning Shift"
    assert sched["grace_period_mins"] == 15

    # 2. Evaluate attendance within grace period (08:10 -> on time)
    t_ontime = datetime(2026, 11, 24, 8, 10, 0)
    res_ontime = evaluate_attendance_time(sched, t_ontime)
    assert res_ontime["status"] == "present"
    assert res_ontime["late_minutes"] == 0

    # 3. Evaluate attendance past grace period (08:35 -> late)
    t_late = datetime(2026, 11, 24, 8, 35, 0)
    res_late = evaluate_attendance_time(sched, t_late)
    assert res_late["status"] == "late"
    assert res_late["late_minutes"] == 35  # 35 mins from 08:00
    assert "Late by 35 min(s)" in res_late["explanation"]
    assert "20 min(s) past grace cutoff" in res_late["explanation"]

    # 4. Update schedule
    update_schedule(
        schedule_id=sched_id,
        name="Updated Morning Shift",
        department="Computer Science",
        days_of_week="Monday,Tuesday,Wednesday,Thursday,Friday",
        start_time="08:30:00",
        end_time="17:30:00",
        grace_period_mins=10,
        is_default=0,
        is_active=1,
    )
    sched_updated = get_schedule_by_id(sched_id)
    assert sched_updated["name"] == "Updated Morning Shift"
    assert sched_updated["grace_period_mins"] == 10

    # Clean up
    delete_schedule(sched_id)
    assert get_schedule_by_id(sched_id) is None


def test_multi_scanner_logging_and_lateness_reasons():
    """Verify scanner_id recording, lateness reason storage, and stats aggregation."""
    last_seen_dict.clear()

    # Find or use an active user
    user = execute_query("SELECT id FROM users WHERE role='student' LIMIT 1", fetchone=True)
    if not user:
        user = execute_query("SELECT id FROM users LIMIT 1", fetchone=True)
    user_id = user["id"]

    test_date = "2026-11-20"
    # Clean previous record for isolation
    execute_query("DELETE FROM attendance WHERE user_id=? AND date=?", params=(user_id, test_date), commit=True)

    # Insert a late record with scanner station 'Gate 2 Kiosk'
    execute_query("""
        INSERT INTO attendance (user_id, date, time_in, status, confidence, late_minutes, late_reason, scanner_id, is_excused)
        VALUES (?, ?, '08:45:00', 'late', 98.5, 45, 'Traffic / Commute Delay', 'Gate 2 Kiosk', 0)
    """, params=(user_id, test_date), commit=True)

    # Query lateness records
    lateness_data = get_lateness_records({"start_date": test_date, "end_date": test_date})
    records = lateness_data["records"]
    assert len(records) >= 1

    matched = [r for r in records if r["user_id"] == user_id and r["date"] == test_date]
    assert len(matched) == 1
    rec = matched[0]
    assert rec["scanner_id"] == "Gate 2 Kiosk"
    assert rec["late_minutes"] == 45
    assert rec["late_reason"] == "Traffic / Commute Delay"
    assert rec["is_excused"] == 0

    # Update lateness reason to Excused
    att_id = rec["attendance_id"]
    update_late_details(
        attendance_id=att_id,
        reason="Medical / Health Issue",
        remarks="Submitted medical certificate from school clinic",
        is_excused=1,
        admin_id=1,
    )

    updated_data = get_lateness_records({"start_date": test_date, "end_date": test_date})
    updated_rec = [r for r in updated_data["records"] if r["attendance_id"] == att_id][0]
    assert updated_rec["late_reason"] == "Medical / Health Issue"
    assert updated_rec["late_remarks"] == "Submitted medical certificate from school clinic"
    assert updated_rec["is_excused"] == 1
    assert updated_data["summary"]["excused_count"] >= 1

    # Clean up test row
    execute_query("DELETE FROM attendance WHERE id=?", params=(att_id,), commit=True)


def test_separate_student_programs_and_faculty_schedules():
    """Verify separate schedules for Student programs (BSA, BSBA, BSIT, BSCE, BSIE) vs Faculty."""
    # 1. Create a student schedule for BSIT
    bsit_sched_id = create_schedule(
        name="BSIT Lab Schedule",
        role="student",
        department="BSIT",
        days_of_week="Monday,Tuesday,Wednesday,Thursday,Friday",
        start_time="09:00:00",
        end_time="18:00:00",
        grace_period_mins=20,
        is_default=0,
        is_active=1,
    )
    assert bsit_sched_id > 0

    # 2. Create a faculty schedule
    faculty_sched_id = create_schedule(
        name="Engineering Faculty Shift",
        role="faculty",
        department="College of Engineering",
        days_of_week="Monday,Tuesday,Wednesday,Thursday,Friday",
        start_time="07:30:00",
        end_time="16:30:00",
        grace_period_mins=10,
        is_default=0,
        is_active=1,
    )
    assert faculty_sched_id > 0

    # 3. Retrieve student schedules only
    student_scheds = get_all_schedules(role="student")
    assert any(s["id"] == bsit_sched_id for s in student_scheds)
    assert not any(s["id"] == faculty_sched_id for s in student_scheds)

    # 4. Retrieve faculty schedules only
    faculty_scheds = get_all_schedules(role="faculty")
    assert any(s["id"] == faculty_sched_id for s in faculty_scheds)
    assert not any(s["id"] == bsit_sched_id for s in faculty_scheds)

    # 5. Clean up
    delete_schedule(bsit_sched_id)
    delete_schedule(faculty_sched_id)
