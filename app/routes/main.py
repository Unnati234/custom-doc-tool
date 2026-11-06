import os

from ..extraction import ExtractionError, UnreadableDocument, extract_document
from ..pipeline import apply_extraction, refresh_shipment
from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, send_from_directory, session, url_for, current_app)

from ..auth import check_csrf, csrf_token, current_user, login_required
from ..models import CrossCheck, Document, Shipment, User, db
from ..uploads import delete_upload, save_upload

bp = Blueprint("main", __name__)

STATUS_LABELS = {
    "uploaded": "Uploaded",
    "extracted": "Extracted",
    "needs_review": "Needs review",
    "cleared": "Cleared",
    "exported": "Exported",
}
DOC_TYPES = {
    "invoice": "Invoice",
    "packing_list": "Packing list",
    "bill_of_lading": "Bill of lading",
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


def _next_shipment_id():
    nums = []
    for s in Shipment.query.all():
        suffix = s.id.split("-")[-1]
        if suffix.isdigit():
            nums.append(int(suffix))
    return f"SHP-{(max(nums) if nums else 24800) + 1}"


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

    all_shipments = Shipment.query.order_by(Shipment.created_at.desc()).all()
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


@bp.route("/shipments/new", methods=["GET", "POST"])
@login_required
def new_shipment():
    if request.method == "POST":
        importer = request.form.get("importer", "").strip()
        supplier = request.form.get("supplier", "").strip()
        if not importer or not supplier:
            flash("Importer and supplier are both required.")
        elif len(importer) > 120 or len(supplier) > 120:
            flash("Names can be at most 120 characters.")
        else:
            shipment = Shipment(
                id=_next_shipment_id(), importer_name=importer, supplier_name=supplier,
                status="uploaded", created_by=current_user().id,
            )
            db.session.add(shipment)
            db.session.commit()
            return redirect(url_for("main.shipment_detail", shipment_id=shipment.id))
    return render_template("new_shipment.html")


@bp.route("/shipments/<shipment_id>")
@login_required
def shipment_detail(shipment_id):
    shipment = db.session.get(Shipment, shipment_id) or abort(404)
    docs = {d.doc_type: d for d in shipment.documents}
    return render_template("shipment_detail.html", shipment=shipment,
                           docs=docs, DOC_TYPES=DOC_TYPES)


@bp.route("/shipments/<shipment_id>/upload/<doc_type>", methods=["POST"])
@login_required
def upload_document(shipment_id, doc_type):
    shipment = db.session.get(Shipment, shipment_id) or abort(404)
    if doc_type not in DOC_TYPES:
        abort(404)
    back = redirect(url_for("main.shipment_detail", shipment_id=shipment_id))

    try:
        rel = save_upload(request.files.get("file"), shipment_id, doc_type)
    except ValueError as e:
        flash(str(e))
        return back

    doc = Document.query.filter_by(shipment_id=shipment_id, doc_type=doc_type).first()
    if doc:  # replacing: drop the old file and anything extracted from it
        delete_upload(doc.file_path)
        for f in list(doc.fields):
            db.session.delete(f)
        for item in list(doc.line_items):
            db.session.delete(item)
        doc.file_path = rel
        doc.extraction_status = "pending"
    else:
        db.session.add(Document(shipment_id=shipment_id, doc_type=doc_type,
                                file_path=rel, extraction_status="pending"))

    # New or replaced documents make old cross-check results stale
    for c in list(shipment.cross_checks):
        db.session.delete(c)
    shipment.status = "uploaded"
    db.session.commit()
    flash(f"{DOC_TYPES[doc_type]} uploaded.")
    return back


@bp.route("/documents/<int:doc_id>/file")
@login_required
def document_file(doc_id):
    doc = db.session.get(Document, doc_id) or abort(404)
    if not doc.file_path:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_DIR"], doc.file_path)

def _run_extraction(doc):
    """Extract one document and return a message for the user."""
    label = DOC_TYPES[doc.doc_type]
    path = os.path.join(current_app.config["UPLOAD_DIR"], doc.file_path)
    try:
        result = extract_document(path, doc.doc_type)
    except UnreadableDocument as e:
        doc.extraction_status = "manual"
        return f"{label} could not be read ({e}). It needs manual entry."
    except ExtractionError as e:
        doc.extraction_status = "failed"
        return f"{label}: {e}"
    apply_extraction(doc, result)
    doc.extraction_status = "done"
    return f"{label} extracted."


@bp.route("/documents/<int:doc_id>/extract", methods=["POST"])
@login_required
def extract_one(doc_id):
    doc = db.session.get(Document, doc_id) or abort(404)
    if not doc.file_path:
        flash("This seeded sample has no file to read.")
    else:
        flash(_run_extraction(doc))
        refresh_shipment(doc.shipment)
        db.session.commit()
    return redirect(url_for("main.shipment_detail", shipment_id=doc.shipment_id))


@bp.route("/shipments/<shipment_id>/extract", methods=["POST"])
@login_required
def extract_all(shipment_id):
    shipment = db.session.get(Shipment, shipment_id) or abort(404)
    todo = [d for d in shipment.documents
            if d.file_path and d.extraction_status in ("pending", "failed")]
    if not todo:
        flash("Nothing left to extract.")
    for doc in todo:
        flash(_run_extraction(doc))
    if todo:
        refresh_shipment(shipment)
        db.session.commit()
    return redirect(url_for("main.shipment_detail", shipment_id=shipment_id))