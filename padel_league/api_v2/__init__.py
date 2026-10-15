"""/api/v2 — the JSON API on the v2 data model (contract: docs/v2/api/openapi.yaml)."""

from . import auth, competitions, matches, players, teams, writes

BLUEPRINTS = (auth.bp, competitions.bp, matches.bp, players.bp, teams.bp, writes.bp)


def register_v2_blueprints(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
