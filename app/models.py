from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'executive' | 'manager'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Shipment(db.Model):
    __tablename__ = "shipments"

    id = db.Column(db.String(20), primary_key=True)  # e.g. 'SHP-24811'
    importer_name = db.Column(db.String(120))
    supplier_name = db.Column(db.String(120))
    # uploaded | extracted | needs_review | cleared | exported
    status = db.Column(db.String(20), default="uploaded", nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=now)

    documents = db.relationship("Document", backref="shipment", cascade="all, delete-orphan")
    cross_checks = db.relationship("CrossCheck", backref="shipment", cascade="all, delete-orphan")


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.String(20), db.ForeignKey("shipments.id"), nullable=False)
    doc_type = db.Column(db.String(20), nullable=False)  # invoice | packing_list | bill_of_lading
    file_path = db.Column(db.String(255))
    # pending | done | failed | manual
    extraction_status = db.Column(db.String(20), default="pending", nullable=False)
    uploaded_at = db.Column(db.DateTime, default=now)

    fields = db.relationship("Field", backref="document", cascade="all, delete-orphan")
    line_items = db.relationship("LineItem", backref="document", cascade="all, delete-orphan")


class Field(db.Model):
    """One extracted value. ai_value is never overwritten."""
    __tablename__ = "fields"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False)
    name = db.Column(db.String(50), nullable=False)  # 'invoice_no', 'gross_weight_kg', ...
    line_no = db.Column(db.Integer)  # set for line-item fields
    ai_value = db.Column(db.String(255))
    ai_confidence = db.Column(db.Float)
    current_value = db.Column(db.String(255))
    # ok | needs_confirm | confirmed | edited
    state = db.Column(db.String(20), default="ok", nullable=False)

    corrections = db.relationship("Correction", backref="field", cascade="all, delete-orphan")


class LineItem(db.Model):
    __tablename__ = "line_items"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False)
    line_no = db.Column(db.Integer)
    description = db.Column(db.String(255))
    hsn = db.Column(db.String(20))
    qty = db.Column(db.Numeric(14, 3))
    unit_price = db.Column(db.Numeric(14, 4))
    packages = db.Column(db.Integer)
    gross_weight_kg = db.Column(db.Numeric(14, 3))
    net_weight_kg = db.Column(db.Numeric(14, 3))
    container_no = db.Column(db.String(20))


class CrossCheck(db.Model):
    __tablename__ = "cross_checks"

    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.String(20), db.ForeignKey("shipments.id"), nullable=False)
    rule = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(10), nullable=False)  # pass | fail | skipped
    detail = db.Column(db.String(500))
    resolved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    resolved_at = db.Column(db.DateTime)


class Correction(db.Model):
    """Edit history. Also the source for the accuracy report."""
    __tablename__ = "corrections"

    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id"), nullable=False)
    old_value = db.Column(db.String(255))
    new_value = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=now)