"""Write routes refuse anonymous and non-admin callers before touching the DB.

The auth checks run before any query, so these tests never reach a database.
The app is pointed at the local dev database only so that nothing could ever
connect to a remote host.
"""

from types import SimpleNamespace

import pytest
from flask_jwt_extended import create_access_token

from padel_league import create_app
from padel_league.config import DevConfig
from padel_league.modules import api as legacy_api
from padel_league.tools import auth_tools

LOCAL_DB_URI = "postgresql://postgres@localhost:5432/padel_league_v2d"


@pytest.fixture
def locked_app():
    config = {k: getattr(DevConfig, k) for k in dir(DevConfig) if k.isupper()}
    config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=LOCAL_DB_URI,
        SECRET_KEY="test-secret",
        JWT_SECRET_KEY="test-jwt-secret-of-at-least-32-bytes",
    )
    return create_app(config)


@pytest.fixture
def client(locked_app):
    return locked_app.test_client()


def _bearer(app, identity="999"):
    with app.app_context():
        token = create_access_token(identity=identity)
    return {"Authorization": f"Bearer {token}"}


# --- v1 JSON API -----------------------------------------------------------

LOGGED_IN_V1 = [
    ("POST", "/api/v1/matches/1/edit"),
    ("POST", "/api/v1/matches/1/edit_shuffle"),
    ("POST", "/api/v1/tournaments/1/remove_player_from_matchweek"),
    ("POST", "/api/v1/shuffle_tournament/remove_player_from_matchweek"),
    ("PUT", "/api/v1/players/1"),
    ("POST", "/api/v1/tournaments/1/refresh_standings"),
]

ADMIN_V1 = [
    ("POST", "/api/v1/divisions"),
    ("PUT", "/api/v1/divisions/1"),
    ("POST", "/api/v1/divisions/1/generate_matches"),
    ("POST", "/api/v1/editions"),
]

SUPER_ADMIN_V1 = [
    ("POST", "/api/v1/shuffle_tournament/calculate_divisions"),
    ("POST", "/api/v1/shuffle_tournament/undo_calculate_divisions"),
    ("POST", "/api/v1/shuffle_tournament/generate_matchweek"),
    ("POST", "/api/v1/shuffle_tournament/delete_last_matchweek"),
    ("POST", "/api/v1/shuffle_tournament/create"),
]


@pytest.mark.parametrize("method,path", LOGGED_IN_V1 + ADMIN_V1 + SUPER_ADMIN_V1)
def test_v1_writes_need_a_token(client, method, path):
    response = client.open(path, method=method, json={})
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", ADMIN_V1 + SUPER_ADMIN_V1)
def test_v1_admin_actions_refuse_non_admins(locked_app, client, monkeypatch, method, path):
    user = SimpleNamespace(is_admin=False, super_admin=False)
    monkeypatch.setattr(auth_tools, "jwt_user", lambda: user)
    response = client.open(path, method=method, json={}, headers=_bearer(locked_app))
    assert response.status_code == 403


@pytest.mark.parametrize("method,path", SUPER_ADMIN_V1)
def test_v1_shuffle_admin_actions_need_super_admin(locked_app, client, monkeypatch, method, path):
    user = SimpleNamespace(is_admin=True, super_admin=False)
    monkeypatch.setattr(auth_tools, "jwt_user", lambda: user)
    response = client.open(path, method=method, json={}, headers=_bearer(locked_app))
    assert response.status_code == 403


def test_v1_admin_guard_refuses_unknown_user(locked_app, client, monkeypatch):
    monkeypatch.setattr(auth_tools, "jwt_user", lambda: None)
    response = client.post("/api/v1/editions", json={}, headers=_bearer(locked_app))
    assert response.status_code == 403


# --- legacy /api blueprint (admin editor backend) -------------------------

