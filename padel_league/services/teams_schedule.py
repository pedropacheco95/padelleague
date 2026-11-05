"""What Teams does on its own: the next pair choice opens when a mini-tournament
ends, and after the deadline the pairs close and the divisions form.

run_due() is idempotent and runs hourly (`flask v2 teams-tick`, cron on the VM),
so whatever a failed run left undone is picked up by the next one.
"""

from datetime import datetime

from padel_league.domain.teams_calendar import pairing_deadline, round_date
from padel_league.models.v2 import CompetitionGroup, Stage
from padel_league.services import teams_divisions, teams_pairing
from padel_league.sql_db import db


def open_next(stage, now):
    """Open the pair choice of the mini-tournament after `stage`. The caller commits."""
    competition = stage.competition
    following = Stage.query.filter_by(competition_id=competition.id, number=stage.number + 1).first()
    if following is None or following.pairing_deadline is not None or competition.starts_on is None:
        return None
    first_round = round_date(competition.starts_on, following.number, 1, len(teams_divisions.ROUND_ROBIN))
    following.pairing_deadline = pairing_deadline(first_round, now)
    return following


def run_due(now=None):
    """Do whatever is due in the current Teams. Commits; returns one line per action."""
    now = now or datetime.utcnow()
    competition = teams_pairing.current_competition()
    if competition is None:
        return []
    lines = []
    for stage in Stage.query.filter_by(competition_id=competition.id).order_by(Stage.number):
        if stage.status == "ended":
            opened = open_next(stage, now)
            if opened is not None:
                db.session.commit()
                lines.append(f"{opened.name}: pair choice open until {opened.pairing_deadline} UTC")
        elif stage.pairing_deadline is not None and stage.pairing_deadline < now:
            if not stage.pairing_closed:
                teams_pairing.close(stage)
                lines.append(f"{stage.name}: pairs closed")
            if not CompetitionGroup.query.filter_by(stage_id=stage.id).first():
                teams_divisions.build_divisions(stage)
                db.session.commit()
                lines.append(f"{stage.name}: divisions formed")
    return lines
