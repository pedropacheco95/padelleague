"""The player page story (GET /api/v2/players/<id>/story): every number and every sentence
of the new player page, computed from the database at request time.

Pedro's rule (2026-10-18): no generated prose. Every sentence on the page is one of the
fixed pt-PT templates in COPY below, picked by the explicit rules written next to it and
filled with computed numbers and names. Same data, same text, for any player. Edit the
wording here; edit a threshold in RULES. Nothing is stored, so the page follows every
league night.

Definitions (shared by every block)
- A player's matches are their MEMBER seats in played or walkover matches; partners and
  opponents are the other MEMBER seats of those matches (the /players/compare definition,
  so the rival block and the Comparar button agree). Substitute appearances are not part
  of the story.
- Result (win/draw/loss) is the live one (serializers.match_score: games for Clássica and
  Shuffle, set points for Teams). Counts of wins/draws/losses include every match.
- Margin (games won minus games lost) is used for the art and the game differences. It
  leaves out walkovers (no sets) and corrupt scores (any set above 15 games, e.g. 1537).
- A night (jornada) is a (group, round) of one of the player's groups that had a played
  match: present when the player had a member match in it. This is exactly the headline
  "jornadas jogadas / faltadas" of /players/<id>.
- Night date: the round date, else the earliest match time, else (Shuffle, which has no
  dates) the Tuesday counted back from the competition's end: ends_on - 7 x (last round
  number - round number). Such nights are marked estimated.
- Game order within a night: scheduled time, then match id.
- Editions run in edition-number order (then start date, then id); place is the entry's
  final place; a title is a final place of 1.

Every block is null when its minimum-data rule fails (see RULES), and the page hides it.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.orm import joinedload

from padel_league.api_v2 import serializers as ser
from padel_league.models import Player
from padel_league.api_v2.cards import _EDITION_PREFIX, competition_label, group_label
from padel_league.services.editions import edition_number
from padel_league.sql_db import db

# --- thresholds -------------------------------------------------------------------------

RULES = {
    "corrupt_set_games": 15,  # a set above this many games is a typo: out of the art
    "people_min_meetings": 9,  # carrasco / clientes need this many meetings
    "clientes_max": 2,
    "rent_min_days": 365,  # "paga a renda desde": first to last meeting at least a year apart
    "carrasco_streak_min": 3,  # "Perdeu os últimos k" from this many losses in a row
    "retired_after_days": 180,  # "não joga desde": no member match for this long
    "paradox_min_together": 6,  # partner record shown when they played this often together
    "paradox_gap_pp": 10,  # ... and won this many points less than the player's overall rate
    "rival_min_meetings": 15,
    "chemistry_min_together": 3,  # below this a partner's chemistry is 0 (neutral)
    "strangers_listed": 3,
    "archetype_min_matches": 30,
    "tight_max_margin": 2,  # "apertado": decided by 1 or 2 games
    "tight_min_matches": 15,
    "tight_trait_pct": 65,  # sangue-frio
    "rolo_margin": 5,  # a win by this many games or more
    "rolo_trait_pct": 25,  # rolo compressor: share of matches won by 5+
    "night_min_three_game": 10,  # diesel / ressuscitador need this many 3-match nights
    "diesel_gap_pp": 8,  # game 1 win% at least this far below games 2 and 3
    "comeback_trait_pct": 15,  # ressuscitador: L-W-W nights / 3-match nights
    "best_night_min_net": 1,
}

# --- copy catalogue -----------------------------------------------------------------------
# key -> template. {placeholders} are filled with computed values; (singular, plural) pairs
# are picked by the count in the same sentence.

COPY = {
    # hero
    "hero.since": "Na liga desde {since}",
    "hero.editions": ("{n} edição", "{n} edições"),
    "hero.titles": ("{n} título", "{n} títulos"),
    "hero.sub_only": ("{n} jogo como substituto", "{n} jogos como substituto"),
    "hero.table": "Ordenado por edição, da mais recente. {parts}.",
    "hero.podiums": ("{n} pódio", "{n} pódios"),
    "hero.points": "De onde vêm os {points}",
    # J1 impressão digital
    "fingerprint.note": "Um anel por edição, da {first} (centro) à {last}.",
    "fingerprint.note.one": "Um anel por edição: a {first} é a primeira.",
    "fingerprint.next": "O anel pontilhado é a {next}, ainda em branco.",
    "fingerprint.excluded": ("{n} resultado impossível fica de fora.", "{n} resultados impossíveis ficam de fora."),
    "fingerprint.caption": ("{n} anel", "{n} anéis"),
    # J2 montanha (titles first, else best place, else the count)
    "mountain.title.titles": ("{t} título em {e}", "{t} títulos em {e}"),
    "mountain.title.best": "Melhor lugar: {place}º",
    "mountain.title.count": ("{e}", "{e}"),
    "mountain.title.rookie": "A montanha começa aqui",
    "mountain.lede": "Estreia em {since}, na {tier}ª Divisão. {moves}.",
    "mountain.lede.flat": "Estreia em {since}, na {tier}ª Divisão. Sempre na mesma divisão.",
    "mountain.lede.rookie": "Estreia em {since}, na {tier}ª Divisão: {place}º lugar.",
    "mountain.lede.rookie_running": "Estreia em {since}, na {tier}ª Divisão.",
    "mountain.ups": ("{n} subida", "{n} subidas"),
    "mountain.downs": ("{n} descida", "{n} descidas"),
    "mountain.editions": ("{n} edição", "{n} edições"),
    # J3 carrascos e clientes
    "people.title": "Quem lhe ganha. Quem paga.",
    "people.carrasco.streak": "Perdeu os últimos {k} contra {name}.",
    "people.carrasco.retired": "{name} não joga desde {since}.",
    "people.carrasco.none": "Ninguém lhe ganha mais do que perde (mín. {n} encontros).",
    "people.clientes.rent": "{name} paga a renda desde {year}.",
    "people.clientes.count": "{name}: {w} vitórias em {n} encontros.",
    "people.clientes.none": "Ainda ninguém lhe paga (mín. {n} encontros).",
    "people.paradox": "Mas ao lado de {name}: {w}V {d}E {l}D. Melhor do outro lado da rede.",
    "people.carrasco.games": ("jogos em {n} encontro.", "jogos em {n} encontros."),
    # J4 constelação
    "constellation.title": "Com quem partilhou campo",
    "constellation.lede": "Perto do centro, os parceiros mais frequentes. Amarelo dá química, coral não dá.",
    "constellation.lede.strangers": "No anel de fora, os inscritos na {competition} que nunca defrontou.",
    "constellation.total": ("de {n} jogador", "de {n} jogadores"),
    "constellation.strangers": "Inscritos que nunca defrontou · {n}",
    "constellation.stranger": ("{n} jogo", "{n} jogos"),
    "constellation.bridge": "{matches} · ponte: {name}",
    # J5 rival
    "rival.title.league": "O jogo mais repetido da liga",
    "rival.title.count": "{n} encontros com {name}",
    "rival.together": "E ainda {n} jogos lado a lado: {w}V {d}E {l}D.",
    "rival.together.one": "E ainda 1 jogo lado a lado: {w}V {d}E {l}D.",
    "rival.wins": ("{n} vitória", "{n} vitórias"),
    "rival.draws": ("{n} empate · {played}", "{n} empates · {played}"),
    "rival.losses": ("{n} derrota", "{n} derrotas"),
    "rival.played": ("{n} jogo", "{n} jogos"),
    # J6 todas as noites
    "nights.title": ("{n} noite de liga", "{n} noites de liga"),
    "nights.lede": "{played}, {missed}.",
    "nights.played": ("{n} jogada", "{n} jogadas"),
    "nights.missed": ("{n} falta", "{n} faltas"),
    "nights.missed.none": "nenhuma falta",
    "nights.best": "A melhor noite: {date}",
    "nights.estimated": "As noites do Shuffle não têm data: ficam nas terças antes do fim.",
    "nights.next": "Próxima noite · {date} · {competition}",
    # J7 sequências
    "streaks.title.alive": "O que está aceso",
    "streaks.title.out": "Para reacender",
    "streaks.title.paused": "Em pausa desde {since}",
    "streaks.podiums": "Pódios seguidos",
    "streaks.wins": "Vitórias seguidas",
    "streaks.nights": "Jornadas seguidas",
    "streaks.record.now": "É o recorde da liga",
    "streaks.record.before": "Já fez {best}: recorde da liga",
    "streaks.best.now": "É o recorde pessoal · liga {record}",
    "streaks.best.before": "Recorde pessoal {best} · liga {record}",
    "streaks.none": "Ainda por estrear · liga {record}",
    "streaks.last_absence": "Faltou à J{round} da {edition} · recorde {best}",
    # J7 assinatura (rules in archetype())
    "archetype.tight": "ganhos nos jogos decididos por 1–2 ({won} de {total})",
    "archetype.rookie": ("A assinatura aparece aos {min} jogos: falta {k}.", "A assinatura aparece aos {min} jogos: faltam {k}."),
}

# Archetypes: traits in priority order; a name combines the first two that fire.
TRAITS = ("sangue_frio", "rolo", "ressuscitador", "diesel")
ARCHETYPES = {
    (): ("Equilibrista", "Joga igual do primeiro ao último jogo: nenhum traço passa a fasquia."),
    ("sangue_frio",): ("Sangue-frio", "Não treme nos jogos apertados."),
    ("rolo",): ("Rolo compressor", "Quando ganha, ganha por muitos."),
    ("ressuscitador",): ("Ressuscitador", "Perde o primeiro e ganha os dois seguintes."),
    ("diesel",): ("Diesel", "Arranca devagar e acaba a noite melhor do que começou."),
    ("sangue_frio", "rolo"): ("Rolo compressor de sangue-frio", "Ganha por muitos e não treme nos apertados."),
    ("sangue_frio", "ressuscitador"): ("Ressuscitador de sangue-frio", "Perde o primeiro, ganha os seguintes, e não treme nos apertados."),
    ("sangue_frio", "diesel"): ("Diesel de sangue-frio", "Arranca devagar e não treme nos jogos apertados."),
    ("rolo", "ressuscitador"): ("Ressuscitador demolidor", "Perde o primeiro e depois ganha por muitos."),
    ("rolo", "diesel"): ("Rolo compressor a diesel", "Arranca devagar e acaba a ganhar por muitos."),
    ("ressuscitador", "diesel"): ("Ressuscitador a diesel", "As noites dele começam mal e acabam bem."),
}

MONTHS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def say(key, **params):
    """{key, text}: the catalogue entry filled in; a (singular, plural) pair picks by `n`
    (or the first int param)."""
    template = COPY[key]
    if isinstance(template, tuple):
        n = params.get("n", next((v for v in params.values() if isinstance(v, int)), 0))
        template = template[0] if n == 1 else template[1]
    return {"key": key, "text": template.format(**params)}


def words(key, n):
    return say(key, n=n)["text"]


def month_year(d):
    return f"{MONTHS[d.month - 1]} {d.year}"


def day_month_year(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def weekday_day_month(d):
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


# --- league data (a handful of queries, the whole league) ------------------------------------


@dataclass
class Match:
    id: int
    group_id: int
    round_id: int
    round_no: int
    competition_id: int
    format: str
    tier: int
    day: date
    estimated: bool
    order: tuple
    home: list = field(default_factory=list)  # member player ids
    away: list = field(default_factory=list)
    sets: list = field(default_factory=list)  # [(home_games, away_games)]
    winner: str = None  # home | away | draw | None
    corrupt: bool = False

    def side_of(self, pid):
        return "home" if pid in self.home else "away" if pid in self.away else None

    def result(self, pid):
        side = self.side_of(pid)
        if self.winner is None or side is None:
            return None
        if self.winner == "draw":
            return "D"
        return "W" if self.winner == side else "L"

    def margin(self, pid):
        """Games won minus lost, or None when the match stays out of the art."""
        if not self.sets or self.corrupt:
            return None
        h = sum(s[0] for s in self.sets)
        a = sum(s[1] for s in self.sets)
        return h - a if self.side_of(pid) == "home" else a - h

    def scores(self, pid):
        mine = self.side_of(pid) == "home"
        return [f"{h}–{a}" if mine else f"{a}–{h}" for h, a in self.sets]

    def partners(self, pid):
        side = self.home if pid in self.home else self.away
        return [p for p in side if p != pid]

    def opponents(self, pid):
        return self.away if pid in self.home else self.home


class League:
    """Every played match with its member seats, the player memberships, entries and
    competitions — the inputs of every block."""

    def __init__(self, today):
        self.today = today
        q = lambda sql, **kw: db.session.execute(text(sql), kw).fetchall()  # noqa: E731
        self.comps = {
            r.id: r
            for r in q("select id, name, title, format, status, starts_on, ends_on from competitions")
        }
        last_round = {
            r.cid: r.n
            for r in q(
                "select s.competition_id cid, max(r.number) n from rounds r join stages s on s.id = r.stage_id group by 1"
            )
        }
        rows = q(
            """
            select m.id, m.group_id, m.round_id, m.status, m.walkover_winner, m.scheduled_at,
                   r.number round_no, r.date round_date, s.competition_id, s.number stage_no, cg.tier
            from matches m
            join rounds r on r.id = m.round_id
            join competition_groups cg on cg.id = m.group_id
            join stages s on s.id = cg.stage_id
            where m.status in ('played', 'walkover')
            """
        )
        sets = defaultdict(list)
        for r in q("select match_id, set_no, home_games, away_games, outcome from match_sets order by match_id, set_no"):
            sets[r.match_id].append(r)
        seats = defaultdict(list)
        for r in q(
            "select mp.match_id, mp.player_id, mp.side from match_participants mp "
            "join matches m on m.id = mp.match_id "
            "where m.status in ('played', 'walkover') and mp.role = 'member' and mp.player_id is not null"
        ):
            seats[r.match_id].append(r)
        # Night date: the round date, else the round's earliest match time, else estimated.
        round_first = {}
        for r in rows:
            if r.scheduled_at is not None:
                d = r.scheduled_at.date()
                round_first[r.round_id] = min(round_first.get(r.round_id, d), d)
        self.matches = {}
        for r in rows:
            comp = self.comps[r.competition_id]
            day, estimated = r.round_date or round_first.get(r.round_id), False
            if day is None and comp.ends_on is not None:
                day = comp.ends_on - timedelta(days=7 * (last_round.get(r.competition_id, r.round_no) - r.round_no))
                estimated = True
            if day is None:
                day = comp.starts_on or date(1970, 1, 1)
                estimated = True
            m = Match(
                id=r.id,
                group_id=r.group_id,
                round_id=r.round_id,
                round_no=r.round_no,
                competition_id=r.competition_id,
                format=comp.format,
                tier=r.tier,
                day=day,
                estimated=estimated,
                order=(day, r.scheduled_at or datetime.combine(day, datetime.min.time()), r.id),
            )
            for s in seats[r.id]:
                (m.home if s.side == "home" else m.away).append(s.player_id)
            m.home.sort()
            m.away.sort()
            ms = sets[r.id]
            m.sets = [(s.home_games or 0, s.away_games or 0) for s in ms]
            m.corrupt = any(max(h, a) > RULES["corrupt_set_games"] for h, a in m.sets)
            obj = SimpleNamespace(status=r.status, walkover_winner=r.walkover_winner, sets=ms)
            m.winner = ser.match_score(obj, comp.format)[2]
            if r.status == "walkover":
                m.sets = []
            self.matches[r.id] = m
        self.by_player = defaultdict(list)
        for m in sorted(self.matches.values(), key=lambda m: m.order):
            if m.winner is None:
                continue
            for pid in m.home + m.away:
                self.by_player[pid].append(m)
        players = Player.query.options(joinedload(Player.picture)).all()
        self.players = {p.id: SimpleNamespace(name=p.name, status=p.status) for p in players}
        self.refs = {p.id: ser.player_ref(p) for p in players}
        self.member_groups = defaultdict(set)
        for r in q("select e.player_id, gm.group_id from group_members gm join entries e on e.id = gm.entry_id"):
            self.member_groups[r.player_id].add(r.group_id)
        self.entries = defaultdict(list)
        for r in q("select id, player_id, competition_id, status, final_place from entries"):
            self.entries[r.player_id].append(r)
        self.groups = {
            r.id: r
            for r in q(
                "select cg.id, cg.stage_id, cg.tier, cg.name, s.competition_id, "
                "(select count(*) from group_members gm where gm.group_id = cg.id) size "
                "from competition_groups cg join stages s on s.id = cg.stage_id"
            )
        }
        # The night date of every group round with a played match.
        self.group_rounds = defaultdict(dict)  # group -> round -> (day, round_no, competition, estimated)
        for m in self.matches.values():
            known = self.group_rounds[m.group_id].get(m.round_id)
            if known is None or (m.day, m.round_no) < known[:2]:
                self.group_rounds[m.group_id][m.round_id] = (m.day, m.round_no, m.competition_id, m.estimated)

    # -- per player helpers --

    def results(self, pid):
        return [(m, m.result(pid)) for m in self.by_player.get(pid, [])]

    def edition_key(self, cid):
        c = self.comps[cid]
        return (edition_number(c.name) or 0, c.starts_on or date.min, cid)

    def edition_short(self, cid):
        """"5ª"; a competition without a number gets its initials ("Play Off" -> "PO")."""
        name = self.comps[cid].name or ""
        n = edition_number(name)
        if n is not None:
            return f"{n}ª"
        return "".join(w[0] for w in name.split() if w[:1].isalnum())[:3].upper()

    def nights(self, pid):
        """[(day, round_no, competition_id, group_id, present, estimated)] chronological."""
        present = {(m.group_id, m.round_id) for m in self.by_player.get(pid, [])}
        out = []
        for g in self.member_groups.get(pid, ()):
            for rid, (day, rno, cid, est) in self.group_rounds.get(g, {}).items():
                out.append((day, rno, cid, g, (g, rid) in present, est, rid))
        out.sort(key=lambda n: (n[0], n[1], n[6]))
        return out

    def ended_places(self, pid):
        """[(competition_id, place)] for ended competitions, in edition order."""
        rows = [
            (e.competition_id, e.final_place)
            for e in self.entries.get(pid, [])
            if self.comps[e.competition_id].status == "ended" and e.final_place is not None
        ]
        return sorted(rows, key=lambda r: self.edition_key(r[0]))

    def ref(self, pid):
        return dict(self.refs[pid])


def runs(flags):
    """(current trailing run, best run) of True values."""
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return cur, best


def h2h(league, a, b):
    """a's record against b and alongside b (member seats, /players/compare)."""
    vs = {"played": 0, "wins": 0, "draws": 0, "losses": 0, "diff": 0, "first": None, "last": None, "trail": []}
    tog = {"played": 0, "wins": 0, "draws": 0, "losses": 0}
    for m, res in league.results(a):
        if res is None:
            continue
        key = {"W": "wins", "D": "draws", "L": "losses"}[res]
        if b in m.partners(a):
            tog["played"] += 1
            tog[key] += 1
        elif b in m.opponents(a):
            vs["played"] += 1
            vs[key] += 1
            vs["diff"] += m.margin(a) or 0
            vs["first"] = vs["first"] or m.day
            vs["last"] = m.day
            vs["trail"].append(res)
    return vs, tog


