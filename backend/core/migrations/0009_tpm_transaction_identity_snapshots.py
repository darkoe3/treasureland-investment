from django.db import migrations, models


def backfill_identity(apps, schema_editor):
    Transaction = apps.get_model("core", "TPMDailyTransaction")
    alias = schema_editor.connection.alias
    for row in Transaction.objects.using(alias).select_related("tpm_code").iterator():
        Transaction.objects.using(alias).filter(pk=row.pk).update(
            person_id_snapshot=row.tpm_code.person_id,
            tpm_code_snapshot=row.tpm_code.code,
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0008_alter_auditlog_action_dailysheetimportbatch")]
    operations = [
        migrations.AddField(model_name="tpmdailytransaction", name="person_id_snapshot", field=models.PositiveBigIntegerField(editable=False, null=True)),
        migrations.AddField(model_name="tpmdailytransaction", name="tpm_code_snapshot", field=models.CharField(max_length=80, editable=False, null=True)),
        migrations.RunPython(backfill_identity, migrations.RunPython.noop),
        migrations.AlterField(model_name="tpmdailytransaction", name="person_id_snapshot", field=models.PositiveBigIntegerField(editable=False)),
        migrations.AlterField(model_name="tpmdailytransaction", name="tpm_code_snapshot", field=models.CharField(max_length=80, editable=False)),
    ]
