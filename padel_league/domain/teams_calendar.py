"""Teams calendar: the competition's start date defines every jornada, one a week,
the mini-tournaments back to back. An exception is fixed by hand on the Round."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LISBON = ZoneInfo("Europe/Lisbon")


def round_date(starts_on, stage_number, round_number, rounds_per_stage):
    return starts_on + timedelta(weeks=(stage_number - 1) * rounds_per_stage + round_number - 1)


def end_of_day(day):
    """The day's last second in Lisbon, as naive UTC (how the database keeps deadlines)."""
    return datetime.combine(day, time(23, 59, 59), tzinfo=LISBON).astimezone(timezone.utc).replace(tzinfo=None)


def pairing_deadline(first_round, now):
    """The end of the Sunday before the first jornada. A mini-tournament that finishes
    after that Sunday still gives the players until the end of the next day."""
    sunday = first_round - timedelta(days=first_round.weekday() + 1)
    today = now.replace(tzinfo=timezone.utc).astimezone(LISBON).date()
    return max(end_of_day(sunday), end_of_day(today + timedelta(days=1)))
