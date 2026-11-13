from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0023_confirmed_weekly_schedule")]
    operations = [
        # Populate only the new column; never rewrite historical money or imports.
        migrations.AddField(
            model_name="dailysheet", name="commission_rate_snapshot",
            field=models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.05"), editable=False),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="dailysheet", name="commission_rate_snapshot",
            field=models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.02"), editable=False),
        ),
    ]
