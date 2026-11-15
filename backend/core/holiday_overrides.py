from dataclasses import dataclass
from datetime import date, time

from django.core.exceptions import ValidationError

from .models import HolidayGameOverride, WeeklyGameSchedule


@dataclass(frozen=True)
class EffectiveScheduleEntry:
    id: int
    game: object
    category: str
    is_whole_day: bool
    closing_time: time | None
    draw_time: time | None
    display_order: int
    is_holiday_override: bool = False


def effective_schedule_for_date(transaction_date: date):
    schedules = list(
        WeeklyGameSchedule.objects.select_related("game").filter(
            weekday=transaction_date.isoweekday(),
            is_active=True,
            game__is_active=True,
        ).order_by("display_order", "id")
    )
    override = (
        HolidayGameOverride.objects.select_related("normal_game", "replacement_game")
        .filter(holiday_date=transaction_date, is_active=True)
        .first()
    )
    from .game_schedule import validate_weekday_schedule

    errors = validate_weekday_schedule(transaction_date.isoweekday(), schedules)
    if errors:
        raise ValidationError({"schedule": errors})
    entries = [
        EffectiveScheduleEntry(
            id=schedule.id,
            game=schedule.game,
            category=schedule.category,
            is_whole_day=schedule.is_whole_day,
            closing_time=schedule.closing_time,
            draw_time=schedule.draw_time,
            display_order=schedule.display_order,
        )
        for schedule in schedules
    ]
    if not override:
        return entries, None

    from .game_schedule import canonical_game_name

    normal_index = next(
        (
            index for index, entry in enumerate(entries)
            if canonical_game_name(entry.game.name) == canonical_game_name(override.normal_game.name) and entry.category == "GHANA"
        ),
        None,
    )
    if normal_index is None:
        raise ValidationError({"holiday_override": "The configured normal Ghana game is no longer scheduled for this date."})

    source_rows = list(WeeklyGameSchedule.objects.select_related("game").filter(
        weekday=override.source_date.isoweekday(), is_active=True, game__is_active=True,
    ).order_by("display_order", "id"))
    source_errors = validate_weekday_schedule(override.source_date.isoweekday(), source_rows)
    if source_errors:
        raise ValidationError({"holiday_override_source_schedule": source_errors})
    source = next((row for row in source_rows if row.category == "GHANA" and
                   canonical_game_name(row.game.name) == canonical_game_name(override.replacement_game.name)), None)
    if source is None:
        raise ValidationError({"holiday_override": "The replacement must be an active Ghana game on the source weekday."})
    normal_entry = entries[normal_index]
    entries[normal_index] = EffectiveScheduleEntry(
        id=normal_entry.id,
        game=source.game,
        category="GHANA",
        is_whole_day=True,
        closing_time=None,
        draw_time=None,
        display_order=normal_entry.display_order,
        is_holiday_override=True,
    )
    return entries, override