# --- blocks -----------------------------------------------------------------------------------


def rings(league, pid):
    """One ring per edition the player played (edition order): the art matches' margins."""
    by_comp = defaultdict(list)
    for m in league.by_player.get(pid, []):
        by_comp[m.competition_id].append(m)
    places = {e.competition_id: e.final_place for e in league.entries.get(pid, [])}
    out = []
    for cid in sorted(by_comp, key=league.edition_key):
        ms = by_comp[cid]
        tiers = [m.tier for m in ms if m.tier is not None]
        place = places.get(cid) if league.comps[cid].status == "ended" else None
        out.append(
            {
                "competitionId": cid,
                "edition": league.edition_short(cid),
                "format": league.comps[cid].format,
                "tier": min(tiers) if tiers and league.comps[cid].format == "classica" else None,
                "place": place,
                "title": place == 1,
                "matches": [[m.margin(pid), m.id] for m in ms if m.margin(pid) is not None],
            }
        )
    return out


def next_competition(league, pid):
    """The competition the player is entered in with the next night: (competition_id, date) or None."""
    best = None
    open_comps = [
        e.competition_id
        for e in league.entries.get(pid, [])
        if league.comps[e.competition_id].status != "ended" and e.status == "active"
    ]
    if not open_comps:
        return None
    rows = db.session.execute(
        text(
            """
            select s.competition_id cid, min(coalesce(r.date, m.scheduled_at::date)) d
            from stages s join rounds r on r.stage_id = s.id
            left join matches m on m.round_id = r.id and m.status not in ('played', 'walkover')
            where s.competition_id = any(:ids) and coalesce(r.date, m.scheduled_at::date) >= :today
            group by 1
            """
        ),
        {"ids": open_comps, "today": league.today},
    ).fetchall()
    dated = {r.cid: r.d for r in rows if r.d is not None}
    for cid in open_comps:
        d = dated.get(cid)
        starts = league.comps[cid].starts_on
        if d is None and starts is not None and starts >= league.today:
            d = starts
        if d is not None and (best is None or (d, cid) < best[::-1]):
            best = (cid, d)
    return best


