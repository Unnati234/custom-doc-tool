"""Generate synthetic sample documents. Run from the project root:
    python -m seed.make_samples
Needs reportlab (pip install reportlab). All data here is made up.
"""
import os

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = os.path.join(os.path.dirname(__file__), "samples")

DOCS = {
    # SHP-24811: the packing list weight (3,165) differs from the invoice (3,120)
    "SHP-24811_invoice.pdf": ("COMMERCIAL INVOICE", [
        "Invoice No: INV-B-0457", "Date: 12-Oct-2026",
        "Seller: Company B (China)", "Buyer: Importer A (demo)",
        "Currency: USD     Terms: FOB", "",
        "Description            Qty     Unit price     Amount",
        "LED panel light 40W    2400    6.80           16,320.00", "",
        "Total: USD 16,320.00", "Gross weight: 3,120 kg"]),
    "SHP-24811_packing_list.pdf": ("PACKING LIST", [
        "Ref: INV-B-0457", "Shipper: Company B (China)", "",
        "Description            Qty     Packages",
        "LED panel light 40W    2400    120", "",
        "Total packages: 120 cartons", "Gross weight: 3,165 kg"]),
    "SHP-24811_bill_of_lading.pdf": ("BILL OF LADING", [
        "B/L No: BL-TEST-0001", "Shipper: Company B (China)",
        "Consignee: Importer A (demo)", "Container: TEST1234567",
        "Packages: 120 cartons", "Gross weight: 3,165 kg",
        "Description: LED panel lights"]),
    # SHP-24812: everything agrees
    "SHP-24812_invoice.pdf": ("COMMERCIAL INVOICE", [
        "Invoice No: INV-C-2210", "Date: 15-Oct-2026",
        "Seller: Company C (Sweden)", "Buyer: Importer D (demo)",
        "Currency: EUR     Terms: CIF", "",
        "Description              Qty     Unit price     Amount",
        "Steel ball valve DN50    180     42.50          7,650.00", "",
        "Total: EUR 7,650.00", "Gross weight: 1,460 kg"]),
    "SHP-24812_packing_list.pdf": ("PACKING LIST", [
        "Ref: INV-C-2210", "Shipper: Company C (Sweden)", "",
        "Description              Qty     Packages",
        "Steel ball valve DN50    180     9", "",
        "Total packages: 9 crates", "Gross weight: 1,460 kg"]),
    "SHP-24812_bill_of_lading.pdf": ("BILL OF LADING", [
        "B/L No: BL-TEST-0002", "Shipper: Company C (Sweden)",
        "Consignee: Importer D (demo)", "Container: TEST7654321",
        "Packages: 9 crates", "Gross weight: 1,460 kg",
        "Description: Steel ball valves"]),
}


def write_pdf(path, title, lines):
    c = canvas.Canvas(path, pagesize=A4)
    _, height = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 60, title)
    c.setFont("Courier", 11)
    y = height - 100
    for line in lines:
        c.drawString(50, y, line)
        y -= 18
    c.save()


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, (title, lines) in DOCS.items():
        write_pdf(os.path.join(OUT, name), title, lines)
    print("Wrote", len(DOCS), "files to", OUT)
    