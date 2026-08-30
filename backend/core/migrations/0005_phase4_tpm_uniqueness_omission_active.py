# Generated for Phase 4 daily operations.

from django.db import migrations, models
import django.db.models
import django.db.models.functions.text


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_alter_auditlog_agency"),
    ]

    operations = [
        migrations.AddField(
            model_name="omittedterminal",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.RemoveConstraint(
            model_name="omittedterminal",
            name="unique_omitted_terminal_per_sheet",
        ),
        migrations.AddConstraint(
            model_name="omittedterminal",
            constraint=models.UniqueConstraint(
                condition=django.db.models.Q(("is_active", True)),
                fields=("daily_sheet", "tpm_code"),
                name="unique_active_omitted_terminal_per_sheet",
            ),
        ),
        migrations.AddConstraint(
            model_name="tpmcode",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("code"),
                name="unique_tpm_code_case_insensitive",
            ),
        ),
    ]
