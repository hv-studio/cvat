import django.db.models.deletion
from django.db import migrations, models

import cvat.apps.engine.models


class Migration(migrations.Migration):
    dependencies = [("engine", "0108_profile_registration_survey_fields")]

    operations = [
        migrations.CreateModel(
            name="LabeledShapeSourceBbox",
            fields=[
                (
                    "shape",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="source_bbox",
                        serialize=False,
                        to="engine.labeledshape",
                    ),
                ),
                ("bbox", cvat.apps.engine.models.FloatArrayField()),
            ],
        ),
    ]
