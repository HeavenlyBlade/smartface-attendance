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

    search = request.args.get("q", "").strip()
    result = list_users(page=page, per_page=25, search=search)
    # Add encoding count per user
    from models.db import execute_query as _eq
    user_list = result["users"] or []
    enc_counts = {}
    try:
        rows = _eq("SELECT user_id, COUNT(*) AS cnt FROM face_encodings GROUP BY user_id", fetchall=True)
        enc_counts = {r["user_id"]: int(r["cnt"]) for r in (rows or [])}
    except Exception:
        pass
    for u in user_list:
        u["enc_count"] = enc_counts.get(u["id"], 0)
    return render_template(
        "users.html",
        users=user_list,
        total=result["total"],
        pages=result["pages"],
        current_page=page,
        search=search,
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
    if request.form.get('csrf_token') != session.get('csrf_token'):
        from flask import abort
        abort(403)
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
    if request.form.get('csrf_token') != session.get('csrf_token'):
        from flask import abort
        abort(403)
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
    if request.form.get('csrf_token') != session.get('csrf_token'):
        from flask import abort
        abort(403)
    admin_id = session["user_id"]

    target = get_user_by_id(user_id)
    if not target:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))

    try:
        # 1. Delete face_encodings rows
        execute_query(
            "DELETE FROM face_encodings WHERE user_id = ?",
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
# Delete User  (hard delete — removes user + all associated data)
# ---------------------------------------------------------------------------

@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def delete_user_route(user_id: int):
    """
    POST /users/<id>/delete
    Permanently deletes the user, their face encodings, attendance records,
    and raw JPEG samples. Writes an audit log entry.
    """
    import shutil
    from models.audit import write_audit, ACTION_USER_DELETED

    if request.form.get('csrf_token') != session.get('csrf_token'):
        from flask import abort
        abort(403)
    admin_id = session["user_id"]

    if user_id == admin_id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin.users"))

    target = get_user_by_id(user_id)
    if not target:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))

    try:
        # Remove raw JPEG samples directory
        sample_dir = os.path.join(config.UPLOAD_DIR, str(user_id))
        if os.path.isdir(sample_dir):
            shutil.rmtree(sample_dir, ignore_errors=True)

        # Delete from DB (CASCADE removes face_encodings and attendance)
        execute_query("DELETE FROM users WHERE id = ?", params=(user_id,), commit=True)

        # Refresh encoding cache
        try:
            from services.face_service import reload_known_faces
            reload_known_faces()
        except Exception:
            pass

        # Audit log
        write_audit(
            user_id=admin_id,
            action=ACTION_USER_DELETED,
            details=f"Admin {admin_id} permanently deleted user id={user_id} ({target['full_name']}, {target['email']})",
            ip_address=request.remote_addr,
        )

        flash(f"User '{target['full_name']}' has been permanently deleted.", "success")
    except Exception as exc:
        logger.error("delete_user_route: failed for user_id=%s — %s", user_id, exc)
        flash("An error occurred while deleting the user.", "error")

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
        ACTION_USER_DELETED,
    )
    action_choices = [
        (ACTION_LOGIN,           "User Login"),
        (ACTION_LOGOUT,          "User Logout"),
        (ACTION_ENROLL,          "User Enrolled"),
        (ACTION_MANUAL_OVERRIDE, "Manual Override"),
        (ACTION_DEACTIVATE,      "User Deactivated"),
        (ACTION_BIOMETRIC_DELETE,"Biometric Deleted"),
        (ACTION_USER_DELETED,    "User Deleted"),
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


@admin_bp.route("/accuracy-test")
@role_required("admin")
def accuracy_test():
    """
    GET /accuracy-test
    Threshold analysis based on enrolled face encodings.
    Shows genuine pair distances, impostor pair distances, and
    estimated FAR/FRR at threshold values 0.30-0.60.
    """
    try:
        from services.face_service import FACE_RECOGNITION_AVAILABLE, deserialize_encoding
    except ImportError:
        FACE_RECOGNITION_AVAILABLE = False
        deserialize_encoding = None

    if not FACE_RECOGNITION_AVAILABLE:
        return render_template(
            "accuracy_test.html",
            unavailable=True,
            message="face_recognition is not available on this deployment. Run locally to use this feature."
        )

    import numpy as np
    try:
        rows = execute_query(
            "SELECT user_id, encoding FROM face_encodings WHERE encoding IS NOT NULL",
            fetchall=True
        ) or []
    except Exception as exc:
        return render_template("accuracy_test.html", unavailable=True, message=f"DB error: {exc}")

    # Group encodings by user_id
    from collections import defaultdict
    user_encs = defaultdict(list)
    for row in rows:
        try:
            enc = deserialize_encoding(bytes(row["encoding"]))
            if enc.shape == (128,):
                user_encs[row["user_id"]].append(enc)
        except Exception:
            pass

    enrolled_users = len(user_encs)
    total_encodings = sum(len(v) for v in user_encs.values())

    if enrolled_users < 2:
        return render_template(
            "accuracy_test.html",
            unavailable=True,
            message="Need at least 2 enrolled users to run accuracy test."
        )

    import face_recognition as _fr
    uids = list(user_encs.keys())
    genuine_dists = []
    impostor_dists = []

    # Genuine pairs: same user_id, different sample indices
    for uid, encs in user_encs.items():
        for i in range(len(encs)):
            for j in range(i + 1, len(encs)):
                d = float(_fr.face_distance([encs[i]], encs[j])[0])
                genuine_dists.append(d)

    # Impostor pairs: different user_ids (sample first encoding per user to keep it manageable)
    first_encs = {uid: user_encs[uid][0] for uid in uids}
    for i in range(len(uids)):
        for j in range(i + 1, len(uids)):
            d = float(_fr.face_distance([first_encs[uids[i]]], first_encs[uids[j]])[0])
            impostor_dists.append(d)

    # Statistics
    mean_genuine  = round(float(np.mean(genuine_dists)),  4) if genuine_dists  else None
    mean_impostor = round(float(np.mean(impostor_dists)), 4) if impostor_dists else None

    # Suggested threshold: midpoint between means (if available)
    if mean_genuine is not None and mean_impostor is not None:
        suggested = round((mean_genuine + mean_impostor) / 2.0, 2)
    else:
        suggested = 0.45

    # Threshold sweep
    thresholds = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    threshold_rows = []
    for t in thresholds:
        # FAR: impostor pairs accepted (distance <= threshold) / total impostor pairs
        # FRR: genuine pairs rejected (distance > threshold) / total genuine pairs
        far = round(sum(1 for d in impostor_dists if d <= t) / max(1, len(impostor_dists)), 4) if impostor_dists else None
        frr = round(sum(1 for d in genuine_dists  if d >  t) / max(1, len(genuine_dists)),  4) if genuine_dists  else None
        threshold_rows.append({"threshold": t, "far": far, "frr": frr})

    return render_template(
        "accuracy_test.html",
        unavailable=False,
        enrolled_users=enrolled_users,
        total_encodings=total_encodings,
        genuine_count=len(genuine_dists),
        impostor_count=len(impostor_dists),
        mean_genuine=mean_genuine,
        mean_impostor=mean_impostor,
        suggested_threshold=suggested,
        current_threshold=0.45,
        threshold_rows=threshold_rows,
    )
