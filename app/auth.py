import secrets
from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from .models import User, db


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def check_csrf():
    if request.method == "POST":
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
        if not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400)


def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("main.login", next=request.path))
        g.user = user
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    """Use after the route decorator, e.g. @role_required('manager')."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return login_required(wrapped)
    return decorator