def short_label(league, cid):
    """The tournament without its edition: "Teams 2026/27"."""
    c = league.comps[cid]
    label = competition_label(SimpleNamespace(name=c.name, title=c.title, id=cid), _top_group_name(league, cid))
    if " - " in label:
        return label.split(" - ", 1)[1]
    # No title and no divisions yet (Teams before its draw): the name without its edition.
    return _EDITION_PREFIX.sub("", c.name or "").strip() or ser.FORMAT_LABELS.get(c.format, c.format)


def _top_group_name(league, cid):
    groups = [g for g in league.groups.values() if g.competition_id == cid]
    groups.sort(key=lambda g: (g.tier if g.tier is not None else 99, g.id))
    return groups[0].name if groups else None


def full_label(league, cid, group_id=None):
    c = league.comps[cid]
    comp = SimpleNamespace(name=c.name, title=c.title, id=cid)
    if c.format == "classica" and group_id in league.groups:
        return group_label(comp, league.groups[group_id].name)
    return competition_label(comp, _top_group_name(league, cid))


def hero(league, pid):
    entries = [e for e in league.entries.get(pid, []) if league.comps[e.competition_id].status != "planned"]
    titles = sum(1 for cid, place in league.ended_places(pid) if place == 1)
    mine = league.by_player.get(pid, [])
    since = mine[0].day if mine else None
    parts = []
    if since:
        parts.append(say("hero.since", since=day_month_year(since))["text"])
    if entries:
        parts.append(words("hero.editions", len(entries)))
    if titles:
        parts.append(words("hero.titles", titles))
    if not mine:
        subs = db.session.execute(
            text(
                "select count(*) from match_participants mp join matches m on m.id = mp.match_id "
                "where mp.player_id = :pid and mp.role = 'substitute' and m.status in ('played', 'walkover')"
            ),
            {"pid": pid},
        ).scalar()
        if subs:
            parts.append(words("hero.sub_only", subs))
    ended = league.ended_places(pid)
    table = [words("hero.editions", len(entries))] if entries else []
    podiums = sum(1 for _, place in ended if place <= 3)
    if podiums:
        table.append(words("hero.podiums", podiums))
    if titles:
        table.append(words("hero.titles", titles))
    return {
        "since": ser.iso_date(since),
        "tableNote": say("hero.table", parts=" · ".join(table)) if table else None,
        "editions": len(entries),
        "titles": titles,
        "line": {"key": "hero", "text": " · ".join(parts)} if parts else None,
    }


