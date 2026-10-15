"""Errors and role guards shared by every /api/v2 blueprint.

Errors are always `{error, code}` with a status the spec documents (400/401/403/404/409).
The app-wide JWT loaders (padel_league/auth.py) answer v1 shapes and 422 for a bad
token, so v2 guards verify the token themselves and answer 401.
"""

from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError

ROLE_ORDER = {"player": 0, "admin": 1, "super_admin": 2}


class ApiError(Exception):
    def __init__(self, status, message, code):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def bad_request(message, code="invalid_input"):
    return ApiError(400, message, code)


def not_found(message="Não encontrado.", code="not_found"):
    return ApiError(404, message, code)


def conflict(message, code="conflict"):
    return ApiError(409, message, code)


def _domain_status(exc):
    """Map S1's DomainError subclasses (padel_league/domain/errors.py) by name."""
    names = {cls.__name__ for cls in type(exc).__mro__}
    if "NotFound" in names:
        return 404
    if "Conflict" in names:
        return 409
    return 400


def register_error_handlers(bp):
    @bp.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify({"error": exc.message, "code": exc.code}), exc.status

    try:
        from padel_league.domain.errors import DomainError
    except ImportError:  # S1's domain package not merged yet
        DomainError = None

    if DomainError is not None:

        @bp.errorhandler(DomainError)
        def _domain_error(exc):
            message = getattr(exc, "message", None) or str(exc)
            return jsonify({"error": message, "code": getattr(exc, "code", "domain_error")}), _domain_status(exc)


def _user_from_token(optional):
    from padel_league.models import User

    try:
        verify_jwt_in_request(optional=optional)
    except (JWTExtendedException, PyJWTError):
        if optional:
            return None
        raise ApiError(401, "Sessão inválida ou expirada.", "unauthorized")
    identity = get_jwt_identity()
    if identity is None:
        return None
    try:
        return User.query.get(int(identity))
    except (TypeError, ValueError):
        return None


def viewer():
    """The signed-in User, or None (a missing, bad or expired token is anonymous)."""
    return _user_from_token(optional=True)


def require_user():
    user = _user_from_token(optional=False)
    if user is None:
        raise ApiError(401, "Sessão inválida.", "unauthorized")
    return user


def has_role(user, role):
    return user is not None and ROLE_ORDER.get(user.role, 0) >= ROLE_ORDER[role]


def role_required(role="player"):
    """401 without a valid access token, 403 when users.role is below `role`."""

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = require_user()
            if not has_role(user, role):
                raise ApiError(403, "Não tens permissão para isto.", "forbidden")
            return f(*args, **kwargs)

        return wrapper

    return decorator


def json_body():
    from flask import request

    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("O corpo do pedido tem de ser um objeto JSON.")
    return data


def int_arg(value, name, required=False):
    if value in (None, ""):
        if required:
            raise bad_request(f"{name} em falta.", "missing_parameter")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise bad_request(f"{name} inválido.", "invalid_parameter")
