from decimal import Decimal

import pytest

from app import create_app
from app.models import Correction, Document, Field, LineItem, Shipment, User, db
from app.pipeline import apply_extraction, export_blockers, refresh_shipment


@pytest.fixture()
def app():
    return create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://"})


def _result(fields, items):
    return {"fields": [{"name": n, "value": v, "confidence": 0.95} for n, v in fields],
            "line_items": items}


def _item(qty="2400", price=None):
    return {"description": "LED panel light 40W", "hsn": None, "qty": qty, "unit_price": price,
            "packages": None, "gross_weight_kg": None, "confidence": 0.95}


def make_shipment():
    """SHP-T1: invoice 3120 kg vs packing list and bill of lading 3165 kg (the brief's case)."""
    s = Shipment(id="SHP-T1", importer_name="Importer", supplier_name="Supplier")
    db.session.add(s)
    data = {
        "invoice": _result([("invoice_no", "INV-1"), ("invoice_date", "2026-10-12"),
                            ("currency", "USD"), ("incoterm", "FOB"), ("total", "16320.00"),
                            ("gross_weight_kg", "3120")], [_item(price="6.80")]),
        "packing_list": _result([("gross_weight_kg", "3165"), ("packages", "120")], [_item()]),
        "bill_of_lading": _result([("gross_weight_kg", "3165"), ("packages", "120"),
                                   ("container_no", "TEST1234567")], []),
    }
    for doc_type, result in data.items():
        doc = Document(shipment=s, doc_type=doc_type, extraction_status="done")
        db.session.add(doc)
        apply_extraction(doc, result)
    refresh_shipment(s)
    db.session.commit()
    return s


def states(shipment):
    return {(d.doc_type, f.name): f.state for d in shipment.documents for f in d.fields}


def login(client, app):
    with app.app_context():
        user = User(email="e@test.test", name="Exec", role="executive")
        user.set_password("x")
        db.session.add(user)
        db.session.commit()
        uid = user.id
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_csrf"] = "tok"


def field_id(shipment, doc_type, name):
    return next(f.id for d in shipment.documents if d.doc_type == doc_type
                for f in d.fields if f.name == name)


def test_weight_mismatch_flags_involved_fields_and_blocks(app):
    with app.app_context():
        s = make_shipment()
        st = states(s)
        assert s.status == "needs_review"
        assert st[("invoice", "gross_weight_kg")] == "needs_confirm"
        assert st[("packing_list", "gross_weight_kg")] == "needs_confirm"
        assert st[("invoice", "total")] == "ok"
        assert export_blockers(s)


def test_confirming_every_flagged_field_clears_the_shipment(app):
    with app.app_context():
        s = make_shipment()
        for d in s.documents:
            for f in d.fields:
                if f.state == "needs_confirm":
                    f.state = "confirmed"
        refresh_shipment(s)
        assert s.status == "cleared"
        assert export_blockers(s) == []


def test_a_changed_mismatch_flags_confirmed_fields_again(app):
    with app.app_context():
        s = make_shipment()
        for d in s.documents:
            for f in d.fields:
                if f.state == "needs_confirm":
                    f.state = "confirmed"
        refresh_shipment(s)

        pl = next(d for d in s.documents if d.doc_type == "packing_list")
        weight = next(f for f in pl.fields if f.name == "gross_weight_kg")
        weight.current_value, weight.state = "3170", "edited"
        refresh_shipment(s)

        st = states(s)
        assert st[("invoice", "gross_weight_kg")] == "needs_confirm"
        assert st[("bill_of_lading", "gross_weight_kg")] == "needs_confirm"
        assert st[("packing_list", "gross_weight_kg")] == "edited"
        assert s.status == "needs_review"


def test_edit_route_logs_correction_and_fixes_the_check(app):
    client = app.test_client()
    with app.app_context():
        fid = field_id(make_shipment(), "invoice", "gross_weight_kg")
    login(client, app)

    resp = client.post(f"/fields/{fid}/save", data={"_csrf": "tok", "value": "3165"})
    assert resp.status_code == 302

    with app.app_context():
        f = db.session.get(Field, fid)
        assert (f.state, f.current_value, f.ai_value) == ("edited", "3165", "3120")
        rows = Correction.query.filter_by(field_id=fid).all()
        assert len(rows) == 1 and rows[0].old_value == "3120" and rows[0].new_value == "3165"
        s = db.session.get(Shipment, "SHP-T1")
        weight_check = next(c for c in s.cross_checks if c.rule == "gross_weight")
        assert weight_check.status == "pass"
        # flags that existed only because of the failed check are gone
        assert states(s)[("packing_list", "gross_weight_kg")] == "ok"


def test_invalid_value_is_rejected_and_nothing_changes(app):
    client = app.test_client()
    with app.app_context():
        fid = field_id(make_shipment(), "invoice", "gross_weight_kg")
    login(client, app)

    client.post(f"/fields/{fid}/save", data={"_csrf": "tok", "value": "abc"})

    with app.app_context():
        f = db.session.get(Field, fid)
        assert (f.current_value, f.state) == ("3120", "needs_confirm")
        assert Correction.query.count() == 0


def test_confirming_an_unchanged_value_logs_no_correction(app):
    client = app.test_client()
    with app.app_context():
        fid = field_id(make_shipment(), "invoice", "gross_weight_kg")
    login(client, app)

    client.post(f"/fields/{fid}/save", data={"_csrf": "tok", "value": "3120"})

    with app.app_context():
        assert db.session.get(Field, fid).state == "confirmed"
        assert Correction.query.count() == 0


def test_line_item_edit_is_logged_and_reruns_the_total_check(app):
    client = app.test_client()
    with app.app_context():
        s = make_shipment()
        inv = next(d for d in s.documents if d.doc_type == "invoice")
        item_id = inv.line_items[0].id
    login(client, app)

    client.post(f"/line-items/{item_id}/save", data={
        "_csrf": "tok", "description": "LED panel light 40W", "qty": "2500", "unit_price": "6.80"})

    with app.app_context():
        assert db.session.get(LineItem, item_id).qty == Decimal("2500")
        s = db.session.get(Shipment, "SHP-T1")
        total_check = next(c for c in s.cross_checks if c.rule == "invoice_total")
        assert total_check.status == "fail"
        assert Correction.query.count() == 1
        assert Correction.query.first().old_value.startswith("qty")


def test_review_requires_login(app):
    resp = app.test_client().get("/shipments/SHP-T1/review")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_review_page_renders_and_ignores_a_bogus_tab(app):
    client = app.test_client()
    with app.app_context():
        make_shipment()
    login(client, app)
    ok = client.get("/shipments/SHP-T1/review?doc=packing_list")
    assert ok.status_code == 200 and b"Gross weight" in ok.data
    assert client.get("/shipments/SHP-T1/review?doc=nonsense").status_code == 200