def mountain(league, pid, next_comp):
    """Absolute position per edition: members of the higher divisions of that stage + place."""
    places = {e.competition_id: e for e in league.entries.get(pid, [])}
    my_groups = league.member_groups.get(pid, set())
    points = []
    for cid in sorted(places, key=league.edition_key):
        comp = league.comps[cid]
        if comp.status == "planned" or comp.format == "teams" and places[cid].final_place is None:
            continue
        e = places[cid]
        group = next((league.groups[g] for g in my_groups if g in league.groups and league.groups[g].competition_id == cid), None)
        if comp.format == "classica" and group is not None:
            above = sum(
                g.size for g in league.groups.values() if g.stage_id == group.stage_id and (g.tier or 0) < (group.tier or 0)
            )
            top = sum(g.size for g in league.groups.values() if g.stage_id == group.stage_id and (g.tier or 0) == 1)
            tier = group.tier
        else:
            above, top, tier = 0, None, None
        place = e.final_place if comp.status == "ended" else None
        points.append(
            {
                "competitionId": cid,
                "edition": league.edition_short(cid),
                "label": full_label(league, cid, group.id if group else None),
                "format": comp.format,
                "tier": tier,
                "place": place,
                "position": above + place if place is not None else None,
                "topSize": top,
                "title": place == 1,
                "change": None,
            }
        )
    classic = [p for p in points if p["format"] == "classica" and p["tier"] is not None]
    if not classic:
        return None
    ups = downs = 0
    for prev, cur in zip(classic, classic[1:]):
        if cur["tier"] < prev["tier"]:
            cur["change"], ups = "up", ups + 1
        elif cur["tier"] > prev["tier"]:
            cur["change"], downs = "down", downs + 1
    mine = league.by_player.get(pid, [])
    since = month_year(mine[0].day) if mine else month_year(league.comps[classic[0]["competitionId"]].starts_on or league.today)
    ended = [p for p in points if p["place"] is not None]
    titles = sum(1 for p in ended if p["place"] == 1)
    n_ed = words("mountain.editions", len(points))
    if len(points) == 1:
        first = classic[0]
        title = say("mountain.title.rookie")
        if first["place"] is not None:
            lede = say("mountain.lede.rookie", since=since, tier=first["tier"], place=first["place"])
        else:
            lede = say("mountain.lede.rookie_running", since=since, tier=first["tier"])
    else:
        if titles:
            title = say("mountain.title.titles", t=titles, e=n_ed)
        elif ended and min(p["place"] for p in ended) <= 3:
            title = say("mountain.title.best", place=min(p["place"] for p in ended))
        else:
            title = say("mountain.title.count", e=n_ed, n=len(points))
        moves = [words(k, n) for k, n in (("mountain.ups", ups), ("mountain.downs", downs)) if n]
        if moves:
            lede = say("mountain.lede", since=since, tier=classic[0]["tier"], moves=" e ".join(moves))
        else:
            lede = say("mountain.lede.flat", since=since, tier=classic[0]["tier"])
    nxt = None
    if next_comp:
        nxt = {"edition": league.edition_short(next_comp[0]), "label": short_label(league, next_comp[0])}
    return {"title": title, "lede": lede, "points": points, "next": nxt, "ups": ups, "downs": downs}


