from django.db import migrations


def correct_wednesday_lucky_schedule(apps, schema_editor):
    WeeklyGameSchedule = apps.get_model("core", "WeeklyGameSchedule")
    schedule = (
        WeeklyGameSchedule.objects.using(schema_editor.connection.alias)
        .filter(weekday=3, game__name="Lucky", is_active=True)
        .order_by("id")
        .first()
    )
    if schedule is None:
        return

    WeeklyGameSchedule.objects.using(schema_editor.connection.alias).filter(pk=schedule.pk).update(
        is_whole_day=False,
        closing_time="22:30:00",
        draw_time="22:45:00",
        is_active=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_dailysheet_holiday_name_snapshot_and_more"),
    ]

    operations = [
        # A reverse update could overwrite schedule edits made by a Super Admin after deployment.
        migrations.RunPython(correct_wednesday_lucky_schedule, migrations.RunPython.noop),
    ]