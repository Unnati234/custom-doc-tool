import pytest

from app import create_app
from app.models import db
from app.reports import accuracy_report
from tests.test_export import login_as
from tests.test_review import make_shipment


@pytest.fixture()
def app():
    return create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://"})


def test_corrected_field_lowers_accuracy(app):
    with app.app_context():
        s = make_shipment()
        inv = next(d for d in s.documents if d.doc_type == "invoice")
        next(f for f in inv.fields if f.name == "gross_weight_kg").current_value = "3165"
        db.session.commit()

        report = accuracy_report()
        weight = next(r for r in report["by_field"] if r["name"] == "gross weight kg")
        assert (weight["total"], weight["wrong"]) == (3, 1)
        assert report["by_supplier"][0]["name"] == "Supplier"


def test_report_is_manager_only(app):
    client = app.test_client()
    login_as(client, app, "executive")
    assert client.get("/reports/accuracy").status_code == 403


def test_manager_sees_the_report(app):
    client = app.test_client()
    with app.app_context():
        make_shipment()
    login_as(client, app, "manager")
    resp = client.get("/reports/accuracy")
    assert resp.status_code == 200 and b"By supplier" in resp.data