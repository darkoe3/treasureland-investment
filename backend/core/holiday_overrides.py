from dataclasses import dataclass
from datetime import date, time

from django.core.exceptions import ValidationError

from .models import HolidayGameOverride, WeeklyGameSchedule


@dataclass(frozen=True)
class EffectiveScheduleEntry:
    id: int
    game: object
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
    entries = [
        EffectiveScheduleEntry(
            id=schedule.id,
            game=schedule.game,
            is_whole_day=schedule.is_whole_day,
            closing_time=schedule.closing_time,
            draw_time=schedule.draw_time,
            display_order=schedule.display_order,
        )
        for schedule in schedules
    ]
    if not override:
        return entries, None

    normal_index = next(
        (
            index for index, entry in enumerate(entries)
            if entry.game.id == override.normal_game_id and entry.is_whole_day
        ),
        None,
    )
    if normal_index is None:
        raise ValidationError({"holiday_override": "The configured normal Whole Day game is no longer scheduled for this date."})

    normal_entry = entries[normal_index]
    entries[normal_index] = EffectiveScheduleEntry(
        id=normal_entry.id,
        game=override.replacement_game,
        is_whole_day=True,
        closing_time=None,
        draw_time=None,
        display_order=normal_entry.display_order,
        is_holiday_override=True,
    )
    return entries, override