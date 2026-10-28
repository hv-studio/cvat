import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("engine", "0109_labeledshape_source_bbox")]

    operations = [
        migrations.CreateModel(
            name="TaskYtvisSource",
            fields=[
                (
                    "task",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="ytvis_source",
                        serialize=False,
                        to="engine.task",
                    ),
                ),
                ("data", models.JSONField()),
            ],
        ),
    ]
