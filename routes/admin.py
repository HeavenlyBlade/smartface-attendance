"""
routes/admin.py — Admin Blueprint

Handles all Administrator-only pages and actions:
  GET  /enroll                         — Enrollment UI (Task 2.4)
  POST /api/enroll                     — Enrollment API (in routes/api.py)
  GET  /users                          — User management list (Task 2.7)
  POST /users/<id>/deactivate          — Toggle is_active flag (Task 2.7)
  POST /users/<id>/edit                — Update profile fields (Task 2.7)
  POST /users/<id>/delete-biometric    — Remove face_encodings + raw JPEGs (Task 2.7)
  GET  /audit                          — Audit log viewer (Task 2.8)

All routes are protected with @role_required('admin') from routes/auth.py.
"""

import logging
import os
import shutil

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from models.audit import (
    ACTION_BIOMETRIC_DELETE,
    ACTION_DEACTIVATE,
    list_audit,
    write_audit,
)
from models.db import execute_query
from models.user import (
    activate_user,
    deactivate_user,
    get_user_by_id,
    list_users,
    update_user,
)
from routes.auth import role_required
import config

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

@admin_bp.route("/enroll")
@role_required("admin")
def enroll_page():
    """
    GET /enroll

    Renders the face enrollment form.  The page streams a live webcam preview
    via getUserMedia (handled in static/js/enroll.js, added in Task 2.5).
    The POST submission is handled by POST /api/enroll in routes/api.py.
    """
    return render_template("enroll.html")


# ---------------------------------------------------------------------------
# User Management  (Requirement 10)
# ---------------------------------------------------------------------------

@admin_bp.route("/users")
@role_required("admin")
def users():
    """
    GET /users

    Paginated user management list.
    Shows full_name, id_number, role, department, is_active for every user,
    25 per page.  Requirement 10.1.
    """
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1

    result = list_users(page=page, per_page=25)
    return render_template(
        "users.html",
        users=result["users"],
        total=result["total"],
        pages=result["pages"],
        current_page=page,
    )


@admin_bp.route("/users/<int:user_id>/deactivate", methods=["POST"])
@role_required("admin")
def deactivate_user_route(user_id: int):
    """
    POST /users/<id>/deactivate

    Toggles the is_active flag for the target user.
    - Blocks self-deactivation (Requirement 10.5).
    - Writes an audit_logs entry on deactivation (Requirement 10.3).
    - Reactivation does not require an audit entry per spec.
    """
    admin_id = session["user_id"]

    # Requirement 10.5 — cannot deactivate own account
    if user_id == admin_id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin.users"))

    target = get_user_by_id(user_id)
    if not target:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))

    try:
        if target["is_active"]:
            # Deactivate
            deactivate_user(user_id)
            write_audit(
                user_id=admin_id,
                action=ACTION_DEACTIVATE,
                details=(
                    f"Deactivated user id={user_id} "
                    f"({target['full_name']}, {target['email']})"
                ),
                ip_address=request.remote_addr,
            )
            flash(
                f"User '{target['full_name']}' has been deactivated.",
                "success",
            )
        else:
            # Reactivate
            activate_user(user_id)
            flash(
                f"User '{target['full_name']}' has been reactivated.",
                "success",
            )
    except Exception as exc:
        logger.error(
            "deactivate_user_route: failed for user_id=%s — %s", user_id, exc
        )
        flash("An error occurred while updating the user status.", "error")

    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/edit", methods=["POST"])
@role_required("admin")
def edit_user_route(user_id: int):
    """
    POST /users/<id>/edit

    Update the profile fields of a user: full_name, department, role, id_number.
    Requirement 10.2.
    """
    target = get_user_by_id(user_id)
    if not target:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))

    # Collect and sanitize inputs
    fields = {}
    for field in ("full_name", "department", "role", "id_number"):
        value = request.form.get(field, "").strip()
        if value:
            fields[field] = value

    if not fields:
        flash("No valid fields were provided for update.", "warning")
        return redirect(url_for("admin.users"))

    # Validate role if provided
    if "role" in fields and fields["role"] not in ("admin", "faculty", "student"):
        flash("Invalid role value.", "error")
        return redirect(url_for("admin.users"))

    try:
        update_user(user_id, fields)
        flash(
            f"Profile for '{target['full_name']}' has been updated successfully.",
            "success",
        )
    except Exception as exc:
        logger.error(
            "edit_user_route: failed for user_id=%s — %s", user_id, exc
        )
        flash("An error occurred while updating the user profile.", "error")

    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete-biometric", methods=["POST"])
