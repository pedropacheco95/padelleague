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
BIG_WIN_MARGIN = 5  # rolo compressor: a win by this many games or more
FULL_EDITIONS = 5  # assíduo: Clássica editions attended in full
FULL_EDITION_MIN_NIGHTS = 5  # ... an edition counts when its group played at least this many nights
TIEBREAK = (7, 6)  # rei do tie-break: a set won by this score


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
    # --- Volume
    Badge("clube_100", "Clube 100", "Jogar 100 jogos.", "matches", target=100),
    Badge("clube_300", "Clube 300", "Jogar 300 jogos.", "matches", target=300),
    Badge("clube_400", "Clube 400", "Jogar 400 jogos.", "matches", target=400),
    Badge("centuriao", "Centurião", "Ganhar 100 jogos.", "wins", target=100),
    Badge("clube_200", "Clube 200", "Ganhar 200 jogos.", "wins", target=200),
    Badge("mil_games", "Mil Games", "Ganhar 1000 games (os pontos de cada set).", "games_won", target=1000),
    # --- Títulos e pódios
    Badge("campeao", "Campeão", "Ganhar uma divisão.", "titles"),
    Badge("bicampeao", "Bicampeão", "Ganhar 2 divisões.", "titles", target=2),
    Badge("tricampeao", "Tricampeão", "Ganhar 3 divisões.", "titles", target=3),
    Badge("tetracampeao", "Tetracampeão", "Ganhar 4 divisões.", "titles", target=4),
    Badge("pentacampeao", "Pentacampeão", "Ganhar 5 divisões.", "titles", target=5),
    Badge("rei_da_1", "Rei da 1ª", "Ganhar a 1ª Divisão.", "first_division_titles"),
    Badge("dinastia", "Dinastia", "Ganhar a divisão em duas edições Clássicas seguidas.", "consecutive_titles", target=2),
    Badge("habitue_podio", "Habitué do Pódio", "Acabar 5 edições no pódio.", "podiums", target=5),
    Badge("prata", "Prata", "Acabar 3 edições em 2º lugar.", "seconds", target=3),
    Badge("invicto", "Invicto", f"Uma edição Clássica com {INVICTO_MIN_MATCHES} ou mais jogos e nenhuma derrota.",
          "invicto_losses", target=0, kind="at_most", progress=("Melhor edição: {value} derrota", "Melhor edição: {value} derrotas")),
    # --- Sequências e presenças
    Badge("sete_seguidas", "Sete Seguidas", "Ganhar 7 jogos seguidos.", "best_win_streak", target=7),
    Badge("dez_seguidas", "Dez Seguidas", "Ganhar 10 jogos seguidos.", "best_win_streak", target=10),
    Badge("quinze_seguidas", "Quinze Seguidas", "Ganhar 15 jogos seguidos.", "best_win_streak", target=15),
    Badge("ferro_30", "Ferro 30", "Estar presente em 30 jornadas seguidas.", "best_attendance", target=30),
    Badge("ferro_50", "Ferro 50", "Estar presente em 50 jornadas seguidas.", "best_attendance", target=50),
    Badge("assiduo", "Assíduo", f"{FULL_EDITIONS} edições Clássicas sem faltar a uma única jornada.",
          "full_attendance_editions", target=FULL_EDITIONS),
    Badge("veterano", "Veterano", "Jogar 10 edições.", "editions", target=10),
    Badge("vinte_edicoes", "Vinte Edições", "Jogar 20 edições.", "editions", target=20),
    # --- Resultados e noites
    Badge("pneu", "Pneu", "Ganhar um jogo sem perder um único jogo de ténis (X–0).", "shutouts"),
    Badge("rolo_compressor", "Rolo Compressor", f"Ganhar 25 jogos por {BIG_WIN_MARGIN} ou mais games de diferença.", "big_wins", target=25),
    Badge("sangue_frio", "Sangue-frio", f"A melhor % de vitórias da liga nos jogos decididos por 1 ou 2 (mín. {MIN_TIGHT}).",
          "tight_pct", kind="leader", progress="{value}% (o melhor tem {target}%)"),
    Badge("rei_tiebreak", "Rei do Tie-break", "Ganhar 20 sets por 7–6.", "tiebreak_set_wins", target=20),
    Badge("salomao", "Salomão", "Empatar 20 jogos.", "draws", target=20),
    Badge("noite_perfeita", "Noite Perfeita", "Ganhar os 3 jogos de uma jornada.", "perfect_nights"),
    Badge("dono_da_noite", "Dono da Noite", "15 jornadas com os 3 jogos ganhos.", "perfect_nights", target=15),
    Badge("ressuscitador", "Ressuscitador", "Perder o 1º jogo da noite e ganhar os outros dois, 8 vezes.", "comebacks", target=8),
    # --- Parceiros e rivais
    Badge("sociavel", "Sociável", "Jogar com 30 parceiros diferentes.", "distinct_partners", target=30),
    Badge("quimica", "Química", "Ganhar 15 jogos com o mesmo parceiro.", "max_wins_with_partner", target=15),
    Badge("conhece_toda_a_gente", "Conhece Toda a Gente", "Defrontar 45 adversários diferentes.", "distinct_opponents", target=45),
    Badge("carrasco", "Carrasco", "Ganhar 20 jogos ao mesmo adversário.", "max_wins_vs_opponent", target=20),
    # --- Lealdade e divisões
    Badge("elevador", "Elevador", "Subir de divisão.", "promotions"),
    # --- Shuffle
    Badge("podio_shuffle", "Pódio Shuffle", "Acabar um Shuffle no pódio.", "shuffle_podiums"),
    # --- Teams
    Badge("campeao_teams", "Campeão Teams", "Ganhar uma divisão de um torneio Teams.", "teams_titles"),
    # --- Estreia

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
    ended_places = league.ended_places(pid)  # [(cid, place)] in edition order
    my_groups = league.member_groups.get(pid, set())
    tier_by_comp = {}
    for g in my_groups:
        grp = league.groups.get(g)
        if grp is not None and league.comps[grp.competition_id].format == "classica":
            tier_by_comp[grp.competition_id] = grp.tier
    # Promotions: a lower tier number than the previous Clássica edition; relegations the other way.
    classic = sorted(tier_by_comp, key=league.edition_key)
    moves = [
        (tier_by_comp[b] > tier_by_comp[a]) - (tier_by_comp[b] < tier_by_comp[a])  # -1 up, +1 down, 0 stay
        for a, b in zip(classic, classic[1:])
        if tier_by_comp[a] is not None and tier_by_comp[b] is not None
    ]
    promotions = sum(1 for mv in moves if mv == -1)
    double_promotions = sum(1 for x, y in zip(moves, moves[1:]) if x == -1 and y == -1)
    fenix = sum(1 for x, y in zip(moves, moves[1:]) if x == 1 and y == -1)
    # Invicto: fewest losses in an ended Clássica edition with enough matches.
    per_comp = defaultdict(lambda: [0, 0])
    for m, r in results:
        if m.format == "classica" and league.comps[m.competition_id].status == "ended":
            per_comp[m.competition_id][0] += 1
            per_comp[m.competition_id][1] += r == "L"
    eligible = [losses for n, losses in per_comp.values() if n >= INVICTO_MIN_MATCHES]
    # Games, shutouts, margins and tie-break sets (walkovers have no sets; corrupt sets stay out).
    games_won = shutouts = big_wins = tiebreak_set_wins = 0
    tight = []
    for m, r in results:
        margin = m.margin(pid)
        if margin is not None and 0 < abs(margin) <= 2:
            tight.append(margin)
        if margin is not None and margin >= BIG_WIN_MARGIN:
            big_wins += 1
        if not m.sets or m.corrupt:
            continue
        home = m.side_of(pid) == "home"
        mine = [h if home else a for h, a in m.sets]
        theirs = [a if home else h for h, a in m.sets]
        games_won += sum(mine)
        shutouts += r == "W" and sum(theirs) == 0
        tiebreak_set_wins += sum(1 for g in zip(mine, theirs) if g == TIEBREAK)
    # Clássica nights of three matches, in game order.
    by_night = defaultdict(list)
    for m, _ in results:
        if m.format == "classica":
            by_night[(m.group_id, m.round_id)].append(m)
    three = [[m.result(pid) for m in sorted(ms, key=lambda m: m.order)] for ms in by_night.values() if len(ms) == 3]
    # Partners and opponents (member seats only).
    partners = defaultdict(lambda: [0, 0])  # played, wins
    opponents = defaultdict(lambda: [0, 0])
    for m, r in results:
        for p in m.partners(pid):
            partners[p][0] += 1
            partners[p][1] += r == "W"
        for o in m.opponents(pid):
            opponents[o][0] += 1
            opponents[o][1] += r == "W"
    # Editions: full attendance, returns after a missed Clássica edition, founders.
    nights_by_comp = defaultdict(list)
    for _day, _rno, cid, _gid, present, _est, _rid in league.nights(pid):
        if league.comps[cid].format == "classica":
            nights_by_comp[cid].append(present)
    full_editions = sum(
        1 for cid, flags in nights_by_comp.items()
        if len(flags) >= FULL_EDITION_MIN_NIGHTS and all(flags) and league.comps[cid].status == "ended"
    )
    my_classic = sorted({m.competition_id for m, _ in results if m.format == "classica"}, key=league.edition_key)
    order = _classic_order(league)
    mine_idx = sorted(order[c] for c in my_classic if c in order)
    returns = sum(1 for a, b in zip(mine_idx, mine_idx[1:]) if b - a > 1)
    founder = any(league.edition_key(c)[0] <= 1 for c in my_classic)
    # Shuffle and Teams.
    shuffle_places = [p for cid, p in ended.items() if league.comps[cid].format == "shuffle"]
    teams = [(m, r) for m, r in results if m.format == "teams"]
    teams_pair_wins = defaultdict(int)
    for m, r in teams:
        for p in m.partners(pid):
            teams_pair_wins[p] += r == "W"
    streaks = streak_values(league, pid)
    return {
        "matches": len(results),
        "wins": wins,
        "draws": sum(1 for _, r in results if r == "D"),
        "games_won": games_won,
        "editions": len(entries),
        "titles": sum(1 for p in ended.values() if p == 1),
        "first_division_titles": sum(
            1 for cid, p in ended.items() if p == 1 and tier_by_comp.get(cid) == 1
        ),
        "consecutive_titles": _best_run(
            p == 1 for cid, p in ended_places if league.comps[cid].format == "classica"
        ),
        "podiums": sum(1 for _, p in ended_places if p <= 3),
        "seconds": sum(1 for _, p in ended_places if p == 2),
        "shuffle_podiums": sum(1 for cid, p in ended.items() if league.comps[cid].format == "shuffle" and p <= 3),
        "shuffle_best_place": min(shuffle_places) if shuffle_places else None,
        "shuffle_matches": sum(1 for m, _ in results if m.format == "shuffle"),
        "invicto_losses": min(eligible) if eligible else None,
        "shutouts": shutouts,
        "big_wins": big_wins,
        "tiebreak_set_wins": tiebreak_set_wins,
        "promotions": promotions,
        "double_promotions": double_promotions,
        "fenix": fenix,
        "first_division_editions": sum(1 for t in tier_by_comp.values() if t == 1),
        "best_attendance": streaks["nights"][1],
        "best_win_streak": streaks["wins"][1],
        "full_attendance_editions": full_editions,
        "returns": returns,
        "founder": int(founder),
        "perfect_nights": sum(1 for s in three if s == ["W", "W", "W"]),
        "comebacks": sum(1 for s in three if s == ["L", "W", "W"]),
        "distinct_partners": len(partners),
        "max_wins_with_partner": max((w for _, w in partners.values()), default=0),
        "distinct_opponents": len(opponents),
        "max_wins_vs_opponent": max((w for _, w in opponents.values()), default=0),
        "tight_pct": round(100 * sum(1 for mg in tight if mg > 0) / len(tight)) if len(tight) >= MIN_TIGHT else None,
        "teams_matches": len(teams),
        "teams_wins": sum(1 for _, r in teams if r == "W"),
        "teams_pair_wins": max(teams_pair_wins.values(), default=0),
        "teams_titles": teams_titles.get(pid, 0),
        "first_match_win": int(results[0][1] == "W") if results else 0,
    }


def _best_run(flags):
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def _classic_order(league):
    """{competition_id: index} of the ended Clássica editions in edition order; memoised on the league."""
    order = getattr(league, "classic_order", None)
    if order is None:
        ended = [c.id for c in league.comps.values() if c.format == "classica" and c.status == "ended"]
        order = league.classic_order = {cid: i for i, cid in enumerate(sorted(ended, key=league.edition_key))}
    return order


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
        "holdersLine": {
            "key": "badges.holders",
            "text": COPY["holders"][0 if len(data["holders"]) == 1 else 1].format(n=len(data["holders"])),
        },
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
