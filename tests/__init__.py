import csv
import io

import pytest

from app import create_app
from app.export import build_csv
from app.models import Shipment, User, db
from app.pipeline import refresh_shipment
from tests.test_review import make_shipment


@pytest.fixture()
def app():
    return create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://"})


def login_as(client, app, role):
    with app.app_context():
        user = User(email=f"{role}@test.test", name=role, role=role)
        user.set_password("x")
        db.session.add(user)
        db.session.commit()
        uid = user.id
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["_csrf"] = "tok"


def clear(shipment):
    for d in shipment.documents:
        for f in d.fields:
            if f.state == "needs_confirm":
                f.state = "confirmed"
    refresh_shipment(shipment)


def test_csv_has_one_row_per_line_item(app):
    with app.app_context():
        s = make_shipment()
        rows = list(csv.DictReader(io.StringIO(build_csv(s))))
        assert len(rows) == 1
        r = rows[0]
        assert r["shipment_id"] == "SHP-T1"
        assert r["invoice_no"] == "INV-1"
        assert r["qty"] == "2400" and r["unit_price"] == "6.8"
        assert r["line_amount"] == "16320"
        assert r["packages"] == "120" and r["gross_weight_kg"] == "3165"
        assert r["container_no"] == "TEST1234567"


def test_csv_neutralises_formula_cells(app):
    with app.app_context():
        s = make_shipment()
        inv = next(d for d in s.documents if d.doc_type == "invoice")
        inv.line_items[0].description = '=HYPERLINK("http://example.test")'
        db.session.commit()
        rows = list(csv.DictReader(io.StringIO(build_csv(s))))
        assert rows[0]["description"].startswith("'=")


def test_export_is_blocked_until_everything_is_confirmed(app):
    client = app.test_client()
    with app.app_context():
        make_shipment()
    login_as(client, app, "manager")

    resp = client.post("/shipments/SHP-T1/export", data={"_csrf": "tok"})

    assert resp.status_code == 302 and resp.mimetype != "text/csv"
    with app.app_context():
        assert db.session.get(Shipment, "SHP-T1").status == "needs_review"


def test_executive_cannot_export(app):
    client = app.test_client()
    with app.app_context():
        clear(make_shipment())
        db.session.commit()
    login_as(client, app, "executive")

    assert client.post("/shipments/SHP-T1/export", data={"_csrf": "tok"}).status_code == 403


def test_manager_exports_a_cleared_shipment(app):
    client = app.test_client()
    with app.app_context():
        clear(make_shipment())
        db.session.commit()
    login_as(client, app, "manager")

    resp = client.post("/shipments/SHP-T1/export", data={"_csrf": "tok"})

    assert resp.status_code == 200 and resp.mimetype == "text/csv"
    assert b"SHP-T1" in resp.data
    with app.app_context():
        s = db.session.get(Shipment, "SHP-T1")
        assert s.status == "exported" and s.exported_by is not None