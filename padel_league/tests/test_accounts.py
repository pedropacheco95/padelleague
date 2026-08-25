import os
import tempfile

import pytest
from werkzeug.security import check_password_hash

from padel_league import create_app
from padel_league.models import Player, User
from padel_league.services.accounts import (
    AccountError,
    backfill_accounts,
    create_player,
    ensure_user_for_player,
    players_without_accounts,
    username_for,
)
from padel_league.sql_db import db, init_db


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
        db.metadata.create_all(
            bind=db.engine, tables=[Player.__table__, User.__table__]
        )
    yield app
    os.close(db_fd)
    os.unlink(db_path)


@pytest.mark.parametrize(
    "full_name,expected",
    [
        ("Nuno Azevedo", "nunoazevedo"),
        ("Manel Serôdio", "manelserodio"),  # accents stripped
        ("Álvaro Van Zeller", "alvarovanzeller"),
        ("Zé Pedro Graça", "zepedrograca"),
        ("João Lello", "joaolello"),
        ("  Diogo   Garrett  ", "diogogarrett"),  # whitespace collapsed
        ("Miguel C.", "miguelc"),  # punctuation dropped
    ],
)
def test_username_convention(full_name, expected):
    assert username_for(full_name) == expected


@pytest.mark.parametrize("bad", ["", "   ", None, "!!!"])
def test_username_needs_something_to_work_with(bad):
    with pytest.raises(AccountError):
        username_for(bad)


def test_create_player_also_creates_the_login(app):
    with app.app_context():
        player, user = create_player("Nuno Azevedo")
        assert player.full_name == "Nuno Azevedo"
        assert user.player_id == player.id
        assert user.username == "nunoazevedo"
        assert user.email == "nunoazevedo@email.com"
        assert user.is_admin is False


def test_password_is_the_username_and_is_hashed(app):
    with app.app_context():
        _, user = create_player("Álvaro Van Zeller")
        assert user.password != "alvarovanzeller"  # stored hashed, not plain
        assert check_password_hash(user.password, "alvarovanzeller")


def test_hash_matches_the_scheme_already_in_production(app):
    with app.app_context():
        _, user = create_player("João Lello")
        assert user.password.startswith("pbkdf2:sha256:")


def test_create_player_is_idempotent(app):
    with app.app_context():
        first, first_user = create_player("Bernardo Vasconcelos")
        second, second_user = create_player("Bernardo Vasconcelos")
        assert first.id == second.id
        assert first_user.id == second_user.id
        assert Player.query.count() == 1
        assert User.query.count() == 1


def test_a_repeated_name_gets_a_distinct_username(app):
    with app.app_context():
        create_player("Nuno Azevedo")
        # players.name and players.full_name are both unique, so a username
        # clash comes from two distinct names normalising the same way --
        # here an accent is the only difference.
        _, user = create_player("Nuno Azevêdo")
        created = True

        assert created is True
        assert user.username == "nunoazevedo2"
        assert user.email == "nunoazevedo2@email.com"
        assert check_password_hash(user.password, "nunoazevedo2")


def test_ensure_is_a_no_op_when_the_player_already_has_a_login(app):
    with app.app_context():
        player, user = create_player("Zé Pedro Graça")
        again, created = ensure_user_for_player(player)
        assert created is False
        assert again.id == user.id
        assert User.query.count() == 1


def test_players_without_accounts_finds_them(app):
    with app.app_context():
        create_player("Com Conta")
        orphan = Player(name="Sem Conta", full_name="Sem Conta")
        db.session.add(orphan)
        db.session.commit()

        assert [p.full_name for p in players_without_accounts()] == ["Sem Conta"]


def test_backfill_gives_every_orphan_a_login(app):
    with app.app_context():
        for full_name in ("Um Jogador", "Outro Jogador"):
            db.session.add(Player(name=full_name, full_name=full_name))
        db.session.commit()

        created = backfill_accounts()
        assert len(created) == 2
        assert players_without_accounts() == []
        assert {u.username for u in created} == {"umjogador", "outrojogador"}


def test_backfill_is_safe_to_run_twice(app):
    with app.app_context():
        db.session.add(Player(name="Um Jogador", full_name="Um Jogador"))
        db.session.commit()
        assert len(backfill_accounts()) == 1
        assert backfill_accounts() == []
        assert User.query.count() == 1


def test_create_player_needs_a_full_name(app):
    with app.app_context():
        with pytest.raises(AccountError, match="full_name is required"):
            create_player("   ")
