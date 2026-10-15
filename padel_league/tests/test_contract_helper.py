"""The contract helper: the spec loads, refs resolve, mismatches are reported."""

import pytest

from padel_league.tests import contract


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def get_json(self):
        return self._body


CARD = {
    "id": 27, "name": "PPL Teams 2026/27", "format": "teams", "status": "upcoming", "groupCount": 6,
    "season": {"id": 6, "name": "2026/27", "isCurrent": True},
}


def test_spec_loads_and_documents_the_cards_endpoint():
    assert "/competitions" in contract.spec()["paths"]


def test_a_valid_card_list_passes():
    contract.assert_matches_spec(_Resp(200, [CARD]), "/competitions")


def test_a_wrong_format_is_reported():
    with pytest.raises(AssertionError, match="format"):
        contract.assert_matches_spec(_Resp(200, [{**CARD, "format": "padel"}]), "/competitions")


def test_an_undocumented_status_is_reported():
    with pytest.raises(AssertionError, match="does not document"):
        contract.assert_matches_spec(_Resp(418, {}), "/competitions")
