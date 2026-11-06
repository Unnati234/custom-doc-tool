"""Cross-checks between invoice, packing list and bill of lading.

Each rule is a pure function: plain data in, CheckResult out.
Money and weights use Decimal, never float.
"""
from dataclasses import dataclass
from decimal import Decimal

PASS, FAIL, SKIPPED = "pass", "fail", "skipped"


@dataclass
class CheckResult:
    rule: str
    status: str  # pass | fail | skipped
    detail: str


def _d(value):
    """Convert to Decimal via str, so 0.1 stays 0.1."""
    return None if value is None else Decimal(str(value))


def check_invoice_total(line_items, stated_total, tolerance_pct="0.5"):
    """Invoice total vs sum of qty x unit_price."""
    rule = "invoice_total"
    if not line_items or stated_total is None:
        return CheckResult(rule, SKIPPED, "Missing line items or stated total")
    if any(i.get("qty") is None or i.get("unit_price") is None for i in line_items):
        return CheckResult(rule, SKIPPED, "A line item is missing quantity or unit price")

    calculated = sum(_d(i["qty"]) * _d(i["unit_price"]) for i in line_items)
    stated = _d(stated_total)
    diff = abs(calculated - stated)
    allowed = max(Decimal("0.01"), abs(stated) * _d(tolerance_pct) / 100)

    if diff <= allowed:
        return CheckResult(rule, PASS, f"Line sum {calculated} matches total {stated}")
    return CheckResult(
        rule, FAIL, f"Line sum {calculated} vs stated total {stated} (diff {diff})"
    )


def _compare_across_documents(rule, label, values, tolerance_pct):
    """values: {'invoice': 3120, 'packing_list': 3165, 'bill_of_lading': None}"""
    present = {k: _d(v) for k, v in values.items() if v is not None}
    if len(present) < 2:
        return CheckResult(rule, SKIPPED, f"Need {label} in at least two documents")

    hi, lo = max(present.values()), min(present.values())
    spread_pct = (hi - lo) / hi * 100 if hi else Decimal(0)
    shown = ", ".join(f"{k} {v}" for k, v in present.items())

    if spread_pct <= _d(tolerance_pct):
        return CheckResult(rule, PASS, f"{label} consistent: {shown}")
    return CheckResult(
        rule, FAIL, f"{label} differs: {shown} (diff {hi - lo}, {spread_pct:.2f}%)"
    )


def check_gross_weight(weights, tolerance_pct="1"):
    return _compare_across_documents("gross_weight", "Gross weight", weights, tolerance_pct)


def check_packages(packages):
    # Package counts must match exactly
    return _compare_across_documents("packages", "Package count", packages, "0")


def _key(description):
    return " ".join(description.lower().split())


def check_qty_per_item(invoice_items, packing_items):
    """Match items by description; compare quantities."""
    rule = "qty_per_item"
    if not invoice_items or not packing_items:
        return CheckResult(rule, SKIPPED, "Need items in both invoice and packing list")
    if any(i.get("qty") is None for i in list(invoice_items) + list(packing_items)):
        return CheckResult(rule, SKIPPED, "A line item is missing a quantity")

    inv = {_key(i["description"]): _d(i["qty"]) for i in invoice_items}
    pl = {_key(i["description"]): _d(i["qty"]) for i in packing_items}

    problems = []
    for name in sorted(inv.keys() | pl.keys()):
        if name not in pl:
            problems.append(f"'{name}' on invoice only")
        elif name not in inv:
            problems.append(f"'{name}' on packing list only")
        elif inv[name] != pl[name]:
            problems.append(f"'{name}': invoice {inv[name]} vs packing list {pl[name]}")

    if problems:
        return CheckResult(rule, FAIL, "; ".join(problems))
    return CheckResult(rule, PASS, "All item quantities match")


def run_all_checks(shipment, tolerances=None):
    """shipment: dict with invoice/packing_list/bill_of_lading data. Returns a list of CheckResult."""
    tol = {"invoice_total": "0.5", "gross_weight": "1", **(tolerances or {})}
    inv = shipment.get("invoice", {})
    pl = shipment.get("packing_list", {})
    bl = shipment.get("bill_of_lading", {})

    return [
        check_invoice_total(inv.get("line_items"), inv.get("total"), tol["invoice_total"]),
        check_gross_weight(
            {
                "invoice": inv.get("gross_weight"),
                "packing_list": pl.get("gross_weight"),
                "bill_of_lading": bl.get("gross_weight"),
            },
            tol["gross_weight"],
        ),
        check_packages(
            {
                "invoice": inv.get("packages"),
                "packing_list": pl.get("packages"),
                "bill_of_lading": bl.get("packages"),
            }
        ),
        check_qty_per_item(inv.get("line_items"), pl.get("line_items")),
    ]