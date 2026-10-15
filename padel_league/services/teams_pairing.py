"""PPL Teams pair formation (Estatutos Teams, pairs and divisions), on the v2 model.

- The Teams edition is a `Competition(format="teams")`; each mini-tournament is
  a `Stage`; the roster is its active `Entry` rows; choices are
  `PartnerRequest`s and formed pairs are `Pair`s of the stage.
- A declared partner counts only when the choice is mutual.
- Nobody may play all 4 mini-tournaments with the same partner, so a pair that
  already played together 3 times is refused.
- At the deadline, everyone without a mutual pair is paired by ranking: take the
  best-ranked unpaired player and give them the nearest-ranked unpaired player
  they are allowed to play with, and so on down the list.

Callers speak in player ids; entries are an internal detail.
"""

from collections import Counter
from datetime import datetime

from padel_league.models import Player
from padel_league.models.v2 import Competition, Entry, Pair, PartnerRequest, Stage
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


# --- lookups ------------------------------------------------------------------


def current_competition():
    return Competition.query.filter_by(format="teams").order_by(Competition.id.desc()).first()


def current_mini_tournament():
    """The latest stage that has opened pair choice (has a deadline)."""
    comp = current_competition()
    if comp is None:
        return None
    return (
        Stage.query.filter(Stage.competition_id == comp.id, Stage.pairing_deadline.isnot(None))
        .order_by(Stage.number.desc())
        .first()
    )


def _entries(stage):
    """{player_id: entry} for the stage's competition roster."""
    rows = Entry.query.filter_by(competition_id=stage.competition_id, status="active").all()
    return {e.player_id: e for e in rows}


def roster_ids(stage):
    return set(_entries(stage))


def roster_players(stage):
    return [e.player for e in _entries(stage).values()]


def _player_of_entry(stage):
    return {e.id: pid for pid, e in _entries(stage).items()}


def stage_pairs(stage):
    return Pair.query.filter_by(stage_id=stage.id).order_by(Pair.id).all()


def pair_players(stage, pair):
    """(player_a_id, player_b_id) of a pair."""
    entry_player = {e.id: e.player_id for e in (pair.entry_a, pair.entry_b)}
    return (entry_player[pair.entry_a_id], entry_player[pair.entry_b_id])


def times_together(stage):
    """How often each pair of players was paired in the *other* stages of the competition."""
    rows = (
        Pair.query.join(Stage, Stage.id == Pair.stage_id)
        .filter(Stage.competition_id == stage.competition_id, Pair.stage_id != stage.id)
        .all()
    )
    return Counter(_key(*pair_players(stage, p)) for p in rows)


def pair_of(stage, player_id):
    entry = _entries(stage).get(player_id)
    if entry is None:
        return None
    return Pair.query.filter(
        Pair.stage_id == stage.id, (Pair.entry_a_id == entry.id) | (Pair.entry_b_id == entry.id)
    ).first()


def choice_of(stage, player_id):
    """The partner player_id this player declared, or None."""
    entries = _entries(stage)
    entry = entries.get(player_id)
    if entry is None:
        return None
    req = PartnerRequest.query.filter_by(stage_id=stage.id, from_entry_id=entry.id).first()
    return _player_of_entry(stage).get(req.to_entry_id) if req else None


def chose(stage, player_id):
    """Player ids who declared `player_id` as their partner."""
    entries = _entries(stage)
    entry = entries.get(player_id)
    if entry is None:
        return []
    by_entry = _player_of_entry(stage)
    rows = PartnerRequest.query.filter_by(stage_id=stage.id, to_entry_id=entry.id).all()
    return [by_entry[r.from_entry_id] for r in rows if r.from_entry_id in by_entry]


# --- actions --------------------------------------------------------------------


def _check_open(stage, now):
    if stage.pairing_closed:
        raise PairingError("As parelhas deste mini-torneio já estão fechadas.")
    if stage.pairing_deadline is None or now > stage.pairing_deadline:
        raise PairingError("O prazo para escolher parceiro já terminou.")


def _make_pair(stage, a, b, formed_by):
    entries = _entries(stage)
    ea, eb = sorted((entries[a].id, entries[b].id))
    pair = Pair(stage_id=stage.id, entry_a_id=ea, entry_b_id=eb, formed_by=formed_by)
    db.session.add(pair)
    return pair


def declare(stage, player_id, partner_id, now=None):
    """Record `player_id`'s choice. Returns the pair if the choice is now mutual."""
    now = now or datetime.utcnow()
    _check_open(stage, now)
    entries = _entries(stage)
    if player_id not in entries:
        raise PairingError("Não estás inscrito na Teams.")
    if partner_id not in entries:
        raise PairingError("Esse jogador não está inscrito na Teams.")
    if partner_id == player_id:
        raise PairingError("Não podes escolher-te a ti próprio.")
    if pair_of(stage, player_id):
        raise PairingError("Já tens parelha formada neste mini-torneio.")
    if pair_of(stage, partner_id):
        raise PairingError("Esse jogador já tem parelha formada.")
    if not allowed(player_id, partner_id, times_together(stage)):
        raise PairingError("Já jogaram juntos 3 mini-torneios; não podem fazer o 4.º juntos.")

    mine, theirs = entries[player_id], entries[partner_id]
    request_row = PartnerRequest.query.filter_by(stage_id=stage.id, from_entry_id=mine.id).first()
    if request_row is None:
        request_row = PartnerRequest(stage_id=stage.id, from_entry_id=mine.id)
        db.session.add(request_row)
    request_row.to_entry_id = theirs.id
    request_row.submitted_at = now

    reciprocal = PartnerRequest.query.filter_by(
        stage_id=stage.id, from_entry_id=theirs.id, to_entry_id=mine.id
    ).first()
    pair = _make_pair(stage, player_id, partner_id, "mutual") if reciprocal else None
    db.session.commit()
    return pair


