import json

import pytest

from app import extraction
from app.extraction import ExtractionError, UnreadableDocument, parse_and_validate


def payload(fields, line_items=None, readable=True, reason=None):
    return json.dumps({"readable": readable, "unreadable_reason": reason,
                       "fields": fields, "line_items": line_items or []})


def f(name, value, conf=0.95):
    return {"name": name, "value": value, "confidence": conf}


PACKING = [f("gross_weight_kg", "3165"), f("packages", "120")]


def by_name(result):
    return {x["name"]: x for x in result["fields"]}


def test_valid_packing_list():
    r = by_name(parse_and_validate(payload(PACKING), "packing_list"))
    assert r["gross_weight_kg"]["value"] == "3165"
    assert r["packages"]["confidence"] == 0.95


def test_thousands_separator_is_normalised():
    r = by_name(parse_and_validate(payload([f("gross_weight_kg", "3,165"), f("packages", "120")]),
                                   "packing_list"))
    assert r["gross_weight_kg"]["value"] == "3165"


def test_invalid_number_is_kept_but_confidence_zeroed():
    r = by_name(parse_and_validate(payload([f("gross_weight_kg", "about 3000"), f("packages", "120")]),
                                   "packing_list"))
    assert r["gross_weight_kg"]["value"] == "about 3000"
    assert r["gross_weight_kg"]["confidence"] == 0.0


def test_fractional_package_count_is_rejected():
    r = by_name(parse_and_validate(payload([f("gross_weight_kg", "10"), f("packages", "12.5")]),
                                   "packing_list"))
    assert r["packages"]["confidence"] == 0.0


def test_confidence_is_clamped_and_junk_becomes_zero():
    fields = [f("gross_weight_kg", "10", 1.7), f("packages", "2", "high")]
    r = by_name(parse_and_validate(payload(fields), "packing_list"))
    assert r["gross_weight_kg"]["confidence"] == 1.0
    assert r["packages"]["confidence"] == 0.0


def test_missing_expected_field_is_added_as_not_found():
    r = by_name(parse_and_validate(payload([f("gross_weight_kg", "10")]), "packing_list"))
    assert r["packages"]["value"] is None
    assert r["packages"]["confidence"] == 0.0


def test_unknown_field_names_are_ignored():
    r = parse_and_validate(payload(PACKING + [f("bank_account", "123")]), "packing_list")
    assert "bank_account" not in by_name(r)


def test_invoice_date_must_be_iso():
    fields = [f("invoice_no", "A1"), f("invoice_date", "12/10/2026"), f("currency", "usd"),
              f("incoterm", "fob"), f("total", "10"), f("gross_weight_kg", "5")]
    r = by_name(parse_and_validate(payload(fields), "invoice"))
    assert r["invoice_date"]["confidence"] == 0.0   # ambiguous dd/mm vs mm/dd
    assert r["currency"]["value"] == "USD"
    assert r["incoterm"]["value"] == "FOB"


def test_container_number_is_normalised_and_checked():
    ok = by_name(parse_and_validate(payload(PACKING + [f("container_no", "test 1234567")]),
                                    "bill_of_lading"))
    bad = by_name(parse_and_validate(payload(PACKING + [f("container_no", "12345")]),
                                     "bill_of_lading"))
    assert ok["container_no"]["value"] == "TEST1234567"
    assert bad["container_no"]["confidence"] == 0.0


def test_line_item_with_bad_quantity_gets_zero_confidence():
    items = [{"description": "LED", "hsn": None, "qty": "lots", "unit_price": "6.80",
              "packages": None, "gross_weight_kg": None, "confidence": 0.9}]
    r = parse_and_validate(payload(PACKING, items), "packing_list")
    assert r["line_items"][0]["confidence"] == 0.0
    assert r["line_items"][0]["qty"] is None


def test_garbage_answer_raises_extraction_error():
    with pytest.raises(ExtractionError):
        parse_and_validate("not json at all", "packing_list")
    with pytest.raises(ExtractionError):
        parse_and_validate(None, "packing_list")


def test_unreadable_flag_raises_unreadable_document():
    with pytest.raises(UnreadableDocument):
        parse_and_validate(payload([], readable=False, reason="too blurry"), "packing_list")


def test_nothing_found_is_treated_as_unreadable():
    with pytest.raises(UnreadableDocument):
        parse_and_validate(payload([f("gross_weight_kg", None, 0), f("packages", None, 0)]),
                           "packing_list")


def test_extract_document_uses_the_model_answer(tmp_path, monkeypatch):
    path = tmp_path / "pl.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(extraction, "_call_model", lambda data, mime, doc_type: payload(PACKING))
    r = extraction.extract_document(str(path), "packing_list")
    assert by_name(r)["packages"]["value"] == "120"


def test_missing_api_key_gives_a_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ExtractionError):
        extraction._call_model(b"x", "application/pdf", "invoice")
        
        
def test_package_count_with_unit_word_is_accepted():
    r = by_name(parse_and_validate(
        payload([f("gross_weight_kg", "10"), f("packages", "9 crates")]), "packing_list"))
    assert r["packages"]["value"] == "9"
    assert r["packages"]["confidence"] == 0.95