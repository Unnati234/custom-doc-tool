"""CSV export of a cleared shipment.

ASSUMPTION: the brief does not give the filing software's import layout, so these columns
are my own, one row per invoice line item. Shipment-level values are read from the
documents in a fixed order, and what is exported is the current (confirmed or edited) value.
"""
import csv
import io
from decimal import Decimal, InvalidOperation

COLUMNS = [
    "shipment_id", "importer", "supplier", "invoice_no", "invoice_date", "currency",
    "incoterm", "container_no", "invoice_total", "packages", "gross_weight_kg",
    "line_no", "description", "hsn", "qty", "unit_price", "line_amount",
]

# Which document is trusted first for each shipment-level value (assumption)
SOURCE_ORDER = {
    "packages": ("packing_list", "bill_of_lading", "invoice"),
    "gross_weight_kg": ("packing_list", "bill_of_lading", "invoice"),
    "container_no": ("bill_of_lading",),
}
DEFAULT_ORDER = ("invoice", "packing_list", "bill_of_lading")


def _safe(value):
    """Stop spreadsheet formulas: a cell starting with = + - @ would be run by Excel."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _plain(value):
    """2400.000 -> '2400', 6.8000 -> '6.8', None -> ''."""
    if value is None:
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except InvalidOperation:
        return str(value)


def _value(shipment, name):
    docs = {d.doc_type: d for d in shipment.documents}
    for key in SOURCE_ORDER.get(name, DEFAULT_ORDER):
        doc = docs.get(key)
        if doc is None:
            continue
        for f in doc.fields:
            if f.name == name and f.line_no is None and f.current_value:
                return f.current_value
    return None


def build_csv(shipment):
    head = {
        "shipment_id": shipment.id,
        "importer": shipment.importer_name,
        "supplier": shipment.supplier_name,
    }
    for name in ("invoice_no", "invoice_date", "currency", "incoterm", "container_no",
                 "packages", "gross_weight_kg"):
        head[name] = _value(shipment, name)
    head["invoice_total"] = _value(shipment, "total")

    invoice = next((d for d in shipment.documents if d.doc_type == "invoice"), None)
    items = sorted(invoice.line_items, key=lambda i: i.line_no or 0) if invoice else []

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    for item in items or [None]:
        row = dict(head)
        if item is not None:
            amount = None
            if item.qty is not None and item.unit_price is not None:
                amount = Decimal(str(item.qty)) * Decimal(str(item.unit_price))
            row.update({
                "line_no": item.line_no, "description": item.description, "hsn": item.hsn,
                "qty": _plain(item.qty), "unit_price": _plain(item.unit_price),
                "line_amount": _plain(amount),
            })
        writer.writerow([_safe(row.get(col)) for col in COLUMNS])
    return out.getvalue()