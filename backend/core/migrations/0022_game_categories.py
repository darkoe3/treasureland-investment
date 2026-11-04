from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0021_payerpayment_agency_id_snapshot_and_more")]
    operations = [
        migrations.AddField(model_name="dailysheetgame", name="category_snapshot", field=models.CharField(blank=True, null=True, max_length=20, choices=[("TIMED", "Timed"), ("GHANA", "Ghana Game"), ("DOUBLE_CHANCE", "Double Chance")])),
        migrations.AddField(model_name="weeklygameschedule", name="category", field=models.CharField(default="TIMED", max_length=20, choices=[("TIMED", "Timed"), ("GHANA", "Ghana Game"), ("DOUBLE_CHANCE", "Double Chance")])),
    ]
