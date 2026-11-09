# Deployment guide

- **Live app:** https://custom-doc-tool.onrender.com
- **Repository:** https://github.com/Unnati234/custom-doc-tool

## Demo login (live app)

| Role | Email | Password |
|---|---|---|
| Manager (approve, export, accuracy report) | manager@demo.test | custom_doc_tool@123 |
| Documentation executive (review, confirm, edit) | executive@demo.test | custom_doc_tool@123 |

These are demo accounts with synthetic data only.

### Things to know when trying the live app

- **First load can take up to a minute.** The free host puts the app to sleep when idle.
- **Data resets on every restart.** The demo users and three sample shipments are re-created at startup, and uploaded files are not kept (free tier, no persistent disk).
- **The seeded shipments (SHP-24811 to 24813) have no document files.** To see the full flow, click **New shipment** and upload the three PDFs from `seed/samples/` in the repository (for example `SHP-24811_invoice.pdf`, `SHP-24811_packing_list.pdf`, `SHP-24811_bill_of_lading.pdf`), then click **Extract all**.
- **Expected result for SHP-24811:** the gross weight cross-check fails (invoice 3120 kg vs packing list and bill of lading 3165 kg), and export stays blocked until a person confirms the flagged fields.
- **If extraction says "the AI service is busy",** wait a minute and click **Extract all** again. This comes from the free AI tier and is temporary. Documents that already extracted are not repeated.

## Run locally

Requires Python 3.12 and Git.

```
git clone https://github.com/Unnati234/custom-doc-tool.git
cd custom-doc-tool
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
```

Create a file named `.env` in the project root (see `.env.example`):

```
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash
```

Then create the demo data and start the server:

```
python -m seed.seed
flask --app app run --debug
```

Open http://127.0.0.1:5000. Locally the demo password is `demo-pass-123` unless `DEMO_PASSWORD` is set.

Without a Gemini key the app still runs and the seeded data works. Extraction then shows a clear "not configured" message and the document goes to retry or manual entry.

Run the tests (none of them calls the real AI service):

```
python -m pytest -q
```

## How it is deployed

Hosted on Render (free web service, Singapore region), built from the `main` branch.

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `python -m seed.seed && gunicorn "app:create_app()" --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 300`

The start command re-seeds the database each time. A single worker is used because the database is a SQLite file on the instance, and the long timeout allows for slow AI extraction.

## Environment variables (names only)

| Name | Purpose |
|---|---|
| `GEMINI_API_KEY` | Key for the Gemini vision API |
| `GEMINI_MODEL` | Primary model used for extraction |
| `GEMINI_FALLBACK_MODEL` | Used if the primary model is overloaded |
| `SECRET_KEY` | Signs login sessions |
| `DEMO_PASSWORD` | Password given to the seeded demo users |
| `COOKIE_SECURE` | Set to `1` so the session cookie is HTTPS-only |
| `PYTHON_VERSION` | Python version for the host |
| `DATABASE_URL` | Optional. Defaults to a local SQLite file |
| `UPLOAD_DIR` | Optional. Defaults to `uploads/` in the project |

No secrets are stored in the repository.