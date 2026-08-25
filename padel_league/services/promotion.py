"""Work out next edition's divisions from the last one's standings.

The base rule is 2 up / 2 down at every boundary. Withdrawals complicate it,
because a player who leaves takes a slot out of the division they *would have
been in* next edition — not the one they were in. A 1º placer who withdraws
leaves the hole one division up; an 8º placer leaves it one division down.

Each hole is then filled by working down a ladder of candidate pairs, as
specified by the league:

    holes 1 and 2  ->  the 7º of this division  and  the 3º of the one below
    holes 3 and 4  ->  the 8º of this division  and  the 4º of the one below
    ...and so on, stepping one place further out each time.

Within a pair: an *even* number of remaining holes takes both candidates; an
*odd* number takes whichever has more appearances last edition, tie broken by
career appearances. Either way the division below ends up one short for every
player taken, so the process repeats down the ladder — which is why holes
cascade all the way to the bottom division, where newcomers fill them.

If both candidates in a pair are unavailable (withdrawn, or already moved), the
next pair down is tried. The league's rule does not spell this out; it came up
the first time it was applied, when both the 7º of the 4ª and the 3º of the 5ª
had withdrawn.
"""

MAX_PAIR_STEPS = 6


class PromotionError(Exception):
    """The layout could not be computed."""


def _key(standing):
    return (standing["appearances"], standing.get("career_appearances", 0))


def next_edition_layout(standings, withdrawn=(), reserved=None, size=8):
    """Return (layout, decisions).

    `standings` is a flat list of dicts with player_id, division (1 = top),
    place (1..size) and appearances, plus optional career_appearances.
    `withdrawn` is player ids that are not coming back.
    `reserved` maps division -> number of slots being filled by incoming
    players; those holes are not cascaded, because someone is already taking
    them.

    `layout` maps division -> list of player ids continuing in it. Divisions
    below `size` are the ones incoming players must fill.
    """
    withdrawn = set(withdrawn)
    reserved = dict(reserved or {})

    by_division = {}
    for s in standings:
        by_division.setdefault(s["division"], {})[s["place"]] = s
    if not by_division:
        raise PromotionError("no standings given")

    divisions = sorted(by_division)
    bottom = divisions[-1]

    for d in divisions:
        missing = set(range(1, size + 1)) - set(by_division[d])
        if missing:
            raise PromotionError(f"division {d} is missing places {sorted(missing)}")

    # Base 2-up / 2-down.
    dest = {d: [] for d in divisions}
    for d in divisions:
        for place, s in sorted(by_division[d].items()):
            if place <= 2:
                target = d - 1 if d > divisions[0] else d
            elif place >= size - 1:
                target = d + 1 if d < bottom else d
            else:
                target = d
            dest[target].append(s)

    for d in divisions:
        dest[d] = [s for s in dest[d] if s["player_id"] not in withdrawn]

    decisions = []
    for d in divisions:
        if d == bottom:
            break
        holes = size - len(dest[d]) - reserved.get(d, 0)
        step = 0
        while holes > 0 and step < MAX_PAIR_STEPS:
            up = by_division[d].get(size - 1 + step)  # 7º, 8º, ...
            down = by_division[d + 1].get(3 + step)  # 3º, 4º, ...
            up = up if up in dest[d + 1] else None
            down = down if down in dest[d + 1] else None
            candidates = [c for c in (up, down) if c is not None]
            if not candidates:
                step += 1
                continue

            if holes >= 2 and len(candidates) == 2:
                picks = candidates
            elif len(candidates) == 1:
                picks = candidates
            else:
                picks = [max(candidates, key=_key)]

            for pick in picks:
                dest[d + 1].remove(pick)
                dest[d].append(pick)
                other = [c for c in candidates if c is not pick]
                decisions.append(
                    {
                        "division": d,
                        "player_id": pick["player_id"],
                        "role": (
                            f"{size - 1 + step}º of {d} not relegated"
                            if pick is up
                            else f"{3 + step}º of {d + 1} promoted"
                        ),
                        "reason": (
                            "two holes, both candidates take one"
                            if len(picks) == 2
                            else (
                                "only candidate available"
                                if not other
                                else f"{pick['appearances']} appearances vs "
                                f"{other[0]['appearances']}"
                                + (
                                    " (tie broken on career appearances "
                                    f"{pick.get('career_appearances', 0)} vs "
                                    f"{other[0].get('career_appearances', 0)})"
                                    if pick["appearances"] == other[0]["appearances"]
                                    else ""
                                )
                            )
                        ),
                    }
                )
            holes -= len(picks)
            step += 1

    layout = {d: [s["player_id"] for s in dest[d]] for d in divisions}
    return layout, decisions


def vacancies(layout, reserved=None, size=8):
    """How many slots each division still needs filling by incoming players."""
    reserved = dict(reserved or {})
    return {
        d: size - len(players) for d, players in layout.items() if len(players) < size
    } or {d: 0 for d in reserved}
