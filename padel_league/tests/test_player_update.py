import datetime
import os
import tempfile

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash, generate_password_hash

from padel_league import create_app
from padel_league.model import Image
from padel_league.models import Player, User
from padel_league.sql_db import db, init_db


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp()
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "JWT_SECRET_KEY": "test-secret",
            # create_app replaces the config wholesale, so anything the app
            # touches on every request (chatbot_api.initialize_globals) must be here.
            "LLM_API_KEY": "",
        }
    )
    with app.app_context():
        init_db(app)
        db.metadata.create_all(
            bind=db.engine, tables=[Player.__table__, User.__table__, Image.__table__]
        )
    yield app
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


def make_player(name, username, password="segredo", is_admin=False, **kwargs):
    player = Player(name=name, **kwargs)
    player.create()
    user = User(
        username=username,
        email=f"{username}@example.com",
        password=generate_password_hash(password),
        player_id=player.id,
        is_admin=is_admin,
    )
    user.create()
    return player, user


def auth_header(user):
    return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


def test_requires_authentication(app, client):
    with app.app_context():
        player, _ = make_player("Zé", "ze")
        res = client.put(f"/api/v1/players/{player.id}", data={"name": "Novo"})
    assert res.status_code == 401


def test_player_can_edit_itself(app, client):
    with app.app_context():
        player, user = make_player("Zé", "ze")
        res = client.put(
            f"/api/v1/players/{player.id}",
            data={"name": "Zé Pedro", "height": "1.82"},
            headers=auth_header(user),
        )
        assert res.status_code == 200
        refreshed = Player.query.get(player.id)
        assert refreshed.name == "Zé Pedro"
        assert refreshed.height == 1.82


def test_player_cannot_edit_someone_else(app, client):
    with app.app_context():
        _, intruder = make_player("Intruso", "intruso")
        victim, _ = make_player("Vitima", "vitima")
        res = client.put(
            f"/api/v1/players/{victim.id}",
            data={"name": "Hackeado"},
            headers=auth_header(intruder),
        )
        assert res.status_code == 403
        assert Player.query.get(victim.id).name == "Vitima"


def test_admin_can_edit_anyone(app, client):
    with app.app_context():
        _, admin = make_player("Chefe", "chefe", is_admin=True)
        target, _ = make_player("Alvo", "alvo")
        res = client.put(
            f"/api/v1/players/{target.id}",
            data={"full_name": "Alvo Silva"},
            headers=auth_header(admin),
        )
        assert res.status_code == 200
        assert Player.query.get(target.id).full_name == "Alvo Silva"


def test_fills_in_a_field_that_is_currently_empty(app, client):
    """The legacy Flask form could never set a field that started out empty."""
    with app.app_context():
        player, user = make_player("Zé", "ze")
        assert player.birthday is None
        res = client.put(
            f"/api/v1/players/{player.id}",
            data={"birth_date": "1990-05-17", "full_name": "Zé Ferreira"},
            headers=auth_header(user),
        )
        assert res.status_code == 200
        refreshed = Player.query.get(player.id)
        assert refreshed.birthday == datetime.date(1990, 5, 17)
        assert refreshed.full_name == "Zé Ferreira"


def test_omitted_fields_are_left_alone(app, client):
    with app.app_context():
        player, user = make_player("Zé", "ze", full_name="Zé Ferreira")
        res = client.put(
            f"/api/v1/players/{player.id}",
            data={"height": "1.90"},
            headers=auth_header(user),
        )
        assert res.status_code == 200
        refreshed = Player.query.get(player.id)
        assert refreshed.full_name == "Zé Ferreira"
        assert refreshed.name == "Zé"


def test_password_change_requires_the_current_password(app, client):
    with app.app_context():
        player, user = make_player("Zé", "ze", password="antiga")
        res = client.put(
            f"/api/v1/players/{player.id}",
            data={"password": "nova"},
            headers=auth_header(user),
        )
        assert res.status_code == 400
        assert check_password_hash(User.query.get(user.id).password, "antiga")


def test_password_changes_with_the_right_current_password(app, client):
    with app.app_context():
        player, user = make_player("Zé", "ze", password="antiga")
        res = client.put(
            f"/api/v1/players/{player.id}",
            data={"password": "nova", "current_password": "antiga"},
            headers=auth_header(user),
        )
        assert res.status_code == 200
        assert check_password_hash(User.query.get(user.id).password, "nova")


def test_rejects_a_username_taken_by_someone_else(app, client):
    with app.app_context():
        player, user = make_player("Zé", "ze")
        make_player("Outro", "outro")
        res = client.put(
            f"/api/v1/players/{player.id}",
            data={"username": "outro"},
            headers=auth_header(user),
        )
        assert res.status_code == 400
        assert User.query.get(user.id).username == "ze"


def test_keeping_your_own_username_is_not_a_conflict(app, client):
    with app.app_context():
        player, user = make_player("Zé", "ze")
        res = client.put(
            f"/api/v1/players/{player.id}",
            data={"username": "ze", "height": "1.70"},
            headers=auth_header(user),
        )
        assert res.status_code == 200


def test_rejects_an_invalid_prefered_hand(app, client):
    with app.app_context():
        player, user = make_player("Zé", "ze")
        res = client.put(
            f"/api/v1/players/{player.id}",
            data={"prefered_hand": "Ambidestro"},
            headers=auth_header(user),
        )
        assert res.status_code == 400


def test_rejects_an_invalid_height(app, client):
    with app.app_context():
        player, user = make_player("Zé", "ze")
        res = client.put(
            f"/api/v1/players/{player.id}",
            data={"height": "muito alto"},
            headers=auth_header(user),
        )
        assert res.status_code == 400


def test_unknown_player_is_404(app, client):
    with app.app_context():
        _, user = make_player("Zé", "ze")
        res = client.put(
            "/api/v1/players/9999",
            data={"name": "Fantasma"},
            headers=auth_header(user),
        )
        assert res.status_code == 404
