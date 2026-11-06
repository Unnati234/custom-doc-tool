"""Glue between extraction, cross-checks and the database."""
from decimal import Decimal, InvalidOperation

from .checks import FAIL, PASS, run_all_checks
from .config import CONFIDENCE_THRESHOLD
from .models import CrossCheck, Field, LineItem

# Which stored field a failed rule puts in doubt
RULE_FIELDS = {
    "gross_weight": "gross_weight_kg",
    "packages": "packages",
    "invoice_total": "total",
    "qty_per_item": "line_item",
}


def _dec(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None

def _int(value):
    """Whole number or None (package counts are integers)."""
    d = _dec(value)
    if d is None or d != d.to_integral_value():
        return None
    return int(d)

def apply_extraction(doc, result):
    """Replace a document's fields and line items with a fresh extraction."""
    doc.fields.clear()
    doc.line_items.clear()

    for f in result["fields"]:
        low = f["value"] is None or f["confidence"] < CONFIDENCE_THRESHOLD
        doc.fields.append(Field(
            name=f["name"], ai_value=f["value"], current_value=f["value"],
            ai_confidence=f["confidence"], state="needs_confirm" if low else "ok",
        ))

    for n, item in enumerate(result["line_items"], start=1):
        doc.line_items.append(LineItem(
            line_no=n, description=item["description"], hsn=item["hsn"],
            qty=_dec(item["qty"]), unit_price=_dec(item["unit_price"]),
            packages=_int(item["packages"]), gross_weight_kg=_dec(item["gross_weight_kg"]),        ))
        # Each line item also gets a field row, so low confidence is flagged the same way
        doc.fields.append(Field(
            name="line_item", line_no=n, ai_value=item["description"],
            current_value=item["description"], ai_confidence=item["confidence"],
            state="needs_confirm" if item["confidence"] < CONFIDENCE_THRESHOLD else "ok",
        ))


def build_check_input(shipment):
    """Read the current (possibly edited) values into the shape checks.py expects."""
    out = {}
    for doc in shipment.documents:
        if doc.extraction_status != "done":
            continue
        vals = {f.name: f.current_value for f in doc.fields if f.line_no is None}
        out[doc.doc_type] = {
            "line_items": [
                {"description": li.description or "", "qty": li.qty, "unit_price": li.unit_price}
                for li in doc.line_items
            ],
            "total": _dec(vals.get("total")),
            "gross_weight": _dec(vals.get("gross_weight_kg")),
            "packages": _dec(vals.get("packages")),
        }
    return out


def _status(shipment, results):
    docs = shipment.documents
    states = [d.extraction_status for d in docs]
    if any(s in ("failed", "manual") for s in states):
        return "needs_review"
    if "done" not in states:
        return "uploaded"
    if "pending" in states or len(docs) < 3:
        return "extracted"
    flagged = any(f.state == "needs_confirm" for d in docs for f in d.fields)
    if flagged or any(r.status != PASS for r in results):
        return "needs_review"
    return "cleared"


def refresh_shipment(shipment):
    """Re-run all cross-checks, flag fields in failed checks, update the status."""
    shipment.cross_checks.clear()
    done = any(d.extraction_status == "done" for d in shipment.documents)
    results = run_all_checks(build_check_input(shipment)) if done else []

    for r in results:
        shipment.cross_checks.append(CrossCheck(rule=r.rule, status=r.status, detail=r.detail))
        if r.status == FAIL:
            name = RULE_FIELDS.get(r.rule)
            for doc in shipment.documents:
                for f in doc.fields:
                    if f.name == name and f.state == "ok":
                        f.state = "needs_confirm"

    shipment.status = _status(shipment, results)