@role_required("admin")
def delete_biometric_route(user_id: int):
    """
    POST /users/<id>/delete-biometric

    Deletes all biometric data for the target user:
    1. Remove all face_encodings rows.
    2. Remove the raw JPEG directory at uploads/face_samples/<user_id>/.
    3. Call reload_known_faces() so the in-memory cache no longer matches
       the deleted user.
    4. Write an audit entry.
    Requirement 10.4, 11.2.
    """
    admin_id = session["user_id"]

    target = get_user_by_id(user_id)
    if not target:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))

    try:
        # 1. Delete face_encodings rows
        execute_query(
            "DELETE FROM face_encodings WHERE user_id = %s",
            params=(user_id,),
            commit=True,
        )

        # 2. Remove raw JPEG directory if it exists
        sample_dir = os.path.join(config.UPLOAD_DIR, str(user_id))
        if os.path.isdir(sample_dir):
            shutil.rmtree(sample_dir)
            logger.info(
                "delete_biometric_route: removed %s for user_id=%s",
                sample_dir, user_id,
            )

        # 3. Refresh in-memory encoding cache
        try:
            from services.face_service import reload_known_faces
            reload_known_faces()
        except Exception as cache_exc:
            # Non-fatal — cache will be stale until next enrollment/restart
            logger.error(
                "delete_biometric_route: reload_known_faces failed — %s", cache_exc
            )

        # 4. Write audit entry
        write_audit(
            user_id=admin_id,
            action=ACTION_BIOMETRIC_DELETE,
            details=(
                f"Deleted all biometric data for user id={user_id} "
                f"({target['full_name']}, {target['email']})"
            ),
            ip_address=request.remote_addr,
        )

        flash(
            f"All biometric data for '{target['full_name']}' has been deleted.",
            "success",
        )
    except Exception as exc:
        logger.error(
            "delete_biometric_route: failed for user_id=%s — %s", user_id, exc
        )
        flash("An error occurred while deleting biometric data.", "error")

    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------------------
# Audit Log  (Task 2.8 — filled out fully here)
# ---------------------------------------------------------------------------

@admin_bp.route("/audit")
@role_required("admin")
def audit_log():
    """
    GET /audit

    Paginated, reverse-chronological audit log viewer with optional filters
    for action type and date range.  Requirement 11.1.
    """
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1

    action_filter = request.args.get("action") or None
    start_date = request.args.get("start_date") or None
    end_date = request.args.get("end_date") or None

    result = list_audit(
        page=page,
        per_page=25,
        action_filter=action_filter,
        start_date=start_date,
        end_date=end_date,
    )

    # Build action choices for the filter dropdown
    from models.audit import (
        ACTION_LOGIN,
        ACTION_LOGOUT,
        ACTION_ENROLL,
        ACTION_MANUAL_OVERRIDE,
        ACTION_DEACTIVATE,
        ACTION_BIOMETRIC_DELETE,
    )
    action_choices = [
        (ACTION_LOGIN,           "User Login"),
        (ACTION_LOGOUT,          "User Logout"),
        (ACTION_ENROLL,          "User Enrolled"),
        (ACTION_MANUAL_OVERRIDE, "Manual Override"),
        (ACTION_DEACTIVATE,      "User Deactivated"),
        (ACTION_BIOMETRIC_DELETE,"Biometric Deleted"),
    ]

    return render_template(
        "audit.html",
        entries=result["entries"],
        total=result["total"],
        pages=result["pages"],
        current_page=page,
        action_filter=action_filter,
        start_date=start_date or "",
        end_date=end_date or "",
        action_choices=action_choices,
    )
