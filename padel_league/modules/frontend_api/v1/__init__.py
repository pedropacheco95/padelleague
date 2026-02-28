from . import auth
from . import main
from . import matches
from . import players
from . import shuffle_tournament
from . import tournaments
from . import calendar
from . import divisions


def register_api_blueprints(app):
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(matches.bp)
    app.register_blueprint(players.bp)
    app.register_blueprint(shuffle_tournament.bp)
    app.register_blueprint(tournaments.bp)
    app.register_blueprint(calendar.bp)
    app.register_blueprint(divisions.bp)


__all__ = [
    "auth",
    "main",
    "matches",
    "players",
    "shuffle_tournament",
    "tournaments",
    "calendar",
    "divisions",
]
