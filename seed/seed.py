"""Seed the database with synthetic demo data.

Run from the project root:  python -m seed.seed
Everything here is made up. No real people, companies or prices.
"""
import os
from decimal import Decimal

from app import create_app
from app.checks import FAIL, SKIPPED, run_all_checks
from app.config import CONFIDENCE_THRESHOLD
from app.models import CrossCheck, Document, Field, LineItem, Shipment, User, db

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo-pass-123")

# Which fields each cross-check rule puts in doubt
RULE_FIELDS = {
    "gross_weight": "gross_weight_kg",
    "packages": "packages",
    "invoice_total": "total",
}

# Sample rows come from the brief. Values marked (assumed) are invented
# to complete the three-document set and are labelled in the TDD.
SHIPMENTS = [
    {
        "id": "SHP-24811",
        "importer": "Importer A (demo)",
        "supplier": "Company B (China)",
        "documents": {
            "invoice": {
                "fields": [
                    ("invoice_no", "INV-B-0457", 0.97),
                    ("invoice_date", "2026-10-12", 0.62),  # low confidence on purpose
                    ("currency", "USD", 0.99),
                    ("incoterm", "FOB", 0.93),
                    ("total", "16320.00", 0.95),
                    ("gross_weight_kg", "3120", 0.96),
                ],
                "line_items": [
                    {"description": "LED panel light 40W", "hsn": "94054090",
                     "qty": 2400, "unit_price": "6.80"},
                ],
            },
            "packing_list": {
                "fields": [
                    ("gross_weight_kg", "3165", 0.94),
                    ("packages", "120", 0.91),  # (assumed)
                ],
                "line_items": [
                    {"description": "LED panel light 40W", "qty": 2400},
                ],
            },
            "bill_of_lading": {
                "fields": [
                    ("gross_weight_kg", "3165", 0.90),  # (assumed)
                    ("packages", "120", 0.92),  # (assumed)
                    ("container_no", "TEST1234567", 0.88),  # fake number
                ],
                "line_items": [],
            },
        },
    },
    {
        "id": "SHP-24812",
        "importer": "Importer D (demo)",
        "supplier": "Company C (Sweden)",
        "documents": {
            "invoice": {
                "fields": [
                    ("invoice_no", "INV-C-2210", 0.98),
                    ("invoice_date", "2026-10-15", 0.97),
                    ("currency", "EUR", 0.99),
                    ("incoterm", "CIF", 0.95),  # (assumed)
                    ("total", "7650.00", 0.96),  # 180 x 42.50
                    ("gross_weight_kg", "1460", 0.97),
                ],
                "line_items": [
                    {"description": "Steel ball valve DN50", "hsn": "84818030",
                     "qty": 180, "unit_price": "42.50"},
                ],
            },
            "packing_list": {
                "fields": [
                    ("gross_weight_kg", "1460", 0.95),  # (assumed)
                    ("packages", "9", 0.93),  # (assumed)
                ],
                "line_items": [
                    {"description": "Steel ball valve DN50", "qty": 180},
                ],
            },
            "bill_of_lading": {
                "fields": [
                    ("gross_weight_kg", "1460", 0.94),  # (assumed)
                    ("packages", "9", 0.94),  # (assumed)
                    ("container_no", "TEST7654321", 0.90),  # fake number
                ],
                "line_items": [],
            },
        },
    },
    # Just uploaded, nothing extracted yet. Shows the early pipeline state.
    {
        "id": "SHP-24813",
        "importer": "Importer A (demo)",
        "supplier": "Company B (China)",
        "documents": {},
    },
]


def _num(value):
    return None if value is None else Decimal(str(value))


def _to_check_input(shipment_data):
    """Build the dict that checks.run_all_checks expects."""
    out = {}
    for doc_type, doc in shipment_data["documents"].items():
        fields = {name: value for name, value, _ in doc["fields"]}
        out[doc_type] = {
            "line_items": doc["line_items"],
            "total": fields.get("total"),
            "gross_weight": fields.get("gross_weight_kg"),
            "packages": fields.get("packages"),
        }
    return out


def seed():
    db.drop_all()
    db.create_all()

    executive = User(email="executive@demo.test", name="Demo Executive", role="executive")
    manager = User(email="manager@demo.test", name="Demo Manager", role="manager")
    for user in (executive, manager):
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
    db.session.flush()

    for data in SHIPMENTS:
        shipment = Shipment(
            id=data["id"],
            importer_name=data["importer"],
            supplier_name=data["supplier"],
            status="uploaded",
            created_by=executive.id,
        )
        db.session.add(shipment)

        for doc_type, doc_data in data["documents"].items():
            doc = Document(shipment=shipment, doc_type=doc_type, extraction_status="done")
            db.session.add(doc)
            for name, value, confidence in doc_data["fields"]:
                state = "needs_confirm" if confidence < CONFIDENCE_THRESHOLD else "ok"
                doc.fields.append(Field(
                    name=name, ai_value=value, current_value=value,
                    ai_confidence=confidence, state=state,
                ))
            for n, item in enumerate(doc_data["line_items"], start=1):
                doc.line_items.append(LineItem(
                    line_no=n,
                    description=item["description"],
                    hsn=item.get("hsn"),
                    qty=_num(item["qty"]),
                    unit_price=_num(item.get("unit_price")),
                ))

        if data["documents"]:
            results = run_all_checks(_to_check_input(data))
            for r in results:
                db.session.add(CrossCheck(
                    shipment=shipment, rule=r.rule, status=r.status, detail=r.detail,
                ))
                # Fields in a failed check must be confirmed by a person
                if r.status == FAIL and r.rule in RULE_FIELDS:
                    for doc in shipment.documents:
                        for f in doc.fields:
                            if f.name == RULE_FIELDS[r.rule] and f.state == "ok":
                                f.state = "needs_confirm"

            needs_review = any(
                f.state == "needs_confirm" for d in shipment.documents for f in d.fields
            ) or any(r.status == FAIL for r in results)
            shipment.status = "needs_review" if needs_review else "cleared"

    db.session.commit()
    print("Seeded:", User.query.count(), "users,", Shipment.query.count(), "shipments")


if __name__ == "__main__":
    with create_app().app_context():
        seed()