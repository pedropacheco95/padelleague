"""The chatbot's SQL client only ever runs one SELECT, read-only, with a timeout."""

import pytest
from sqlalchemy.exc import DBAPIError

from padel_league.core import services
from padel_league.core.services import SQLClient, UnsafeSQLError, check_select_only


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE players SET name = 'x'",
        "DELETE FROM players",
        "INSERT INTO players (name) VALUES ('x')",
        "SELECT 1; DROP TABLE players",
        "WITH gone AS (DELETE FROM players RETURNING id) SELECT * FROM gone",
        "SELECT name INTO scratch FROM players",
        "SELECT password FROM users",
        "SELECT * FROM legacy.users",
        "SELECT * FROM compat.players",
        "SELECT pg_sleep(60)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT * FROM information_schema.tables",
        "COPY players TO '/tmp/players.csv'",
        "",
        None,
    ],
)
def test_anything_but_one_select_is_refused(sql):
    with pytest.raises(UnsafeSQLError):
        check_select_only(sql)


def test_a_commented_select_with_a_trailing_semicolon_passes():
    body = check_select_only("-- top player\nSELECT p.name FROM players p /* v2 */ WHERE p.id = :id;")
    assert body.startswith("SELECT p.name")
    assert body.endswith(":id")


def test_select_runs_and_returns_dicts(pg):
    rows = SQLClient().execute("select count(*) as n from players")
    assert rows == [{"n": rows[0]["n"]}]
    assert rows[0]["n"] >= 0


def test_a_write_never_reaches_the_database(pg, monkeypatch):
    connected = []
    monkeypatch.setattr(SQLClient, "_engine", lambda self: connected.append(1))
    with pytest.raises(UnsafeSQLError):
        SQLClient().execute("update players set name = name where false")
    assert connected == []


def test_the_transaction_is_read_only_even_if_the_check_is_bypassed(pg, monkeypatch):
    monkeypatch.setattr(services, "check_select_only", lambda sql: sql)
    with pytest.raises(DBAPIError) as info:
        SQLClient().execute("update players set name = name where false")
    assert "read-only transaction" in str(info.value)


def test_slow_queries_hit_the_statement_timeout(pg):
    with pytest.raises(DBAPIError) as info:
        SQLClient(statement_timeout_ms=50).execute("select count(*) from generate_series(1, 300000000)")
    assert "statement timeout" in str(info.value)


def test_timeout_comes_from_config_by_default(pg_app):
    with pg_app.app_context():
        pg_app.config["CHATBOT_STATEMENT_TIMEOUT_MS"] = 1234
        assert SQLClient()._timeout_ms() == 1234
        assert SQLClient(statement_timeout_ms=7)._timeout_ms() == 7


def test_dedicated_role_uri_gets_its_own_engine(pg_app, pg_database):
    with pg_app.app_context():
        client = SQLClient()
        assert client._engine() is services.db.engine
        pg_app.config["CHATBOT_DATABASE_URI"] = pg_database
        try:
            own = client._engine()
            assert own is not services.db.engine
            assert client._engine() is own
            assert client.execute("select 1 as one") == [{"one": 1}]
        finally:
            pg_app.config.pop("CHATBOT_DATABASE_URI")
            own.dispose()