def opponents_table(league, pid):
    """{opponent: h2h dict} and {partner: record} over the player's member matches."""
    opp = defaultdict(lambda: {"played": 0, "wins": 0, "draws": 0, "losses": 0, "diff": 0, "first": None, "last": None, "trail": []})
    par = defaultdict(lambda: {"played": 0, "wins": 0, "draws": 0, "losses": 0})
    for m, res in league.results(pid):
        if res is None:
            continue
        key = {"W": "wins", "D": "draws", "L": "losses"}[res]
        for p in m.partners(pid):
            par[p]["played"] += 1
            par[p][key] += 1
        for o in m.opponents(pid):
            r = opp[o]
            r["played"] += 1
            r[key] += 1
            r["diff"] += m.margin(pid) or 0
            r["first"] = r["first"] or m.day
            r["last"] = m.day
            r["trail"].append(res)
    return opp, par


def last_played(league, pid):
    ms = league.by_player.get(pid, [])
    return ms[-1].day if ms else None


def record(r):
    return {k: r[k] for k in ("played", "wins", "draws", "losses")}


def people(league, pid, opp, par):
    n_min = RULES["people_min_meetings"]
    eligible = [(o, r) for o, r in opp.items() if r["played"] >= n_min and o in league.players]
    if not eligible:
        return None
    worst = sorted(
        [(o, r) for o, r in eligible if r["diff"] < 0 and r["losses"] > r["wins"]], key=lambda x: (x[1]["diff"], x[0])
    )
    best = sorted(
        [(o, r) for o, r in eligible if r["diff"] > 0 and r["wins"] > r["losses"]], key=lambda x: (-x[1]["diff"], x[0])
    )[: RULES["clientes_max"]]
    carrasco = carrasco_line = None
    if worst:
        o, r = worst[0]
        name = league.players[o].name
        streak = 0
        for res in reversed(r["trail"]):
            if res != "L":
                break
            streak += 1
        seen = last_played(league, o)
        if streak >= RULES["carrasco_streak_min"]:
            carrasco_line = say("people.carrasco.streak", k=streak, name=name)
        elif seen and (league.today - seen).days > RULES["retired_after_days"]:
            carrasco_line = say("people.carrasco.retired", name=name, since=month_year(seen))
        carrasco = {
            "player": league.ref(o),
            **record(r),
            "diff": r["diff"],
            "lossStreak": streak,
            "gamesLine": say("people.carrasco.games", n=r["played"]),
        }
    else:
        carrasco_line = say("people.carrasco.none", n=n_min)
    clientes = [{"player": league.ref(o), **record(r), "diff": r["diff"]} for o, r in best]
    clientes_line = paradox = None
    if best:
        o, r = best[0]
        name = league.players[o].name
        if r["first"] and (r["last"] - r["first"]).days >= RULES["rent_min_days"]:
            clientes_line = say("people.clientes.rent", name=name, year=r["first"].year)
        else:
            clientes_line = say("people.clientes.count", name=name, w=r["wins"], n=r["played"])
        together = par.get(o)
        overall = overall_rate(league, pid)
        if together and together["played"] >= RULES["paradox_min_together"]:
            rate = 100 * together["wins"] / together["played"]
            if rate < overall - RULES["paradox_gap_pp"]:
                paradox = say("people.paradox", name=name, w=together["wins"], d=together["draws"], l=together["losses"])
    else:
        clientes_line = say("people.clientes.none", n=n_min)
    return {
        "title": say("people.title"),
        "carrasco": carrasco,
        "clientes": clientes,
        "carrascoLine": carrasco_line,
        "clientesLine": clientes_line,
        "paradox": paradox,
    }