LEGACY_API = [
    ("POST", "/api/edit/user/1"),
    ("POST", "/api/delete/user/1"),
    ("POST", "/api/delete_player/1"),
    ("POST", "/api/delete_tournament/1"),
    ("POST", "/api/delete_order_line/1"),
    ("POST", "/api/remove_relationship"),
    ("GET", "/api/modal_create_page/user"),
    ("POST", "/api/modal_create_page/user"),
    ("POST", "/api/upload_csv_to_db/user"),
    ("GET", "/api/query/user"),
    ("POST", "/api/download_csv/user"),
    ("GET", "/api/csv/user.csv"),
]


@pytest.mark.parametrize("method,path", LEGACY_API)
def test_legacy_api_redirects_anonymous_to_login(client, method, path):
    response = client.open(path, method=method, json={})
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


@pytest.fixture
def admin_client(locked_app):
    """A client whose requests Flask-Login resolves to an admin, without a database."""
    admin = SimpleNamespace(
        is_authenticated=True, is_active=True, is_anonymous=False,
        is_admin=True, super_admin=True, id=1, get_id=lambda: "1",
    )
    locked_app.login_manager.request_loader(lambda _request: admin)
    return locked_app.test_client()


@pytest.mark.parametrize("path", ["/api/delete/users/1", "/api/delete_order_line/1"])
def test_legacy_api_deletes_never_run_on_get(client, admin_client, path):
    # Even an admin's GET (a link, a prefetch, a crawler on a logged-in browser)
    # must not delete anything: the routes answer POST only, for everyone.
    assert client.get(path).status_code == 405
    assert admin_client.get(path).status_code == 405


@pytest.mark.parametrize(
    "path",
    ["/api/calendar", "/api/calendar/1", "/api/points_by_matchweek/1", "/api/image/1"],
)
def test_legacy_api_public_reads_stay_public(locked_app, path):
    with locked_app.test_request_context(path):
        assert legacy_api.require_admin() is None


# --- legacy Jinja routes ---------------------------------------------------

JINJA_WRITES = [
    ("GET", "/players/edit/1"),
    ("POST", "/players/edit/1"),
    ("GET", "/players/ranking/recalculate"),
    ("GET", "/matches/edit/1"),
    ("POST", "/matches/edit/1"),
    ("POST", "/matches/create/1"),
    ("GET", "/matches/for_edit"),
    ("GET", "/tournaments/edit/1"),
    ("POST", "/tournaments/delete/1"),
    ("GET", "/tournaments/1/recalculate"),
    ("GET", "/editions/create"),
    ("POST", "/editions/create"),
    ("POST", "/editions/delete/1"),
    ("POST", "/news/create"),
    ("POST", "/news/delete/1"),
    ("GET", "/news/new_prompt"),
    ("GET", "/news/test_prompt"),
    ("POST", "/products/create"),
    ("POST", "/products/delete/1"),
    ("POST", "/products_attributes/create"),
    ("POST", "/products_attributes/edit/1"),
    ("POST", "/products_attributes/delete/1"),
    ("POST", "/registrations/create/1"),
    ("GET", "/registrations/"),
    ("POST", "/registrations/delete/1"),
    ("POST", "/uploads/upload_csv_to_db"),
]


@pytest.mark.parametrize("method,path", JINJA_WRITES)
def test_jinja_writes_redirect_anonymous_to_login(client, method, path):
    response = client.open(path, method=method, data={})
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


@pytest.mark.parametrize(
    "path",
    [
        # /tournaments/delete/1 is left out: a GET falls through to the
        # read-only /tournaments/<id>/<recalculate> page instead of 405.
        "/editions/delete/1",
        "/news/delete/1",
        "/products/delete/1",
        "/products_attributes/delete/1",
        "/registrations/delete/1",
    ],
)
def test_deletes_are_post_only(client, path):
    assert client.get(path).status_code == 405


@pytest.mark.parametrize(
    "path", ["/tournaments/1", "/tournaments/1/recalculate", "/tournaments/1/x"]
)
def test_tournament_page_refuses_post(client, path):
    # A POST used to persist a recomputed table for anyone.
    assert client.post(path).status_code == 405


def test_export_db_to_csv_is_gone(client):
    assert client.get("/uploads/export_db_to_csv").status_code == 404
    assert client.post("/uploads/export_db_to_csv").status_code == 404
