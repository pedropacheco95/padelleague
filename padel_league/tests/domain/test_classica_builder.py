"""Next Clássica from the previous one, on the real v2 data (Postgres, rolled back)."""

import pytest

from padel_league.domain.errors import InvalidInput
from padel_league.services.classica_builder import members_of, next_classica_plan

# 21ª Edição (Primavera 2026, comp 24) → 22ª (Masters de Outono, comp 25):
# Perneta, João Bello, Kikos, Gonçalo Ramalho, To maria, Diogo Leão withdrew.
WITHDRAWN = [18, 77, 26, 100, 92, 3]


def test_real_rollover_reproduces_the_approved_22a_edicao(pg):
    approved = members_of(25)
    previous = set().union(*members_of(24).values())
    newcomers = {t: sorted(p for p in ids if p not in previous) for t, ids in approved.items()}
    placed = {1: newcomers[1]}  # the newcomer who went straight into the 1ª
    rest = [p for t in sorted(newcomers) if t != 1 for p in newcomers[t]]
    plan, notes = next_classica_plan(
        24, "Teste 22ª", "2026-09-01T19:00:00", withdrawals=WITHDRAWN,
        new_player_ids=rest, placed_new_players=placed, division_prefix="Teste",
    )  # fmt: skip
    got = {i + 1: set(d["players"]) for i, d in enumerate(plan["divisions"])}
    assert got == approved
    assert [d["rating"] for d in plan["divisions"]] == [2000, 1000, 500, 250, 125, 63]
    assert plan["divisions"][1]["name"] == "Teste - 2ª Divisão"
    assert any("21 appearances vs 18" in n for n in notes)  # Cou beat Gonçalo PA on appearances


def test_vacancies_must_match_newcomers(pg):
    with pytest.raises(InvalidInput) as err:
        next_classica_plan(24, "Teste", "2026-09-01T19:00:00", withdrawals=WITHDRAWN, new_player_ids=[])
    assert err.value.code == "vacancies_mismatch"