def overall_rate(league, pid):
    res = [r for _, r in league.results(pid) if r is not None]
    return 100 * res.count("W") / len(res) if res else 0.0


def met_graph(league):
    """player -> set of players met (partner or opponent), members only."""
    if getattr(league, "graph", None) is not None:
        return league.graph
    g = league.graph = defaultdict(set)
    for m in league.matches.values():
        if m.winner is None:
            continue
        seated = m.home + m.away
        for a in seated:
            for b in seated:
                if a != b:
                    g[a].add(b)
    return g


def constellation(league, pid, opp, par, next_comp, rival_id, carrasco_id):
    if not par:
        return None
    overall = overall_rate(league, pid)
    partners = []
    for p, r in sorted(par.items(), key=lambda x: (-x[1]["played"], x[0])):
        chem = 0
        if r["played"] >= RULES["chemistry_min_together"]:
            chem = round(100 * r["wins"] / r["played"] - overall)
        partners.append({"player": league.ref(p), "together": r["played"], "chemistry": chem})
    only_opp = [
        {"player": league.ref(o), "met": r["played"]}
        for o, r in sorted(opp.items(), key=lambda x: (-x[1]["played"], x[0]))
        if o not in par
    ]
    graph = met_graph(league)
    league_ids = {p for p in graph if league.players[p].status != "external"}
    dist = {pid: 0}
    frontier = [pid]
    while frontier:
        nxt = []
        for a in frontier:
            for b in sorted(graph.get(a, ())):
                if b not in dist and b in league_ids:
                    dist[b] = dist[a] + 1
                    nxt.append(b)
        frontier = nxt
    met = {p for p in graph.get(pid, ()) if p in league_ids}
    strangers = None
    if next_comp:
        cid = next_comp[0]
        entrants = {
            e.player_id
            for es in league.entries.values()
            for e in es
            if e.competition_id == cid and e.status == "active" and league.players[e.player_id].status != "external"
        }
        never = sorted(entrants - met - {pid}, key=lambda s: (-len(league.by_player.get(s, [])), s))
        listed = []
        for s in never[: RULES["strangers_listed"]]:
            bridges = []
            for b in graph.get(pid, ()) & graph.get(s, set()):
                with_me = (opp.get(b, {}).get("played", 0)) + (par.get(b, {}).get("played", 0))
                bridges.append((-min(with_me, _met_count(league, b, s)), b))
            bridge = league.ref(sorted(bridges)[0][1]) if bridges else None
            n = len(league.by_player.get(s, []))
            line = words("constellation.stranger", n)
            if bridge:
                line = say("constellation.bridge", matches=line, name=bridge["name"])["text"]
            listed.append({"player": league.ref(s), "matches": n, "bridge": bridge, "line": {"key": "constellation.stranger", "text": line}})
        strangers = {
            "count": len(never),
            "competitionLabel": full_label(league, cid),
            "title": say("constellation.strangers", n=len(never)),
            "list": listed,
            "lede": say("constellation.lede.strangers", competition=short_label(league, cid)),
        }
    return {
        "title": say("constellation.title"),
        "lede": say("constellation.lede"),
        "partners": partners,
        "opponents": only_opp,
        "strangers": strangers,
        "met": len(met),
        "total": len(league_ids - {pid}),
        "totalLine": say("constellation.total", n=len(league_ids - {pid})),
        "degree2": sum(1 for d in dist.values() if d == 2),
        "degree3": sum(1 for d in dist.values() if d == 3),
        "rivalId": rival_id,
        "carrascoId": carrasco_id,
    }


def _met_count(league, a, b):
    return sum(1 for m in league.by_player.get(a, []) if b in m.home or b in m.away)


def league_max_pair(league):
    if getattr(league, "max_pair", None) is not None:
        return league.max_pair
    counts = defaultdict(int)
    for m in league.matches.values():
        if m.winner is None:
            continue
        for a in m.home:
            for b in m.away:
                counts[(min(a, b), max(a, b))] += 1
    league.max_pair = max(counts.values()) if counts else 0
    return league.max_pair


def rival(league, pid, opp):
    eligible = [(o, r) for o, r in opp.items() if r["played"] >= RULES["rival_min_meetings"] and o in league.players]
    if not eligible:
        return None
    o, r = sorted(eligible, key=lambda x: (-x[1]["played"], x[0]))[0]
    vs, tog = h2h(league, pid, o)
    name = league.players[o].name
    if vs["played"] >= league_max_pair(league):
        title = say("rival.title.league")
    else:
        title = say("rival.title.count", n=vs["played"], name=name)
    together = None
    if tog["played"] == 1:
        together = say("rival.together.one", w=tog["wins"], d=tog["draws"], l=tog["losses"])
    elif tog["played"] > 1:
        together = say("rival.together", n=tog["played"], w=tog["wins"], d=tog["draws"], l=tog["losses"])
    theirs = rings(league, o)
    return {
        "player": league.ref(o),
        "title": title,
        **record(vs),
        "together": tog,
        "togetherLine": together,
        "split": [
            say("rival.wins", n=vs["wins"]),
            say("rival.draws", n=vs["draws"], played=words("rival.played", vs["played"])),
            say("rival.losses", n=vs["losses"]),
        ],
        "rings": theirs,
        "titles": sum(1 for x in theirs if x["title"]),
        "caption": ring_caption(theirs),
    }


