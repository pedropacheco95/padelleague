"""Fixtures for /api/v2 tests: a client on the rolled-back Postgres session, users with tokens."""

import re

import pytest
from flask.testing import FlaskClient
from flask_jwt_extended import create_access_token, create_refresh_token
from sqlalchemy import event

from padel_league.models import User
from padel_league.sql_db import db
from padel_league.tests.contract import assert_matches_spec


def _spec_routes():
    """[(regex, template)] for every spec path; literal paths win over templated ones."""
    from padel_league.tests.contract import spec

    routes = []
    for template in spec()["paths"]:
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", template)
        routes.append((template.count("{"), re.compile(f"^/api/v2{pattern}$"), template))
    return [(rx, t) for _, rx, t in sorted(routes, key=lambda r: r[0])]


# Asked of S0 (spec owner); remove each line once the spec documents it.
PENDING_SPEC_PATHS = ("/api/v2/news",)
PENDING_SPEC_STATUSES = {
    ("get", "/rankings/players/{playerId}", 409),  # ranking_missing_awards before the bootstrap
    ("post", "/stages/{stageId}/divisions", 404),
}


class ContractClient(FlaskClient):
    """Every /api/v2 response is validated against the spec: its status must be
    documented and its JSON body must match, whatever the test asserts after."""

    def open(self, *args, **kwargs):
        response = super().open(*args, **kwargs)
        request = response.request
        path, method = request.path, request.method.lower()
        if path.startswith("/api/v2"):
            template = next((t for rx, t in _spec_routes() if rx.match(path)), None)
            if template is None and path.startswith(PENDING_SPEC_PATHS):
                return response
            assert template is not None, f"{method.upper()} {path} is not in the spec"
            if (method, template, response.status_code) in PENDING_SPEC_STATUSES:
                return response
            assert_matches_spec(response, template, method)
            if response.is_json:
                assert_v2_shape(response.get_json())
        return response


@pytest.fixture
def client(pg):
    pg.test_client_class = ContractClient
    try:
        yield pg.test_client()
    finally:
        pg.test_client_class = None


def persist():
    """Commit test setup before calling the API.

    The `pg` fixture's session is removed at every request teardown, which drops
    flushed-but-uncommitted rows; a commit only releases the savepoint, so the
    test's final rollback still cleans up.
    """
    db.session.commit()


@pytest.fixture
def make_user(pg):
    def _make(role="player", player=None, username=None):
        if player is not None and player.user is not None:
            player.user.role = role
            persist()
            return player.user
        n = User.query.count() + 1
        user = User(
            username=username or f"v2_{role}_{n}",
            email=f"v2_{role}_{n}@example.com",
            password="x",
            role=role,
            player_id=player.id if player else None,
        )
        db.session.add(user)
        persist()
        return user

    return _make


def bearer(user, refresh=False):
    make = create_refresh_token if refresh else create_access_token
    return {"Authorization": f"Bearer {make(identity=str(user.id))}"}


CAMEL = re.compile(r"^[a-z][a-zA-Z0-9]*$")
SNAKE_ALLOWED = {"access_token", "refresh_token"}  # spec Tokens


def assert_v2_shape(body, path="$"):
    """camelCase keys everywhere (the contract helper allows extra keys) and UTC datetimes end in Z."""
    if isinstance(body, dict):
        for key, value in body.items():
            assert key in SNAKE_ALLOWED or CAMEL.match(key), f"{path}.{key} is not camelCase"
            if key.endswith("At") or key == "pairingDeadline" or key == "computedAt":
                assert value is None or value.endswith("Z"), f"{path}.{key}={value!r} lacks Z"
            if key not in ("rules", "stats"):  # free-form maps
                assert_v2_shape(value, f"{path}.{key}")
    elif isinstance(body, list):
        for i, item in enumerate(body[:50]):
            assert_v2_shape(item, f"{path}[{i}]")


def check(response, spec_path, method="get", status=200):
    assert response.status_code == status, response.get_data(as_text=True)[:500]
    assert_matches_spec(response, spec_path, method)
    if response.is_json:
        assert_v2_shape(response.get_json())
    return response.get_json()


class QueryCounter:
    def __init__(self):
        self.count = 0

    def __call__(self, *args, **kwargs):
        self.count += 1


@pytest.fixture
def count_queries(pg):
    def _count():
        counter = QueryCounter()
        event.listen(db.engine, "before_cursor_execute", counter)
        return counter

    yield _count
    # listeners are removed per counter by stop()


def stop_counting(counter):
    event.remove(db.engine, "before_cursor_execute", counter)
    return counter.count
