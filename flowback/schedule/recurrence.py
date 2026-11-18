"""
Occurrences of repeating events.

A repeating event only stores its first occurrence. The others are that occurrence's wall-clock time repeated
in the event's timezone, so a daily event at 18:00 stays at 18:00 when the clocks change.
The frontend does the same calculation when it draws the calendar (src/lib/Schedule/recurrence.ts),
keep the two in sync.
"""
import calendar
import datetime
from functools import cache
from zoneinfo import ZoneInfo, available_timezones

from django.core.exceptions import ValidationError

DAILY = 1
WEEKLY = 2
MONTHLY = 3  # Months without the event's day are skipped, a monthly event on the 31st is never held in April
YEARLY = 4  # Years without the event's day are skipped, a yearly event on Feb 29th is only held in leap years

# Clients only know a time to the millisecond, so a time within one is the same time
SAME_TIME = datetime.timedelta(milliseconds=1)

# Far enough to get past skipped months and years (Feb 29th comes around at most every eight years)
LOOKAHEAD = 12


@cache
def _timezone_names() -> frozenset[str]:
    return frozenset(available_timezones())


def validate_timezone_name(value: str):
    if value not in _timezone_names():
        raise ValidationError(f"Unknown timezone '{value}', expected an IANA name like 'Europe/Stockholm'")


def occurrence(first: datetime.datetime,
               frequency: int,
               index: int,
               tz: ZoneInfo) -> datetime.datetime | None:
    """
    The occurrence at index of an event that first happens at first, where index 0 is first itself.
    Returns None if the event skips that occurrence.
    """
    wall = first.astimezone(tz).replace(tzinfo=None)

    if frequency == DAILY:
        wall += datetime.timedelta(days=index)

    elif frequency == WEEKLY:
        wall += datetime.timedelta(weeks=index)

    elif frequency == MONTHLY:
        year, month = divmod(wall.year * 12 + wall.month - 1 + index, 12)
        month += 1
        if wall.day > calendar.monthrange(year, month)[1]:
            return None
        wall = wall.replace(year=year, month=month)

    elif frequency == YEARLY:
        year = wall.year + index
        if wall.month == 2 and wall.day == 29 and not calendar.isleap(year):
            return None
        wall = wall.replace(year=year)

    else:
        raise ValueError(f"Unknown repeat frequency {frequency}")

    # A wall-clock time that is skipped when the clocks go forward is held an hour later,
    # one that happens twice when they go back is held the first time
    return wall.replace(tzinfo=tz).astimezone(datetime.timezone.utc)


def _search_start(first: datetime.datetime,
                  frequency: int,
                  tz: ZoneInfo,
                  after: datetime.datetime) -> int:
    """
    An index to start looking from for the first occurrence after the given time,
    a little before the answer to not go through every occurrence since the first one
    """
    wall_first = first.astimezone(tz)
    wall_after = after.astimezone(tz)

    if frequency in (DAILY, WEEKLY):
        index = (wall_after.date() - wall_first.date()).days // (1 if frequency == DAILY else 7)
    elif frequency == MONTHLY:
        index = (wall_after.year - wall_first.year) * 12 + wall_after.month - wall_first.month
    else:
        index = wall_after.year - wall_first.year

    return max(0, index - 1)


def next_occurrence(first: datetime.datetime,
                    frequency: int,
                    tz: ZoneInfo,
                    after: datetime.datetime,
                    last: datetime.datetime | None = None) -> datetime.datetime | None:
    """
    The first occurrence after the given time, None if the event doesn't get to it before last
    """
    index = _search_start(first, frequency, tz, after)

    for i in range(index, index + LOOKAHEAD):
        candidate = occurrence(first, frequency, i, tz)

        if candidate is None:
            continue

        if last is not None and candidate > last:
            return None

        if candidate > after:
            return candidate

    return None


def occurrence_index(first: datetime.datetime,
                     frequency: int,
                     tz: ZoneInfo,
                     at: datetime.datetime,
                     last: datetime.datetime | None = None) -> int | None:
    """
    The index of the occurrence that happens at the given time (to the millisecond),
    None if the event has no occurrence then
    """
    index = _search_start(first, frequency, tz, at)

    for i in range(index, index + LOOKAHEAD):
        candidate = occurrence(first, frequency, i, tz)

        if candidate is None:
            continue

        if abs(candidate - at) < SAME_TIME:
            return i if last is None or candidate <= last else None

        if candidate > at:
            return None

    return None
