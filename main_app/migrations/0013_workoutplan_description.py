# Generated manually for WorkoutPlan.description

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main_app", "0012_alter_workouttemplateplan_plan_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="workoutplan",
            name="description",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
    ]
