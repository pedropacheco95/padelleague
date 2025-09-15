import os
import tempfile

import pytest

from padel_league import create_app
from padel_league.sql_db import db, init_db
from padel_league.models import User


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
