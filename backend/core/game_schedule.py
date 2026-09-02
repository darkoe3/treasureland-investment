from dataclasses import dataclass
from datetime import time

from django.db import transaction

from .models import Game, Weekday, WeeklyGameSchedule


@dataclass(frozen=True)
class ApprovedScheduleEntry:
    weekday: int
    game_name: str
    display_order: int
    is_whole_day: bool = False
    closing_time: time | None = None
    draw_time: time | None = None


def parse_time(value):
    hour, minute = value.split(":")
    return time(hour=int(hour), minute=int(minute))


def timed(weekday, game_name, display_order, closing_time, draw_time):
    return ApprovedScheduleEntry(
        weekday=weekday,
        game_name=game_name,
        display_order=display_order,
        closing_time=parse_time(closing_time),
        draw_time=parse_time(draw_time),
    )


def whole_day(weekday, game_name, display_order):
    return ApprovedScheduleEntry(
        weekday=weekday,
        game_name=game_name,
        display_order=display_order,
        is_whole_day=True,
    )


APPROVED_WEEKLY_SCHEDULE = [
    timed(Weekday.MONDAY, "Peoples", 1, "12:30", "12:45"),
    timed(Weekday.MONDAY, "Bingo", 2, "15:30", "15:45"),
    whole_day(Weekday.MONDAY, "Monday Special", 3),
    timed(Weekday.MONDAY, "Metro", 4, "19:30", "19:45"),
    timed(Weekday.MONDAY, "International", 5, "22:30", "22:45"),
    timed(Weekday.MONDAY, "Diamond", 6, "09:00", "21:45"),
    timed(Weekday.TUESDAY, "06", 1, "12:30", "12:45"),
    timed(Weekday.TUESDAY, "Jackpot", 2, "15:30", "15:45"),
    whole_day(Weekday.TUESDAY, "Lucky G", 3),
    timed(Weekday.TUESDAY, "Club Master", 4, "19:30", "19:45"),
    timed(Weekday.TUESDAY, "Super", 5, "22:30", "22:45"),
    timed(Weekday.TUESDAY, "Gold", 6, "09:00", "09:45"),
    timed(Weekday.WEDNESDAY, "Mark II", 1, "12:30", "12:45"),
    timed(Weekday.WEDNESDAY, "VAG", 2, "15:30", "15:45"),
    whole_day(Weekday.WEDNESDAY, "Midweek", 3),
    timed(Weekday.WEDNESDAY, "Enugu", 4, "19:30", "19:45"),
    whole_day(Weekday.WEDNESDAY, "Lucky", 5),
    timed(Weekday.WEDNESDAY, "Tota", 6, "09:00", "09:45"),
    timed(Weekday.THURSDAY, "Fairchance", 1, "12:30", "13:30"),
    timed(Weekday.THURSDAY, "Diamond", 2, "15:30", "15:45"),
    whole_day(Weekday.THURSDAY, "Fortune", 3),
    timed(Weekday.THURSDAY, "International", 4, "19:30", "19:45"),
    timed(Weekday.THURSDAY, "Bingo", 5, "22:30", "22:45"),
    timed(Weekday.THURSDAY, "Peoples", 6, "09:00", "09:45"),
    timed(Weekday.FRIDAY, "Metro", 1, "12:30", "12:45"),
    timed(Weekday.FRIDAY, "Gold", 2, "15:30", "15:45"),
    whole_day(Weekday.FRIDAY, "Bonanza", 3),
    timed(Weekday.FRIDAY, "Jackpot", 4, "19:30", "19:45"),
    timed(Weekday.FRIDAY, "VAG", 5, "22:30", "22:45"),
    timed(Weekday.FRIDAY, "Royal", 6, "09:00", "09:45"),
    timed(Weekday.SATURDAY, "Super", 1, "12:30", "12:45"),
    timed(Weekday.SATURDAY, "Club Master", 2, "15:30", "15:45"),
    whole_day(Weekday.SATURDAY, "National", 3),
    timed(Weekday.SATURDAY, "06", 4, "19:30", "19:45"),
    timed(Weekday.SATURDAY, "Fairchance", 5, "22:00", "22:30"),
    timed(Weekday.SATURDAY, "King", 6, "09:30", "09:45"),
    timed(Weekday.SUNDAY, "Enugu", 1, "15:30", "15:45"),
    timed(Weekday.SUNDAY, "Lucky", 2, "19:30", "19:45"),
    timed(Weekday.SUNDAY, "Tota", 3, "21:30", "21:45"),
    timed(Weekday.SUNDAY, "Mark II", 4, "12:30", "12:45"),
    whole_day(Weekday.SUNDAY, "Aseda", 5),
]


