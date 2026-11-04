import os
import secrets

from flask import current_app

# Allowed extension -> the bytes a real file of that type starts with
ALLOWED = {
    ".pdf": b"%PDF",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
}


def save_upload(file, shipment_id, doc_type):
    """Validate and store an uploaded file. Returns its path relative to UPLOAD_DIR."""
    if not file or not file.filename:
        raise ValueError("Choose a file to upload.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED:
        raise ValueError("Only PDF, PNG or JPG files are accepted.")

    head = file.stream.read(8)
    file.stream.seek(0)
    if not head.startswith(ALLOWED[ext]):
        raise ValueError("The file content does not match its type.")

    # We generate the name ourselves, so the user's filename never touches the disk
    rel = f"{shipment_id}/{doc_type}_{secrets.token_hex(6)}{ext}"
    full = os.path.join(current_app.config["UPLOAD_DIR"], rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    file.save(full)
    return rel


def delete_upload(rel):
    if not rel:
        return
    base = os.path.abspath(current_app.config["UPLOAD_DIR"])
    full = os.path.abspath(os.path.join(base, rel))
    if full.startswith(base + os.sep) and os.path.exists(full):
        os.remove(full)