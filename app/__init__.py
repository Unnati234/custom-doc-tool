import os

from flask import Flask, render_template

from .models import db


def create_app(config=None):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///app.db")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["UPLOAD_DIR"] = os.environ.get("UPLOAD_DIR", os.path.join(app.root_path, "..", "uploads"))
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB per request
    if config:
        app.config.update(config)

    db.init_app(app)
    with app.app_context():
        db.create_all()

    from .routes.main import bp as main_bp
    app.register_blueprint(main_bp)

    messages = {400: "Bad request.", 403: "You don't have access to this page.",
                404: "Page not found.", 413: "That file is too large (10MB is maximum)."}

    def error_page(e):
        return render_template("error.html", code=e.code, message=messages.get(e.code, "Error")), e.code

    for code in messages:
        app.register_error_handler(code, error_page)

    return app