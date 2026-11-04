"""Update schedules only; never rewrite games, overrides, or historical snapshots."""
from django.db import migrations


GHANA = [(1, "MSP", "Monday Special"), (2, "Lucky Ghana", "Lucky G"),
         (3, "Midweek", "Midweek"), (4, "Fortune", "Fortune"),
         (5, "Bonanza", "Bonanza"), (6, "National", "National"), (7, "Aseda", "Aseda")]


def update_schedule(apps, schema_editor):
    alias = schema_editor.connection.alias
    Game = apps.get_model("core", "Game")
    Schedule = apps.get_model("core", "WeeklyGameSchedule")
    games = Game.objects.using(alias)
    schedules = Schedule.objects.using(alias)
    double, _ = games.get_or_create(name="Double Chance", defaults={"is_active": True})
    for weekday, name, legacy in GHANA:
        game, _ = games.get_or_create(name=name, defaults={"is_active": True})
        games.filter(pk__in=[game.pk, double.pk]).update(is_active=True)
        candidates = schedules.filter(weekday=weekday, game__name__in=[name, legacy]).order_by("-is_active", "id")
        row = candidates.first()
        order = row.display_order if row else (5 if weekday == 7 else 3)
        # Deactivate duplicate legacy entries before repointing the retained schedule.
        if row:
            candidates.exclude(pk=row.pk).update(is_active=False)
            schedules.filter(pk=row.pk).update(game_id=game.pk, category="GHANA", is_whole_day=True,
                closing_time=None, draw_time=None, is_active=True)
        else:
            schedules.create(game_id=game.pk, weekday=weekday, category="GHANA", is_whole_day=True,
                closing_time=None, draw_time=None, display_order=order, is_active=True)
        dc = schedules.filter(weekday=weekday, game_id=double.pk).order_by("-is_active", "id").first()
        defaults = dict(category="DOUBLE_CHANCE", is_whole_day=True, closing_time=None,
                        draw_time=None, display_order=order, is_active=True)
        if dc:
            schedules.filter(weekday=weekday, game_id=double.pk).exclude(pk=dc.pk).update(is_active=False)
            schedules.filter(pk=dc.pk).update(**defaults)
        else:
            schedules.create(weekday=weekday, game_id=double.pk, **defaults)


class Migration(migrations.Migration):
    dependencies = [("core", "0022_game_categories")]
    operations = [migrations.RunPython(update_schedule, migrations.RunPython.noop)]
