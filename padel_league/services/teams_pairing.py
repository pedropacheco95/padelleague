"""PPL Teams pair formation (Estatutos Teams, pairs and divisions).

- A declared partner counts only when the choice is mutual.
- Nobody may play all 4 mini-tournaments with the same partner, so a pair that
  already played together 3 times is refused.
- At the deadline, everyone without a mutual pair is paired by ranking: take the
  best-ranked unpaired player and give them the nearest-ranked unpaired player
  they are allowed to play with, and so on down the list.
"""

from collections import Counter
from datetime import datetime

from padel_league.models import Player
from padel_league.models.teams import (
    TeamsMiniTournament,
    TeamsPair,
    TeamsPartnerRequest,
    TeamsPlayer,
)
from padel_league.sql_db import db

MAX_TIMES_TOGETHER = 3


class PairingError(ValueError):
    """A partner choice that the rules refuse. The message is shown to the player."""


def ranking_key(player):
    """Best first. Position 0 means unranked, which goes after every ranked player."""
    position = player.ranking_position or 0
    return (position == 0, position, -(player.ranking_points or 0), player.id)


def _key(a, b):
    return (a, b) if a < b else (b, a)


def times_together(mini_tournament_id):
    """How often each pair of players was paired in the *other* mini-tournaments."""
    rows = TeamsPair.query.filter(TeamsPair.mini_tournament_id != mini_tournament_id).all()
    return Counter(_key(p.player_a_id, p.player_b_id) for p in rows)


def allowed(a, b, history):
    return history[_key(a, b)] < MAX_TIMES_TOGETHER


def auto_pairs(players, history):
    """Pair `players` (already in ranking order) by nearest allowed partner.

    Deterministic. If a greedy choice would strand someone with no allowed
    partner further down, it backtracks to the next-nearest choice.
    """
    if len(players) % 2:
        raise PairingError("Número ímpar de jogadores sem parelha.")

    def solve(remaining):
        if not remaining:
            return []
        first, rest = remaining[0], remaining[1:]
        for i, candidate in enumerate(rest):
            if not allowed(first, candidate, history):
                continue
            tail = solve(rest[:i] + rest[i + 1 :])
            if tail is not None:
                return [(first, candidate)] + tail
        return None

    pairs = solve(list(players))
    if pairs is None:
        raise PairingError("Não há emparelhamento possível sem repetir uma parelha pela 4.ª vez.")
    return pairs


# --- database operations ----------------------------------------------------


def current_mini_tournament():
    """The latest mini-tournament (the one pairs are being formed for, or played)."""
    return TeamsMiniTournament.query.order_by(TeamsMiniTournament.number.desc()).first()


def roster_ids():
    return {row.player_id for row in TeamsPlayer.query.all()}


def pair_of(mini_tournament_id, player_id):
    return TeamsPair.query.filter(
        TeamsPair.mini_tournament_id == mini_tournament_id,
        (TeamsPair.player_a_id == player_id) | (TeamsPair.player_b_id == player_id),
    ).first()


def _check_open(mt, now):
    if mt.pairing_closed:
        raise PairingError("As parelhas deste mini-torneio já estão fechadas.")
    if now > mt.pairing_deadline:
        raise PairingError("O prazo para escolher parceiro já terminou.")


def _make_pair(mt, a, b, source):
    a, b = _key(a, b)
    pair = TeamsPair(mini_tournament_id=mt.id, player_a_id=a, player_b_id=b, source=source)
    db.session.add(pair)
    return pair


def declare(mt, player_id, partner_id, now=None):
    """Record `player_id`'s choice. Returns the pair if the choice is now mutual."""
    now = now or datetime.utcnow()
    _check_open(mt, now)
    roster = roster_ids()
    if player_id not in roster:
        raise PairingError("Não estás inscrito na Teams.")
    if partner_id not in roster:
        raise PairingError("Esse jogador não está inscrito na Teams.")
    if partner_id == player_id:
        raise PairingError("Não podes escolher-te a ti próprio.")
    if pair_of(mt.id, player_id):
        raise PairingError("Já tens parelha formada neste mini-torneio.")
    if pair_of(mt.id, partner_id):
        raise PairingError("Esse jogador já tem parelha formada.")
    if not allowed(player_id, partner_id, times_together(mt.id)):
        raise PairingError("Já jogaram juntos 3 mini-torneios; não podem fazer o 4.º juntos.")

    request_row = TeamsPartnerRequest.query.filter_by(mini_tournament_id=mt.id, player_id=player_id).first()
    if request_row is None:
        request_row = TeamsPartnerRequest(mini_tournament_id=mt.id, player_id=player_id)
        db.session.add(request_row)
    request_row.partner_id = partner_id
    request_row.created_at = now

    reciprocal = TeamsPartnerRequest.query.filter_by(
        mini_tournament_id=mt.id, player_id=partner_id, partner_id=player_id
    ).first()
    pair = _make_pair(mt, player_id, partner_id, "mutual") if reciprocal else None
    db.session.commit()
    return pair


def withdraw(mt, player_id, now=None):
    now = now or datetime.utcnow()
    _check_open(mt, now)
    if pair_of(mt.id, player_id):
        raise PairingError("A parelha já está formada; fala com a organização para a desfazer.")
    TeamsPartnerRequest.query.filter_by(mini_tournament_id=mt.id, player_id=player_id).delete()
    db.session.commit()


def set_pair(mt, a, b):
    """Admin: form a pair by hand (e.g. for a player without a login)."""
    roster = roster_ids()
    if a == b or a not in roster or b not in roster:
        raise PairingError("Escolhe dois jogadores diferentes inscritos na Teams.")
    for pid in (a, b):
        if pair_of(mt.id, pid):
            raise PairingError("Um dos jogadores já tem parelha formada.")
    if not allowed(a, b, times_together(mt.id)):
        raise PairingError("Já jogaram juntos 3 mini-torneios; não podem fazer o 4.º juntos.")
    pair = _make_pair(mt, a, b, "admin")
    db.session.commit()
    return pair


def unpair(mt, pair_id):
    """Admin: undo a pair before the pairs are closed."""
    if mt.pairing_closed:
        raise PairingError("As parelhas deste mini-torneio já estão fechadas.")
    TeamsPair.query.filter_by(mini_tournament_id=mt.id, id=pair_id).delete()
    db.session.commit()


def _settle_mutual(mt):
    """Form pairs for mutual choices that two simultaneous requests both missed."""
    choice = {r.player_id: r.partner_id for r in TeamsPartnerRequest.query.filter_by(mini_tournament_id=mt.id)}
    paired = {pid for p in TeamsPair.query.filter_by(mini_tournament_id=mt.id) for pid in p.player_ids}
    history = times_together(mt.id)
    for a, b in sorted(choice.items()):
        if a < b and choice.get(b) == a and not {a, b} & paired and allowed(a, b, history):
            _make_pair(mt, a, b, "mutual")
            paired |= {a, b}
    db.session.flush()


def close(mt):
    """Pair everyone left by ranking and close the mini-tournament's pairs."""
    if mt.pairing_closed:
        raise PairingError("As parelhas deste mini-torneio já estão fechadas.")
    _settle_mutual(mt)
    paired = {pid for p in TeamsPair.query.filter_by(mini_tournament_id=mt.id) for pid in p.player_ids}
    left = Player.query.filter(Player.id.in_(roster_ids() - paired)).all()
    order = [p.id for p in sorted(left, key=ranking_key)]
    created = [_make_pair(mt, a, b, "auto") for a, b in auto_pairs(order, times_together(mt.id))]
    mt.pairing_closed = True
    db.session.commit()
    return created
