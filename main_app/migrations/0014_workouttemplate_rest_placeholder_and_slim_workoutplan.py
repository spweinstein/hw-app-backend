# Generated manually: rest placeholder template + remove plan schedule fields

from django.db import migrations, models


def seed_rest_day_template(apps, schema_editor):
    User = apps.get_model("auth", "User")
    WorkoutTemplate = apps.get_model("main_app", "WorkoutTemplate")
    user = User.objects.order_by("pk").first()
    if user is None:
        return
    WorkoutTemplate.objects.get_or_create(
        user=user,
        title="Rest day",
        defaults={
            "description": "",
            "is_public": True,
            "duration": 1,
            "is_rest_placeholder": True,
        },
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("main_app", "0013_workoutplan_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="workouttemplate",
            name="is_rest_placeholder",
            field=models.BooleanField(
                default=False,
                help_text="If true, plan generate treats this as a rest day (no workout). Cannot be scheduled from the template schedule action.",
            ),
        ),
        migrations.RemoveField(model_name="workoutplan", name="start_dt"),
        migrations.RemoveField(model_name="workoutplan", name="interval"),
        migrations.RemoveField(model_name="workoutplan", name="cycles"),
        migrations.RunPython(seed_rest_day_template, noop_reverse),
    ]