APPROVED_WEEKLY_GAME_NAMES = {
    weekday: [entry.game_name for entry in APPROVED_WEEKLY_SCHEDULE if entry.weekday == weekday]
    for weekday in Weekday.values
}


GAME_NAME_ALIASES = {
    "msp": "Monday Special",
    "monday special": "Monday Special",
    "mk ii": "Mark II",
    "mark ii": "Mark II",
    "c/master": "Club Master",
    "clubmaster": "Club Master",
    "club master": "Club Master",
    "international": "International",
    "fairchance": "Fairchance",
    "06": "06",
}


def canonical_game_name(name):
    return GAME_NAME_ALIASES.get(str(name).strip().lower(), str(name).strip())


def equivalent_game_names(name):
    canonical = canonical_game_name(name)
    names = {canonical}
    names.update(alias for alias, resolved in GAME_NAME_ALIASES.items() if resolved == canonical)
    return names


def get_or_create_canonical_game(name):
    canonical = canonical_game_name(name)
    exact = Game.objects.filter(name=canonical).first()
    alias = None
    for alias_name in equivalent_game_names(canonical):
        if alias_name == canonical:
            continue
        alias_query = Game.objects.filter(name__iexact=alias_name)
        if exact:
            alias_query = alias_query.exclude(pk=exact.pk)
        alias = alias_query.first()
        if alias:
            break

    if exact:
        if alias:
            WeeklyGameSchedule.objects.filter(game=alias).update(game=exact)
            alias.is_active = False
            alias.save(update_fields=["is_active", "updated_at"])
        if not exact.is_active:
            exact.is_active = True
            exact.save(update_fields=["is_active", "updated_at"])
        return exact

    if alias:
        alias.name = canonical
        alias.is_active = True
        alias.save(update_fields=["name", "is_active", "updated_at"])
        return alias

    return Game.objects.create(name=canonical, is_active=True)


def entry_defaults(entry):
    return {
        "display_order": entry.display_order,
        "is_whole_day": entry.is_whole_day,
        "closing_time": None if entry.is_whole_day else entry.closing_time,
        "draw_time": None if entry.is_whole_day else entry.draw_time,
        "is_active": True,
    }


@transaction.atomic
def apply_approved_weekly_game_schedule():
    approved_keys = set()
    updated = []

    for entry in APPROVED_WEEKLY_SCHEDULE:
        game = get_or_create_canonical_game(entry.game_name)
        approved_keys.add((entry.weekday, game.id))
        schedule = (
            WeeklyGameSchedule.objects.filter(weekday=entry.weekday, game=game)
            .order_by("-is_active", "id")
            .first()
        )
        if schedule is None:
            schedule = WeeklyGameSchedule(game=game, weekday=entry.weekday)
        for field, value in entry_defaults(entry).items():
            setattr(schedule, field, value)
        schedule.save()
        updated.append(schedule)

    WeeklyGameSchedule.objects.filter(is_active=True).exclude(
        weekday__in=[weekday for weekday, _game_id in approved_keys],
        game_id__in=[game_id for _weekday, game_id in approved_keys],
    ).update(is_active=False)

    for schedule in WeeklyGameSchedule.objects.filter(is_active=True).select_related("game"):
        if (schedule.weekday, schedule.game_id) not in approved_keys:
            schedule.is_active = False
            schedule.save(update_fields=["is_active", "updated_at"])

    return updated
