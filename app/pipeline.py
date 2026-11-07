"""Glue between extraction, cross-checks and the database."""
from decimal import Decimal, InvalidOperation

from .checks import FAIL, PASS, run_all_checks
from .config import CONFIDENCE_THRESHOLD
from .models import CrossCheck, Field, LineItem

DOC_ORDER = ("invoice", "packing_list", "bill_of_lading")
DOC_LABELS = {"invoice": "Invoice", "packing_list": "Packing list",
              "bill_of_lading": "Bill of lading"}

# Which stored field a cross-check rule puts in doubt
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


def _is_low(field):
    """True if the field is doubtful on its own (not just because of a failed check)."""
    return field.current_value is None or (
        field.ai_confidence is not None and field.ai_confidence < CONFIDENCE_THRESHOLD
    )


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
            packages=_int(item["packages"]), gross_weight_kg=_dec(item["gross_weight_kg"]),
        ))
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


def _status(shipment):
    docs = shipment.documents
    states = [d.extraction_status for d in docs]
    if any(s in ("failed", "manual") for s in states):
        return "needs_review"
    if "done" not in states:
        return "uploaded"
    if "pending" in states or len(docs) < 3:
        return "extracted"
    flagged = any(f.state == "needs_confirm" for d in docs for f in d.fields)
    return "needs_review" if flagged else "cleared"


def refresh_shipment(shipment):
    """Re-run all cross-checks, update field flags and the shipment status.

    - A failing check flags the fields it involves.
    - If the failure text changed since last time (someone edited a value), fields a person
      had already confirmed are flagged again. Fields a person typed ('edited') stay as they are.
    - A passing check removes flags that only existed because of that check.
    """
    previous = {c.rule: c.detail for c in shipment.cross_checks}
    shipment.cross_checks.clear()
    done = any(d.extraction_status == "done" for d in shipment.documents)
    results = run_all_checks(build_check_input(shipment)) if done else []

    for r in results:
        shipment.cross_checks.append(CrossCheck(rule=r.rule, status=r.status, detail=r.detail))
        name = RULE_FIELDS.get(r.rule)
        if name is None:
            continue
        changed = previous.get(r.rule) != r.detail
        for doc in shipment.documents:
            for f in doc.fields:
                if f.name != name:
                    continue
                if r.status == FAIL:
                    if f.state == "ok" or (changed and f.state == "confirmed"):
                        f.state = "needs_confirm"
                elif r.status == PASS and f.state == "needs_confirm" and not _is_low(f):
                    f.state = "ok"

    shipment.status = _status(shipment)


def export_blockers(shipment):
    """Plain-language reasons this shipment is not cleared yet. Empty list = nothing left."""
    reasons = []
    docs = {d.doc_type: d for d in shipment.documents}
    for key in DOC_ORDER:
        doc = docs.get(key)
        if doc is None:
            reasons.append(f"{DOC_LABELS[key]} not uploaded")
        elif doc.extraction_status != "done":
            reasons.append(f"{DOC_LABELS[key]} not extracted")
    flagged = sum(1 for d in docs.values() for f in d.fields if f.state == "needs_confirm")
    if flagged:
        reasons.append(f"{flagged} field{'' if flagged == 1 else 's'} to confirm")
    return reasons