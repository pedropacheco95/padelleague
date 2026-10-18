"""The one competition/division label and the edition order (Pedro, 2026-10-18)."""

from types import SimpleNamespace

from padel_league.api_v2.cards import competition_label, edition_sort_key, group_label


def comp(name, title=None, id=1):
    return SimpleNamespace(id=id, name=name, title=title)


def test_classic_label_drops_the_sponsor_and_takes_the_season_from_the_top_division():
    c = comp("16ª Edição Powered by QSC")
    assert competition_label(c, "Primavera 2025 - 1ª Divisão") == "16ª Edição - Primavera 2025"
    assert group_label(c, "Primavera 2025 - 5ª Divisão") == "16ª Edição - Primavera 2025 - 5ª Divisão"


def test_divisions_named_after_the_edition_are_not_prefixed_twice():
    c = comp("24ª Edição")
    assert group_label(c, "24ª Edição - 1ª Divisão") == "24ª Edição - 1ª Divisão"
    assert competition_label(c, "24ª Edição - 1ª Divisão") == "24ª Edição"


def test_shuffle_and_teams_use_their_title():
    assert competition_label(comp("20ª Edição", "Shuffle 2026"), None) == "20ª Edição - Shuffle 2026"
    assert competition_label(comp("23ª Edição", "Teams 2026/27"), "1.ª Divisão") == "23ª Edição - Teams 2026/27"
    assert group_label(comp("20ª Edição", "Shuffle 2026"), None) == "20ª Edição - Shuffle 2026"


def test_a_competition_without_a_number_keeps_its_name():
    assert competition_label(comp("Play Off"), "Quadro A") == "Play Off"
    assert group_label(comp("Play Off"), "Quadro A") == "Play Off"


def test_edition_order_puts_the_undated_shuffle_between_its_neighbours():
    cards = [
        {"id": 23, "editionNumber": 19, "startsOn": "2026-01-06"},
        {"id": 26, "editionNumber": 20, "startsOn": None},
        {"id": 24, "editionNumber": 21, "startsOn": "2026-05-12"},
        {"id": 1, "editionNumber": None, "startsOn": "2022-01-12"},
    ]
    assert [c["id"] for c in sorted(cards, key=edition_sort_key, reverse=True)] == [24, 26, 23, 1]
