from flask import (Blueprint, flash, g, redirect, render_template,
                   request, session, url_for)

from ..auth import check_csrf, csrf_token, current_user, login_required
from ..models import Shipment, User

bp = Blueprint("main", __name__)

STATUS_LABELS = {
    "uploaded": "Uploaded",
    "extracted": "Extracted",
    "needs_review": "Needs review",
    "cleared": "Cleared",
    "exported": "Exported",
}


@bp.before_request
def _csrf():
    check_csrf()


@bp.app_context_processor
def _inject():
    return {"csrf_token": csrf_token, "user": current_user(), "STATUS_LABELS": STATUS_LABELS}


def _safe_next(target):
    # Only allow redirects to paths inside this app
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.shipments")


@bp.route("/")
def index():
    return redirect(url_for("main.shipments"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session.clear()  # prevents session fixation
            session["user_id"] = user.id
            return redirect(_safe_next(request.args.get("next")))
        flash("Invalid email or password.")  # same message for both cases
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("main.login"))


@bp.route("/shipments")
@login_required
def shipments():
    status = request.args.get("status")
    if status not in STATUS_LABELS:
        status = None  # ignore unknown filter values

    query = Shipment.query.order_by(Shipment.created_at.desc())
    all_shipments = query.all()
    counts = {key: 0 for key in STATUS_LABELS}
    for s in all_shipments:
        counts[s.status] = counts.get(s.status, 0) + 1

    rows = []
    for s in all_shipments:
        if status and s.status != status:
            continue
        rows.append({
            "s": s,
            "docs": len(s.documents),
            "flagged": sum(1 for d in s.documents for f in d.fields if f.state == "needs_confirm"),
            "failed": sum(1 for c in s.cross_checks if c.status == "fail"),
        })
    return render_template("shipments.html", rows=rows, counts=counts,
                           total=len(all_shipments), active=status)