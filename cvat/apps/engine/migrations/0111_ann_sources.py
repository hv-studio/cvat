import django.db.models.deletion
from django.db import migrations, models


def migrate_sources(apps, schema_editor):
    database = schema_editor.connection.alias
    task_sources = apps.get_model("engine", "TaskAnnSource").objects.using(database)
    for source in task_sources.iterator():
        source.data = {"format": "YTVIS 1.0", "data": source.data}
        source.save(using=database, update_fields=["data"])

    shape_sources = apps.get_model("engine", "LabeledShapeSource").objects.using(database)
    batch = []
    for source in shape_sources.iterator():
        # The old record only stored a COCO-style XYWH reference box, not source identity.
        source.data = {"format": "COCO 1.0", "data": {"ref_bbox": list(source.bbox)}}
        batch.append(source)
        if len(batch) == 1000:
            shape_sources.bulk_update(batch, ["data"])
            batch.clear()
    if batch:
        shape_sources.bulk_update(batch, ["data"])


class Migration(migrations.Migration):
    dependencies = [("engine", "0110_task_ytvis_source")]

    operations = [
        migrations.RenameModel("TaskYtvisSource", "TaskAnnSource"),
        migrations.AlterField(
            model_name="taskannsource",
            name="task",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                primary_key=True,
                related_name="ann_sources",
                serialize=False,
                to="engine.task",
            ),
        ),
        migrations.RenameModel("LabeledShapeSourceBbox", "LabeledShapeSource"),
        migrations.AlterField(
            model_name="labeledshapesource",
            name="shape",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                primary_key=True,
                related_name="ann_sources",
                serialize=False,
                to="engine.labeledshape",
            ),
        ),
        migrations.AddField(
            model_name="labeledshapesource", name="data", field=models.JSONField(null=True)
        ),
        migrations.RunPython(migrate_sources),
        migrations.RemoveField(model_name="labeledshapesource", name="bbox"),
        migrations.AlterField(
            model_name="labeledshapesource", name="data", field=models.JSONField()
        ),
    ]
