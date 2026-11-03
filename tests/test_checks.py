from app.checks import (
    check_invoice_total, check_gross_weight, check_packages,
    check_qty_per_item, run_all_checks, PASS, FAIL, SKIPPED,
)

# Sample data from the brief
SHP_24811_INVOICE = [{"description": "LED panel light 40W", "qty": 2400, "unit_price": "6.80"}]
SHP_24811_PACKING = [{"description": "LED panel light 40W", "qty": 2400}]


def test_invoice_total_matches():
    # 2400 x 6.80 = 16320.00
    assert check_invoice_total(SHP_24811_INVOICE, "16320.00").status == PASS


def test_invoice_total_mismatch():
    result = check_invoice_total(SHP_24811_INVOICE, "16500.00")
    assert result.status == FAIL
    assert "16320" in result.detail


def test_invoice_total_decimal_precision():
    items = [{"description": "x", "qty": 3, "unit_price": "0.1"}]
    assert check_invoice_total(items, "0.30").status == PASS  # no float error


def test_invoice_total_skipped_when_missing():
    assert check_invoice_total([], "100").status == SKIPPED


def test_weight_mismatch_flags_shp_24811():
    # 3120 vs 3165 kg = 45 kg, about 1.4%
    result = check_gross_weight({"invoice": 3120, "packing_list": 3165}, "1")
    assert result.status == FAIL
    assert "45" in result.detail


def test_weight_passes_within_wider_tolerance():
    result = check_gross_weight({"invoice": 3120, "packing_list": 3165}, "2")
    assert result.status == PASS


def test_weight_skipped_with_one_document():
    assert check_gross_weight({"invoice": 3120}).status == SKIPPED


def test_packages_must_match_exactly():
    assert check_packages({"packing_list": 120, "bill_of_lading": 121}).status == FAIL
    assert check_packages({"packing_list": 120, "bill_of_lading": 120}).status == PASS


def test_qty_per_item_pass():
    assert check_qty_per_item(SHP_24811_INVOICE, SHP_24811_PACKING).status == PASS


def test_qty_per_item_mismatch_and_missing_item():
    pl = [{"description": "LED panel light 40W", "qty": 2300}]
    assert check_qty_per_item(SHP_24811_INVOICE, pl).status == FAIL
    other = [{"description": "Something else", "qty": 5}]
    assert check_qty_per_item(SHP_24811_INVOICE, other).status == FAIL


def test_shp_24811_end_to_end_fails_on_weight_only():
    shipment = {
        "invoice": {"line_items": SHP_24811_INVOICE, "total": "16320.00", "gross_weight": 3120},
        "packing_list": {"line_items": SHP_24811_PACKING, "gross_weight": 3165},
    }
    results = {r.rule: r.status for r in run_all_checks(shipment)}
    assert results["gross_weight"] == FAIL
    assert results["invoice_total"] == PASS
    assert results["qty_per_item"] == PASS