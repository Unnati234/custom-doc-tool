import os

from flask import Flask

from .models import db


def create_app(config=None):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///app.db")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
    if config:
        app.config.update(config)

    db.init_app(app)
    with app.app_context():
        db.create_all()

    return app