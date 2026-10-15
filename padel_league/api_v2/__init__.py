"""/api/v2 — the JSON API on the v2 data model (contract: docs/v2/api/openapi.yaml)."""

from . import auth, builders, competitions, matches, news, players, sponsors, teams, writes

BLUEPRINTS = (auth.bp, builders.bp, competitions.bp, matches.bp, news.bp, players.bp, sponsors.bp, teams.bp, writes.bp)


def register_v2_blueprints(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