def withdraw(stage, player_id, now=None):
    now = now or datetime.utcnow()
    _check_open(stage, now)
    if pair_of(stage, player_id):
        raise PairingError("A parelha já está formada; fala com a organização para a desfazer.")
    entry = _entries(stage).get(player_id)
    if entry is not None:
        PartnerRequest.query.filter_by(stage_id=stage.id, from_entry_id=entry.id).delete()
    db.session.commit()


def set_pair(stage, a, b):
    """Admin: form a pair by hand (e.g. for a player without a login)."""
    roster = roster_ids(stage)
    if a == b or a not in roster or b not in roster:
        raise PairingError("Escolhe dois jogadores diferentes inscritos na Teams.")
    for pid in (a, b):
        if pair_of(stage, pid):
            raise PairingError("Um dos jogadores já tem parelha formada.")
    if not allowed(a, b, times_together(stage)):
        raise PairingError("Já jogaram juntos 3 mini-torneios; não podem fazer o 4.º juntos.")
    pair = _make_pair(stage, a, b, "manual")
    db.session.commit()
    return pair


def unpair(stage, pair_id):
    """Admin: undo a pair before the pairs are closed."""
    if stage.pairing_closed:
        raise PairingError("As parelhas deste mini-torneio já estão fechadas.")
    Pair.query.filter_by(stage_id=stage.id, id=pair_id).delete()
    db.session.commit()


def _settle_mutual(stage):
    """Form pairs for mutual choices that two simultaneous requests both missed."""
    by_entry = _player_of_entry(stage)
    choice = {
        by_entry[r.from_entry_id]: by_entry[r.to_entry_id]
        for r in PartnerRequest.query.filter_by(stage_id=stage.id)
        if r.from_entry_id in by_entry and r.to_entry_id in by_entry
    }
    paired = {pid for p in stage_pairs(stage) for pid in pair_players(stage, p)}
    history = times_together(stage)
    for a, b in sorted(choice.items()):
        if a < b and choice.get(b) == a and not {a, b} & paired and allowed(a, b, history):
            _make_pair(stage, a, b, "mutual")
            paired |= {a, b}
    db.session.flush()


def close(stage, positions=None):
    """Pair everyone left by ranking and close the mini-tournament's pairs.

    `positions` ({player_id: ranking position}) seeds the pairing; by default
    players.ranking_position, which services.ranking keeps mirrored from the
    live v2 ranking (services.ranking.compute gives it directly).
    """
    if stage.pairing_closed:
        raise PairingError("As parelhas deste mini-torneio já estão fechadas.")
    _settle_mutual(stage)
    paired = {pid for p in stage_pairs(stage) for pid in pair_players(stage, p)}
    left = Player.query.filter(Player.id.in_(roster_ids(stage) - paired)).all()
    if positions is None:
        order = [p.id for p in sorted(left, key=ranking_key)]
    else:
        order = [p.id for p in sorted(left, key=lambda p: (positions.get(p.id) or 10**9, p.id))]
    created = [_make_pair(stage, a, b, "ranking") for a, b in auto_pairs(order, times_together(stage))]
    stage.pairing_closed = True
    db.session.commit()
    return created


def add_to_roster(stage, player_id):
    if db.session.get(Player, player_id) is None:
        raise PairingError("Jogador desconhecido.")
    entry = Entry.query.filter_by(competition_id=stage.competition_id, player_id=player_id).first()
    if entry is None:
        db.session.add(Entry(competition_id=stage.competition_id, player_id=player_id))
    else:
        entry.status = "active"
    db.session.commit()


def remove_from_roster(stage, player_id):
    if pair_of(stage, player_id):
        raise PairingError("Desfaz primeiro a parelha deste jogador.")
    entry = _entries(stage).get(player_id)
    if entry is None:
        return
    PartnerRequest.query.filter(
        PartnerRequest.stage_id == stage.id,
        (PartnerRequest.from_entry_id == entry.id) | (PartnerRequest.to_entry_id == entry.id),
    ).delete(synchronize_session=False)
    has_history = Pair.query.filter((Pair.entry_a_id == entry.id) | (Pair.entry_b_id == entry.id)).first()
    if has_history:
        entry.status = "withdrawn"
    else:
        db.session.delete(entry)
    db.session.commit()


def set_roster(stage, player_ids):
    current = roster_ids(stage)
    for pid in sorted(current - player_ids):
        remove_from_roster(stage, pid)
    for pid in sorted(player_ids - current):
        add_to_roster(stage, pid)
