"""Conquistas (badges): one registry, one explicit rule per badge, computed for the whole
league from the same live data as the player story (services/player_story.League).

Edit badges in REGISTRY: name, rule (the sentence shown to players), the metric it reads
from player_facts(), the target, and how progress is written. Rarity is the share of
players with at least one game (members, not external subs) who own the badge:
Comum > 40%, Rara 15–40%, Épica 5–15%, Lendária < 5%.

Three kinds of rule:
- "at_least": earned when metric >= target (progress "186 de 200").
- "at_most": earned when metric <= target (e.g. 0 losses in an edition); a missing
  metric means not eligible yet.
- "leader": earned by the players with the league's best metric (ties share it);
  players below the minimum have no metric.
Nothing is stored: the league data is cached per day under a fingerprint of the tables it
reads, so a saved result changes the badges on the next request.
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import text

from padel_league.sql_db import db

COPY = {
    "info": (
        "As conquistas são marcos da carreira na liga, calculados a partir de todos os jogos. "
        "Cada uma tem uma regra fixa. A raridade é a percentagem de jogadores com pelo menos um "
        "jogo que a têm: Comum acima de 40%, Rara de 15 a 40%, Épica de 5 a 15%, Lendária abaixo "
        "de 5%. As que ainda faltam mostram quanto falta."
    ),
    "count": "{earned} de {total}",
    "progress": "{value} de {target}",
    "holders": ("{n} jogador", "{n} jogadores"),
    "rarity": "{pct}% dos jogadores",
}
TIERS = (("lendaria", "Lendária", 5), ("epica", "Épica", 15), ("rara", "Rara", 40), ("comum", "Comum", 101))

MIN_TIGHT = 20  # sangue-frio: decided-by-1-or-2 games needed to be ranked
INVICTO_MIN_MATCHES = 10


@dataclass(frozen=True)
class Badge:
    key: str
    name: str
    rule: str
    metric: str
    target: float = 1
    kind: str = "at_least"  # at_least | at_most | leader
    progress: object = None  # template (or singular/plural pair, by value) for a locked badge; None = COPY["progress"]


REGISTRY = (
    Badge("sangue_frio", "Sangue-frio", f"A melhor % de vitórias da liga nos jogos decididos por 1 ou 2 (mín. {MIN_TIGHT}).",
          "tight_pct", kind="leader", progress="{value}% (o melhor tem {target}%)"),
    Badge("podio_shuffle", "Pódio Shuffle", "Acabar um Shuffle no pódio.", "shuffle_podiums"),
    Badge("invicto", "Invicto", f"Uma edição Clássica com {INVICTO_MIN_MATCHES} ou mais jogos e nenhuma derrota.",
          "invicto_losses", target=0, kind="at_most", progress=("Melhor edição: {value} derrota", "Melhor edição: {value} derrotas")),
    Badge("pentacampeao", "Pentacampeão", "Ganhar 5 divisões.", "titles", target=5),
    Badge("tetracampeao", "Tetracampeão", "Ganhar 4 divisões.", "titles", target=4),
    Badge("rei_da_1", "Rei da 1ª", "Ganhar a 1ª Divisão.", "first_division_titles"),
    Badge("clube_300", "Clube 300", "Jogar 300 jogos.", "matches", target=300),
    Badge("ferro_30", "Ferro 30", "Estar presente em 30 jornadas seguidas.", "best_attendance", target=30),
    Badge("centuriao", "Centurião", "Ganhar 100 jogos.", "wins", target=100),
    Badge("veterano", "Veterano", "Jogar 10 edições.", "editions", target=10),
    Badge("pneu", "Pneu", "Ganhar um jogo sem perder um único jogo de ténis (X–0).", "shutouts"),
    Badge("elevador", "Elevador", "Subir de divisão.", "promotions"),
    Badge("clube_200", "Clube 200", "Ganhar 200 jogos.", "wins", target=200),
    Badge("campeao_teams", "Campeão Teams", "Ganhar uma divisão de um torneio Teams.", "teams_titles"),
)
BY_KEY = {b.key: b for b in REGISTRY}


def tier_of(pct):
    return next((key, label) for key, label, top in TIERS if pct < top)


# --- facts -------------------------------------------------------------------------------


def player_facts(league, pid, teams_titles):
    """Every metric a badge can read, for one player."""
    from padel_league.services.player_story import streak_values

    results = [(m, r) for m, r in league.results(pid) if r is not None]
    wins = sum(1 for _, r in results if r == "W")
    entries = [e for e in league.entries.get(pid, []) if league.comps[e.competition_id].status != "planned"]
    ended = {e.competition_id: e.final_place for e in league.entries.get(pid, [])
             if league.comps[e.competition_id].status == "ended" and e.final_place is not None}
    my_groups = league.member_groups.get(pid, set())
    tier_by_comp = {}
    for g in my_groups:
        grp = league.groups.get(g)
        if grp is not None and league.comps[grp.competition_id].format == "classica":
            tier_by_comp[grp.competition_id] = grp.tier
    # Promotions: a lower tier number than the previous Clássica edition.
    classic = sorted(tier_by_comp, key=league.edition_key)
    promotions = sum(
        1 for a, b in zip(classic, classic[1:])
        if tier_by_comp[a] is not None and tier_by_comp[b] is not None and tier_by_comp[b] < tier_by_comp[a]
    )
    # Invicto: fewest losses in an ended Clássica edition with enough matches.
    per_comp = defaultdict(lambda: [0, 0])
    for m, r in results:
        if m.format == "classica" and league.comps[m.competition_id].status == "ended":
            per_comp[m.competition_id][0] += 1
            per_comp[m.competition_id][1] += r == "L"
    eligible = [losses for n, losses in per_comp.values() if n >= INVICTO_MIN_MATCHES]
    # Pneu: a won match where the other side scored no game (walkovers have no sets).
    shutouts = sum(
        1 for m, r in results
        if r == "W" and m.sets and not m.corrupt and sum(s[1] if m.side_of(pid) == "home" else s[0] for s in m.sets) == 0
    )
    tight = [mg for m, _ in results for mg in [m.margin(pid)] if mg is not None and 0 < abs(mg) <= 2]
    return {
        "matches": len(results),
        "wins": wins,
        "editions": len(entries),
        "titles": sum(1 for p in ended.values() if p == 1),
        "first_division_titles": sum(
            1 for cid, p in ended.items() if p == 1 and tier_by_comp.get(cid) == 1
        ),
        "shuffle_podiums": sum(1 for cid, p in ended.items() if league.comps[cid].format == "shuffle" and p <= 3),
        "invicto_losses": min(eligible) if eligible else None,
        "shutouts": shutouts,
        "promotions": promotions,
        "best_attendance": streak_values(league, pid)["nights"][1],
        "tight_pct": round(100 * sum(1 for mg in tight if mg > 0) / len(tight)) if len(tight) >= MIN_TIGHT else None,
        "teams_titles": teams_titles.get(pid, 0),
    }


def _teams_titles():
    rows = db.session.execute(
        text(
            "select a.player_id, count(*) n from awards a join award_events ae on ae.id = a.award_event_id "
            "join competitions c on c.id = ae.competition_id where c.format = 'teams' and a.place = 1 group by 1"
        )
    ).fetchall()
    return {r.player_id: r.n for r in rows}


# --- league-wide computation -------------------------------------------------------------------


def _earned(badge, value, target):
    if value is None or target is None:
        return False
    return value <= target if badge.kind == "at_most" else value >= target


def _closeness(badge, value, target):
    """Sort key for "closest to earning": smaller is closer."""
    if value is None:
        return float("inf")
    if badge.kind == "at_most":
        return value - target
    return -(value / target) if target else 0


def compute(league):
    """{"players": [ids], "facts": {pid: facts}, "badges": {key: {...}}}; memoised on the league."""
    if getattr(league, "badges", None) is not None:
        return league.badges
    teams = _teams_titles()
    players = sorted(
        pid for pid in league.by_player
        if pid in league.players and league.players[pid].status != "external"
    )
    facts = {pid: player_facts(league, pid, teams) for pid in players}
    out = {}
    for b in REGISTRY:
        values = {pid: facts[pid][b.metric] for pid in players}
        target = b.target
        if b.kind == "leader":
            ranked = [v for v in values.values() if v is not None]
            target = max(ranked) if ranked else None
        holders = [pid for pid in players if _earned(b, values[pid], target)]
        pct = 100 * len(holders) / len(players) if players else 0.0
        tier, label = tier_of(pct)
        out[b.key] = {"badge": b, "target": target, "values": values, "holders": holders,
                      "pct": pct, "tier": tier, "tierLabel": label}
    league.badges = {"players": players, "facts": facts, "badges": out}
    return league.badges


def _fmt(v):
    return "—" if v is None else int(v) if float(v).is_integer() else v


def _item(b, data, pid=None):
    base = {
        "key": b.key,
        "name": b.name,
        "rule": b.rule,
        "kind": b.kind,
        "target": data["target"],
        "holdersCount": len(data["holders"]),
        "rarityPct": round(data["pct"], 1),
        "tier": data["tier"],
        "tierLabel": data["tierLabel"],
        "rarityLine": {"key": "badges.rarity", "text": COPY["rarity"].format(pct=_pct_text(data["pct"]))},
    }
    if pid is not None:
        value = data["values"].get(pid)
        earned = pid in data["holders"]
        progress = None
        if not earned and value is not None and data["target"] is not None:
            template = b.progress or COPY["progress"]
            if isinstance(template, tuple):
                template = template[0] if value == 1 else template[1]
            progress = {"key": f"badges.{b.key}.progress", "text": template.format(value=_fmt(value), target=_fmt(data["target"]))}
        fraction = None
        if b.kind == "at_least" and data["target"] and value is not None:
            fraction = min(1.0, value / data["target"])
        base.update({"earned": earned, "value": value, "fraction": fraction, "progress": progress})
    return base


def _pct_text(pct):
    return f"{pct:.0f}" if pct >= 10 or pct == 0 else f"{pct:.1f}".replace(".", ",")


def catalogue(league):
    """GET /badges: every badge with its rule, rarity and holders, rarest first."""
    c = compute(league)
    badges = []
    for b in REGISTRY:
        data = c["badges"][b.key]
        badges.append({**_item(b, data), "holders": [league.ref(p) for p in data["holders"]]})
    badges.sort(key=lambda x: (x["rarityPct"], x["key"]))
    return {"playersCount": len(c["players"]), "info": {"key": "badges.info", "text": COPY["info"]}, "badges": badges}


def detail(league, key, closest=10):
    """GET /badges/<key>: the catalogue entry plus who is closest to earning it."""
    b = BY_KEY.get(key)
    if b is None:
        return None
    c = compute(league)
    data = c["badges"][key]
    others = [p for p in c["players"] if p not in data["holders"] and data["values"][p] is not None]
    others.sort(key=lambda p: (_closeness(b, data["values"][p], data["target"]), p))
    return {
        **_item(b, data),
        "playersCount": len(c["players"]),
        "holders": [league.ref(p) for p in data["holders"]],
        "closest": [
            {**_item(b, data, p), "player": league.ref(p)} for p in others[:closest]
        ],
    }


def for_player(league, pid):
    """The player's badges: earned first (rarest first), then locked by progress."""
    c = compute(league)
    if pid not in c["facts"]:
        return None
    items = [_item(b, c["badges"][b.key], pid) for b in REGISTRY]
    items.sort(key=lambda i: (not i["earned"], i["rarityPct"] if i["earned"] else -(i["fraction"] or 0), i["key"]))
    earned = sum(1 for i in items if i["earned"])
    return {
        "earned": earned,
        "total": len(items),
        "countLine": {"key": "badges.count", "text": COPY["count"].format(earned=earned, total=len(items))},
        "info": {"key": "badges.info", "text": COPY["info"]},
        "items": items,
    }
