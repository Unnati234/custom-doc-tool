# DocCheck – AI-Powered Customs Document Verification

DocCheck is an AI-powered customs document processing system that uses Google Gemini Vision API to extract and cross-verify shipment information from invoices, packing lists, and bills of lading. It identifies inconsistencies, flags uncertain values for human review, and ensures manager approval before exporting verified data.

## Live Demo

- **Application:** https://custom-doc-tool.onrender.com
- **Repository:** https://github.com/Unnati234/custom-doc-tool

## Key Features

- **AI-Powered Extraction:** Extracts structured data from shipment documents using Gemini Vision API.
- **Automated Cross-Verification:** Checks invoice totals, gross weights, package counts, and item quantities.
- **Human-in-the-Loop Validation:** Flags uncertain or inconsistent fields for manual review and correction.
- **Role-Based Access:** Separate permissions for documentation executives and managers.
- **Correction Tracking:** Maintains correction history and field-level accuracy reports.
- **Controlled CSV Export:** Allows managers to approve and export shipment data only after flagged fields are reviewed.

## Tech Stack

- **Backend:** Python, Flask
- **AI Integration:** Google Gemini Vision API
- **Database:** SQLite, SQLAlchemy
- **Frontend:** HTML, CSS, JavaScript
- **Testing:** Pytest
- **Deployment:** Render

## Getting Started

For local installation, environment configuration, demo credentials, and deployment instructions, refer to the [Deployment Guide](deployment.md).

## Testing

Run the automated test suite using:

```bash
python -m pytest -q
```

## Important Note

This application uses synthetic demonstration data. The live demo runs on Render's free tier, so initial loading may take up to a minute and demo data resets when the application restarts. It is not intended for real or confidential customs documents in its current deployment.

---

**Built with Python, Flask, and Google Gemini AI.**
