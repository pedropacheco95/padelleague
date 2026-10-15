import os
import subprocess
import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from padel_league import create_app
from padel_league.sql_db import db, init_db
from padel_league.models import User

# --- SQLite: old-model unit tests -------------------------------------------
# The pre-v2 models live in schema `compat` (views over the v2 tables on
# Postgres). On SQLite a schema is an attached database, so attach a companion
# file named compat to every SQLite connection. Tests that write old models
# also set ALLOW_COMPAT_WRITES (see read_only.init_compat_guard).


@event.listens_for(Engine, "connect")
def _attach_compat_schema(dbapi_connection, connection_record):
    if type(dbapi_connection).__module__.split(".")[0] != "sqlite3":
        return
    rows = dbapi_connection.execute("PRAGMA database_list").fetchall()
    if any(r[1] == "compat" for r in rows):
        return
    main = next((r[2] for r in rows if r[1] == "main"), "")
    dbapi_connection.execute("ATTACH DATABASE ? AS compat", (f"{main}.compat" if main else ":memory:",))


# --- Postgres: v2 tests ---------------------------------------------------------
# Every session clones the local template `v2_template` (scripts/v2/build_template.sh)
# into its own database, named after TEST_DB_PREFIX, so parallel sessions never
# touch each other's databases. Each test runs inside a transaction that is
# rolled back, even when the code under test commits.

PG = ["-h", "localhost", "-U", "postgres"]
TEMPLATE = os.environ.get("V2_TEMPLATE", "v2_template")


def test_db_name(suffix="pytest"):
    prefix = os.environ.get("TEST_DB_PREFIX", "test")
    return f"{prefix}_{suffix}_{os.getpid()}"


def _template_exists():
    out = subprocess.run(["psql", *PG, "-d", "postgres", "-Atc", f"select 1 from pg_database where datname='{TEMPLATE}'"],
                         capture_output=True, text=True)
    return out.stdout.strip() == "1"


@pytest.fixture(scope="session")
def pg_database():
    if not _template_exists():
        pytest.skip(f"local template {TEMPLATE} missing: run scripts/v2/build_template.sh")
    name = test_db_name()
    subprocess.run(["dropdb", *PG, "--if-exists", name], check=True)
    subprocess.run(["createdb", *PG, "-T", TEMPLATE, name], check=True)
    yield f"postgresql://postgres@localhost:5432/{name}"
    subprocess.run(["dropdb", *PG, "--if-exists", "--force", name])


def pg_config(uri, **extra):
    from padel_league.modules import chatbot_api

    chatbot_api.orchestrator_agent = chatbot_api.orchestrator_agent or object()
    return {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": uri,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SECRET_KEY": "test",
        "JWT_SECRET_KEY": "test-jwt-secret-of-at-least-32-bytes",
        "JWT_TOKEN_LOCATION": ["headers"],
        "JWT_HEADER_TYPE": "Bearer",
        **extra,
    }


@pytest.fixture(scope="session")
def pg_app(pg_database):
    return create_app(pg_config(pg_database))


@pytest.fixture
def pg(pg_app):
    """App context on the session database; everything the test does is rolled back.

    Commit test setup with db.session.commit() before calling the app: each
    request's teardown removes the session (and a GET rolls back), which drops
    rows that were only flushed. The commit just releases the savepoint; the
    outer transaction still rolls everything back at the end.
    """
    with pg_app.app_context():
        connection = db.engine.connect()
        outer = connection.begin()
        options = dict(bind=connection, binds={})
        session = db.create_scoped_session(options=options)
        session.begin_nested()

        @event.listens_for(session, "after_transaction_end")
        def _restart_savepoint(sess, trans):
            if trans.nested and not trans._parent.nested:
                sess.begin_nested()

        old_session, db.session = db.session, session
        try:
            yield pg_app
        finally:
            session.remove()
            outer.rollback()
            connection.close()
            db.session = old_session


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp()

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        }
    )

    with app.app_context():
        init_db(app)
        db.create_all()

    yield app

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


@pytest.fixture
def seed_users(app):
    with app.app_context():
        user1 = User(username="test", password="secret")
        user2 = User(username="other", password="secret2")
        db.session.add_all([user1, user2])
        db.session.commit()
        return [user1, user2]


class AuthActions:
    def __init__(self, client):
        self._client = client

    def login(self, username="test", password="secret"):
        return self._client.post(
            "/auth/login", data={"username": username, "password": password}
        )

    def logout(self):
        return self._client.get("/auth/logout")


@pytest.fixture
def auth(client):
    return AuthActions(client)