def nights(league, pid, next_comp):
    all_nights = league.nights(pid)
    if not all_nights:
        return None
    by_night = defaultdict(list)
    for m in league.by_player.get(pid, []):
        by_night[(m.group_id, m.round_id)].append(m)
    cells = []
    best = None
    for day, rno, cid, gid, present, est, rid in all_nights:
        ms = by_night.get((gid, rid), [])
        margins = [m.margin(pid) for m in ms if m.margin(pid) is not None]
        net = sum(margins) if present else None
        cells.append(
            {"date": day.isoformat(), "net": net, "played": present, "estimated": est, "competitionId": cid, "round": rno}
        )
        if present and margins and (best is None or net > best[0]):
            best = (net, day, cid, gid, ms)
    played = sum(1 for c in cells if c["played"])
    missed = len(cells) - played
    missed_words = say("nights.missed.none")["text"] if missed == 0 else words("nights.missed", missed)
    best_json = None
    if best and best[0] >= RULES["best_night_min_net"]:
        net, day, cid, gid, ms = best
        best_json = {
            "date": day.isoformat(),
            "net": net,
            "label": full_label(league, cid, gid),
            "scores": [", ".join(m.scores(pid)) for m in ms if m.sets],
            "line": say("nights.best", date=day_month_year(day)),
        }
    nxt = None
    if next_comp:
        cid, d = next_comp
        nxt = {
            "date": d.isoformat(),
            "competitionId": cid,
            "line": say("nights.next", date=weekday_day_month(d), competition=short_label(league, cid)),
        }
    return {
        "title": say("nights.title", n=len(cells)),
        "lede": say("nights.lede", played=words("nights.played", played), missed=missed_words),
        "played": played,
        "missed": missed,
        "cells": cells,
        "best": best_json,
        "next": nxt,
        "estimatedNote": say("nights.estimated") if any(c["estimated"] for c in cells) else None,
    }


def streak_values(league, pid):
    """{key: (current, best)} for podiums, wins and nights."""
    podiums = runs([place <= 3 for _, place in league.ended_places(pid)])
    wins = runs([r == "W" for _, r in league.results(pid) if r is not None])
    attendance = runs([n[4] for n in league.nights(pid)])
    return {"podiums": podiums, "wins": wins, "nights": attendance}


def league_records(league):
    if getattr(league, "records", None) is not None:
        return league.records
    rec = {"podiums": 0, "wins": 0, "nights": 0}
    for pid in set(league.by_player) | set(league.entries):
        if pid not in league.players or league.players[pid].status == "external":
            continue
        for k, (_, best) in streak_values(league, pid).items():
            rec[k] = max(rec[k], best)
    league.records = rec
    return rec


def streaks(league, pid, next_comp):
    if not league.by_player.get(pid):
        return None
    values = streak_values(league, pid)
    records = league_records(league)
    items = []
    for key in ("podiums", "wins", "nights"):
        cur, best = values[key]
        rec = records[key]
        if best == 0:
            line = say("streaks.none", record=rec)
        elif key == "nights" and cur == 0:
            last = next((n for n in reversed(league.nights(pid)) if not n[4]), None)
            line = say("streaks.last_absence", round=last[1], edition=league.edition_short(last[2]), best=best)
        elif best and best >= rec:
            line = say("streaks.record.now") if cur == best else say("streaks.record.before", best=best)
        elif best and cur == best:
            line = say("streaks.best.now", record=rec)
        else:
            line = say("streaks.best.before", best=best, record=rec)
        items.append(
            {"key": key, "label": COPY[f"streaks.{key}"], "current": cur, "best": best, "record": rec, "alive": cur > 0, "line": line}
        )
    # Away for longer than retired_after_days and not entered in what comes next: paused.
    last = league.nights(pid)[-1][0] if league.nights(pid) else league.by_player[pid][-1].day
    if (league.today - last).days > RULES["retired_after_days"] and next_comp is None:
        for i in items:
            i["alive"] = False
        title = say("streaks.title.paused", since=month_year(last))
    else:
        title = say("streaks.title.alive" if any(i["alive"] for i in items) else "streaks.title.out")
    return {"title": title, "items": items}


def archetype(league, pid):
    mine = league.by_player.get(pid, [])
    art = [(m, m.margin(pid)) for m in mine if m.margin(pid) is not None]
    if not mine:
        return None
    skyline = [0] * 21
    for _, mg in art:
        skyline[max(-10, min(10, mg)) + 10] += 1
    t = RULES["tight_max_margin"]
    tight = [mg for _, mg in art if 0 < abs(mg) <= t]
    tight_won = sum(1 for mg in tight if mg > 0)
    big_wins = sum(1 for _, mg in art if mg >= RULES["rolo_margin"])
    # Clássica nights of three matches, in game order.
    by_night = defaultdict(list)
    for m in mine:
        if m.format == "classica":
            by_night[(m.group_id, m.round_id)].append(m)
    three = [[m.result(pid) for m in sorted(ms, key=lambda m: m.order)] for ms in by_night.values() if len(ms) == 3]
    perfect = sum(1 for s in three if s == ["W", "W", "W"])
    comebacks = sum(1 for s in three if s == ["L", "W", "W"])
    diesel = None
    if three:
        diesel = [round(100 * sum(1 for s in three if s[i] == "W") / len(three)) for i in range(3)]
    traits = {
        "tight": {
            "won": tight_won,
            "total": len(tight),
            "pct": round(100 * tight_won / len(tight)) if tight else None,
            "line": say("archetype.tight", won=tight_won, total=len(tight)),
        },
        "diesel": diesel,
        "perfectNights": perfect,
        "comebacks": comebacks,
        "nightsOfThree": len(three),
        "bigWins": big_wins,
    }
    n = len(art)
    if n < RULES["archetype_min_matches"]:
        k = RULES["archetype_min_matches"] - n
        return {
            "key": None,
            "name": None,
            "line": say("archetype.rookie", min=RULES["archetype_min_matches"], k=k, n=k),
            "matches": n,
            "skyline": skyline,
            "traits": traits,
        }
    fired = []
    if len(tight) >= RULES["tight_min_matches"] and 100 * tight_won / len(tight) >= RULES["tight_trait_pct"]:
        fired.append("sangue_frio")
    if 100 * big_wins / n >= RULES["rolo_trait_pct"]:
        fired.append("rolo")
    if len(three) >= RULES["night_min_three_game"]:
        if 100 * comebacks / len(three) >= RULES["comeback_trait_pct"]:
            fired.append("ressuscitador")
        g1, g2, g3 = (sum(1 for s in three if s[i] == "W") / len(three) * 100 for i in range(3))
        if g1 <= (g2 + g3) / 2 - RULES["diesel_gap_pp"]:
            fired.append("diesel")
    key = tuple(t for t in TRAITS if t in fired)[:2]
    name, reading = ARCHETYPES[key]
    return {
        "key": "+".join(key) or "equilibrista",
        "name": name,
        "line": {"key": f"archetype.{'+'.join(key) or 'equilibrista'}", "text": reading},
        "matches": n,
        "skyline": skyline,
        "traits": traits,
    }


