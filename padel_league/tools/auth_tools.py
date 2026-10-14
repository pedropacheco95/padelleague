from functools import wraps
from urllib.parse import urljoin, urlparse

from flask import flash, jsonify, redirect, request, url_for
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_login import current_user


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            # If user is not authenticated, redirect to login page with next parameter
            return redirect(url_for("auth.login", next=request.url))
        elif not current_user.is_admin:
            # If user is not an admin, redirect to an appropriate error page or the index page.
            flash("You do not have permission to view this page.")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)

    return decorated_function


def login_required(f):
    """Flask-Login session required; anonymous users are sent to the login page."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)

    return decorated_function


def jwt_user():
    """The User behind the request's JWT, or None. Call after verify_jwt_in_request."""
    from padel_league.models import User

    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    return User.query.get(user_id)


def admin_required_jwt(super_admin=False):
    """JSON API guard: a valid JWT (401 otherwise) whose user is an admin (403 otherwise).

    super_admin=True requires User.super_admin, mirroring the screens the
    frontend only shows to super admins.
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            verify_jwt_in_request()
            user = jwt_user()
            allowed = user is not None and (
                user.super_admin if super_admin else user.is_admin
            )
            if not allowed:
                return jsonify({"error": "Admin access required"}), 403
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc
