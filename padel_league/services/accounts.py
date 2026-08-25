"""Login accounts for players.

Every player must have a `users` row — a player without one cannot log in and
does not show up as a real person anywhere that joins through `users`. Creating
a player without an account is always a bug, so use `create_player` rather than
inserting into `players` directly.

The convention, taken from the accounts already in production (`diogogarrett`,
`manelserodio`, `joaoribeiro`):

- username — the full name, accents stripped, no spaces, lower case
- email    — ``<username>@email.com``
- password — the username, hashed the same way the rest of the app hashes

The password being the username is deliberate: these are handed out so players
can log in for the first time. It is a starting credential, not a secret.
"""

import unidecode
from werkzeug.security import generate_password_hash

from padel_league.models import Player, User
from padel_league.sql_db import db

EMAIL_DOMAIN = "email.com"


class AccountError(Exception):
    """A player account could not be created."""


def username_for(full_name):
    """`"Manel Serôdio"` -> `"manelserodio"`."""
    cleaned = unidecode.unidecode(full_name or "").strip().lower()
    username = "".join(ch for ch in cleaned if ch.isalnum())
    if not username:
        raise AccountError(f"cannot build a username from {full_name!r}")
    return username


def _unique(base, column):
    """Append a counter until the value is free — names do repeat."""
    candidate = base
    n = 1
    while db.session.query(User.id).filter(column == candidate).first():
        n += 1
        candidate = f"{base}{n}"
    return candidate


def ensure_user_for_player(player, commit=True):
    """Create the player's login if it doesn't exist. Returns (user, created)."""
    existing = User.query.filter_by(player_id=player.id).first()
    if existing:
        return existing, False

    base = username_for(player.full_name or player.name)
    username = _unique(base, User.username)
    email = _unique(f"{username}@{EMAIL_DOMAIN}", User.email)

    user = User(
        username=username,
        email=email,
        # The password is the username, per the league's onboarding convention.
        password=generate_password_hash(username),
        is_admin=False,
        super_admin=False,
        player_id=player.id,
    )
    db.session.add(user)
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    else:
        db.session.flush()
    return user, True


def create_player(full_name, name=None, commit=True):
    """Create a player *and* their login together. Returns (player, user).

    Idempotent on `full_name`: an existing player is returned untouched, but
    still gets an account if they somehow lack one.
    """
    full_name = (full_name or "").strip()
    if not full_name:
        raise AccountError("full_name is required")

    player = Player.query.filter_by(full_name=full_name).first()
    if not player:
        player = Player(
            name=(name or full_name).strip(),
            full_name=full_name,
            ranking_points=0,
            ranking_position=0,
        )
        db.session.add(player)
        db.session.flush()

    user, _ = ensure_user_for_player(player, commit=False)

    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    else:
        db.session.flush()
    return player, user


def players_without_accounts():
    return (
        Player.query.outerjoin(User, User.player_id == Player.id)
        .filter(User.id.is_(None))
        .order_by(Player.id)
        .all()
    )


def backfill_accounts(commit=True):
    """Give every account-less player a login. Returns the users created."""
    created = []
    for player in players_without_accounts():
        user, was_created = ensure_user_for_player(player, commit=False)
        if was_created:
            created.append(user)
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return created