# The league data is reused while nothing it reads has changed: VERSION_SQL fingerprints
# every table League reads, so a result write, an edition change or a rename gives a new
# key and the next request reloads. Keyed by the day too ("não joga desde" moves with it).
VERSION_SQL = """
select md5(concat_ws('|',
  (select count(*) || ':' || coalesce(max(updated_at)::text, '') || ':' || coalesce(sum(id), 0)
     || ':' || coalesce(string_agg(status || coalesce(walkover_winner, ''), '' order by id), '') from matches),
  (select count(*) || ':' || coalesce(sum(match_id * 7 + set_no * 131 + coalesce(home_games, 0) * 31
     + coalesce(away_games, 0) * 17), 0) || coalesce(string_agg(outcome, '' order by match_id, set_no), '') from match_sets),
  (select count(*) || ':' || coalesce(sum(match_id * 3 + player_id * 5 + slot), 0)
     || coalesce(string_agg(side || role, '' order by id), '') from match_participants),
  (select count(*) || ':' || coalesce(string_agg(id || ':' || player_id || ':' || competition_id || ':' || status
     || ':' || coalesce(final_place, 0), ',' order by id), '') from entries),
  (select count(*) || ':' || coalesce(sum(id * 3 + group_id * 7 + entry_id), 0) from group_members),
  (select string_agg(id || ':' || stage_id || ':' || coalesce(tier, 0) || ':' || coalesce(name, ''), ',' order by id) from competition_groups),
  (select string_agg(id || ':' || number || ':' || coalesce(date::text, ''), ',' order by id) from rounds),
  (select string_agg(id || ':' || competition_id || ':' || number, ',' order by id) from stages),
  (select string_agg(id || ':' || coalesce(name, '') || ':' || coalesce(title, '') || ':' || format || ':' || status
     || ':' || coalesce(starts_on::text, '') || ':' || coalesce(ends_on::text, ''), ',' order by id) from competitions),
  (select string_agg(id || ':' || coalesce(name, '') || ':' || coalesce(full_name, '') || ':' || coalesce(status, '')
     || ':' || coalesce(picture_id, 0) || ':' || coalesce(picture_path, ''), ',' order by id) from players)
))
"""
_cache = {}


def league_for(today):
    key = (today, db.session.execute(text(VERSION_SQL)).scalar())
    league = _cache.get(key)
    if league is None:
        league = League(today)
        _cache.clear()
        _cache[key] = league
    return league


def ring_caption(rs):
    """"18 anéis · 4 títulos"."""
    titles = sum(1 for r in rs if r["title"])
    parts = [words("fingerprint.caption", len(rs))] + ([words("hero.titles", titles)] if titles else [])
    return {"key": "fingerprint.caption", "text": " · ".join(parts)}


def story(player_id, today=None, ranking_points=None):
    league = league_for(today or date.today())
    pid = player_id
    mine = league.by_player.get(pid, [])
    next_comp = next_competition(league, pid)
    opp, par = opponents_table(league, pid)
    ppl = people(league, pid, opp, par)
    riv = rival(league, pid, opp)
    my_rings = rings(league, pid)
    fp = None
    if mine:
        excluded = sum(1 for m in mine if m.margin(pid) is None)
        nxt = None
        if next_comp:
            nxt = {"edition": league.edition_short(next_comp[0]), "label": short_label(league, next_comp[0])}
        if len(my_rings) == 1:
            note = [say("fingerprint.note.one", first=my_rings[0]["edition"])["text"]]
        else:
            note = [say("fingerprint.note", first=my_rings[0]["edition"], last=my_rings[-1]["edition"])["text"]]
        if nxt:
            note.append(say("fingerprint.next", next=nxt["label"])["text"])
        if excluded:
            note.append(words("fingerprint.excluded", excluded))
        fp = {
            "rings": my_rings,
            "excluded": excluded,
            "next": nxt,
            "note": {"key": "fingerprint.note", "text": " ".join(note)},
            "caption": ring_caption(my_rings),
        }
    return {
        "playerId": pid,
        "today": league.today.isoformat(),
        "hero": {
            **hero(league, pid),
            "pointsLine": say("hero.points", points=round(ranking_points)) if ranking_points else None,
        },
        "archetype": archetype(league, pid),
        "fingerprint": fp,
        "mountain": mountain(league, pid, next_comp),
        "people": ppl,
        "constellation": constellation(
            league,
            pid,
            opp,
            par,
            next_comp,
            riv["player"]["id"] if riv else None,
            ppl["carrasco"]["player"]["id"] if ppl and ppl["carrasco"] else None,
        ),
        "rival": riv,
        "nights": nights(league, pid, next_comp),
        "streaks": streaks(league, pid, next_comp),
    }
