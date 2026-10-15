"""users.role and the is_admin/super_admin booleans stay in step until phase 4."""

from padel_league.models import User
from padel_league.sql_db import db


def _user(**kw):
    user = User(username=kw.pop("username", "role_test"), email="role_test@example.com", password="x", **kw)
    db.session.add(user)
    db.session.flush()
    return user


def test_role_follows_the_booleans(pg):
    assert _user(is_admin=True, super_admin=False).role == "admin"


def test_booleans_follow_the_role(pg):
    user = _user()
    assert user.role == "player"
    user.role = "super_admin"
    db.session.flush()
    assert (user.is_admin, user.super_admin) == (True, True)
    user.role = "player"
    db.session.flush()
    assert (user.is_admin, user.super_admin) == (False, False)


def test_migrated_roles(pg):
    assert {u.username for u in User.query.filter_by(role="super_admin")} == {"pedropacheco", "dudasbf"}
    assert User.query.filter_by(role="admin").count() == 0
