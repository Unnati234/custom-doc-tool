"""Accuracy report: how often the AI's value survived human review.

A header field counts as wrong when its final value differs from what the AI read.
A line item counts as wrong when a person edited it. Fields where the AI found nothing
and nobody added anything are skipped, since there is nothing to measure.
ASSUMPTION: seeded demo shipments are treated as if the AI had read them.
"""
from collections import defaultdict

from .models import Document, Field, Shipment, db


def _rows(buckets):
    out = []
    for name, (total, wrong) in buckets.items():
        out.append({"name": name, "total": total, "wrong": wrong,
                    "pct": round((total - wrong) / total * 100, 1)})
    return sorted(out, key=lambda r: (r["pct"], r["name"]))  # weakest first


def accuracy_report():
    rows = (db.session.query(Field, Document, Shipment)
            .join(Document, Field.document_id == Document.id)
            .join(Shipment, Document.shipment_id == Shipment.id)
            .filter(Document.extraction_status == "done")
            .all())

    by_field = defaultdict(lambda: [0, 0])
    by_supplier = defaultdict(lambda: [0, 0])
    for field, _doc, shipment in rows:
        if field.name == "line_item":
            wrong = bool(field.corrections)
        else:
            if field.ai_value is None and field.current_value is None:
                continue
            wrong = field.current_value != field.ai_value
        label = "line item" if field.name == "line_item" else field.name.replace("_", " ")
        for bucket, key in ((by_field, label), (by_supplier, shipment.supplier_name or "Unknown")):
            bucket[key][0] += 1
            bucket[key][1] += int(wrong)

    return {"by_field": _rows(by_field), "by_supplier": _rows(by_supplier)}