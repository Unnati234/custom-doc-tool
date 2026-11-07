import os

from flask import Flask, render_template

from .models import db

from dotenv import load_dotenv

from decimal import Decimal

def create_app(config=None):
    load_dotenv()  # reads .env for local development
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
        
    
    @app.template_filter("num")
    def num(value):
        """2400.000 -> 2400, 6.8000 -> 6.8, None -> empty."""
        if value is None:
            return ""
        return format(Decimal(str(value)).normalize(), "f")

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
    
    return app