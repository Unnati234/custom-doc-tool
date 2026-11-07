import os
from decimal import Decimal
from ..reports import accuracy_report
from ..config import CONFIDENCE_THRESHOLD
from ..extraction import EXPECTED_FIELDS, clean_decimal, clean_value
from ..models import Correction, Field, LineItem
from ..extraction import ExtractionError, UnreadableDocument, extract_document
from ..pipeline import apply_extraction, refresh_shipment, export_blockers
from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, send_from_directory, session, url_for, current_app, Response, g)

from ..auth import check_csrf, csrf_token, current_user, login_required, role_required
from ..models import CrossCheck, Document, Shipment, User, db, now
from ..uploads import delete_upload, save_upload
from ..export import build_csv

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
                           docs=docs, DOC_TYPES=DOC_TYPES,
                           blockers=export_blockers(shipment))      

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

# ---------------------------------------------------------------- review screen

def _review_url(doc, anchor=None):
    return url_for("main.review", shipment_id=doc.shipment_id, doc=doc.doc_type, _anchor=anchor)


@bp.route("/shipments/<shipment_id>/review")
@login_required
def review(shipment_id):
    shipment = db.session.get(Shipment, shipment_id) or abort(404)
    docs = {d.doc_type: d for d in shipment.documents}
    if not docs:
        flash("Upload the documents first.")
        return redirect(url_for("main.shipment_detail", shipment_id=shipment_id))

    doc = docs.get(request.args.get("doc")) or next(docs[k] for k in DOC_TYPES if k in docs)
    attention = {k: sum(1 for f in d.fields if f.state == "needs_confirm") for k, d in docs.items()}
    fields = sorted((f for f in doc.fields if f.line_no is None), key=lambda f: f.id)
    line_fields = {f.line_no: f for f in doc.fields if f.line_no is not None}
    items = [(li, line_fields.get(li.line_no))
             for li in sorted(doc.line_items, key=lambda x: x.line_no or 0)]
    return render_template(
        "review.html", shipment=shipment, docs=docs, doc=doc, DOC_TYPES=DOC_TYPES,
        attention=attention, fields=fields, items=items, checks=shipment.cross_checks,
        blockers=export_blockers(shipment), threshold=CONFIDENCE_THRESHOLD,
    )


@bp.route("/fields/<int:field_id>/save", methods=["POST"])
@login_required
def save_field(field_id):
    """One endpoint for both actions: unchanged value = confirm, changed value = edit."""
    field = db.session.get(Field, field_id) or abort(404)
    if field.line_no is not None:
        abort(404)
    doc = field.document
    back = redirect(_review_url(doc, f"row-{field.id}"))

    raw = request.form.get("value", "").strip()
    cleaned = clean_value(field.name, raw)
    if cleaned is None:
        label = field.name.replace("_", " ")
        flash(f"'{raw[:40]}' is not a valid {label}." if raw else "Enter a value first.")
        return back

    if cleaned == field.current_value:
        if field.state != "edited":
            field.state = "confirmed"
    else:
        db.session.add(Correction(field_id=field.id, old_value=field.current_value,
                                  new_value=cleaned, user_id=current_user().id))
        field.current_value = cleaned
        field.state = "edited"

    refresh_shipment(doc.shipment)
    db.session.commit()
    return back


@bp.route("/line-items/<int:item_id>/save", methods=["POST"])
@login_required
def save_line_item(item_id):
    item = db.session.get(LineItem, item_id) or abort(404)
    doc = item.document
    back = redirect(_review_url(doc, f"row-item-{item.id}"))

    description = request.form.get("description", "").strip()[:255]
    if not description:
        flash("A line item needs a description.")
        return back

    new_values = {}
    for col in ("qty", "unit_price"):
        raw = request.form.get(col, "").strip()
        if not raw:
            new_values[col] = None
            continue
        cleaned = clean_decimal(raw)
        if cleaned is None:
            flash(f"'{raw[:40]}' is not a valid {col.replace('_', ' ')}.")
            return back
        new_values[col] = Decimal(cleaned)

    changes = []
    if description != (item.description or ""):
        changes.append(("description", item.description, description))
    for col, new in new_values.items():
        old = getattr(item, col)
        same = (old is None and new is None) or (
            old is not None and new is not None and Decimal(str(old)) == new)
        if not same:
            changes.append((col, old, new))

    field = Field.query.filter_by(document_id=doc.id, name="line_item", line_no=item.line_no).first()
    if field is None:  # seeded samples have no field row yet
        field = Field(document_id=doc.id, name="line_item", line_no=item.line_no,
                      ai_value=item.description, current_value=item.description, state="ok")
        db.session.add(field)
        db.session.flush()

    for col, old, new in changes:
        db.session.add(Correction(
            field_id=field.id,
            old_value=f"{col}: {'' if old is None else old}",
            new_value=f"{col}: {'' if new is None else new}",
            user_id=current_user().id,
        ))
        setattr(item, col, new)

    if changes:
        field.current_value = item.description
        field.state = "edited"
    elif field.state != "edited":
        field.state = "confirmed"

    refresh_shipment(doc.shipment)
    db.session.commit()
    return back


@bp.route("/documents/<int:doc_id>/manual", methods=["POST"])
@login_required
def manual_entry(doc_id):
    """Unreadable or failed document: create blank fields a person fills in."""
    doc = db.session.get(Document, doc_id) or abort(404)
    back = redirect(_review_url(doc))
    if doc.extraction_status not in ("manual", "failed") or doc.fields:
        flash("This document already has data.")
        return back
    for name in EXPECTED_FIELDS[doc.doc_type]:
        doc.fields.append(Field(name=name, ai_value=None, ai_confidence=0.0,
                                current_value=None, state="needs_confirm"))
    doc.extraction_status = "done"
    refresh_shipment(doc.shipment)
    db.session.commit()
    return back

@bp.route("/shipments/<shipment_id>/export", methods=["POST"])
@role_required("manager")
def export_shipment(shipment_id):
    shipment = db.session.get(Shipment, shipment_id) or abort(404)
    blockers = export_blockers(shipment)
    if blockers:  # the server decides, not the disabled button
        flash("Cannot export yet: " + "; ".join(blockers) + ".")
        return redirect(url_for("main.shipment_detail", shipment_id=shipment_id))

    data = build_csv(shipment)
    shipment.status = "exported"
    shipment.exported_by = g.user.id
    shipment.exported_at = now()
    db.session.commit()
    return Response(data, mimetype="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{shipment.id}.csv"'})
    
@bp.route("/reports/accuracy")
@role_required("manager")
def accuracy():
    return render_template("accuracy.html", **accuracy_report())    