from django.db import models
from django.conf import settings
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

# Create your models here.


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    
    height = models.PositiveIntegerField(null=True, blank=True)
    def __str__(self):
        return f"Profile for {self.user.username}"
    
class WeightLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="weight_logs",
    )
    weight = models.DecimalField(max_digits=5, decimal_places=1) 
    date = models.DateField()
    class Meta:
        ordering = ["date"]
    def __str__(self):
        return f"{self.user.username} - {self.weight} on {self.date}"
    
class MuscleGroup(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Exercise(models.Model):
    class ExerciseType(models.TextChoices):
        STRENGTH = "strength", "Strength"
        CARDIO = "cardio", "Cardio"
        MOBILITY = "mobility", "Mobility"
        STRETCH = "stretch", "Stretch"
        SPORT = "sport", "Sport"

    name = models.CharField(max_length=120, unique=True)
    exercise_type = models.CharField(
        max_length=20, choices=ExerciseType.choices, default=ExerciseType.STRENGTH
    )

    muscle_groups = models.ManyToManyField(
        MuscleGroup, related_name="exercises", blank=True
    )

    equipment = models.CharField(max_length=60, blank=True)  # keep free-form for MVP
    instructions = models.TextField(blank=True)
    video_url = models.URLField(blank=True)

    def __str__(self) -> str:
        return self.name
    
class WorkoutTemplate(models.Model):
    """
    Reusable routine users can copy/share and attach to WorkoutPlans.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workout_templates"
    )
    title = models.CharField(max_length=140)
    description = models.TextField(blank=True)

    # sharing/copying
    is_public = models.BooleanField(default=False)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
        help_text="If this template was copied from another template, reference it here.",
    )

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    duration = models.PositiveIntegerField()

    class Meta:
        unique_together = ("user", "title")

    def __str__(self) -> str:
        return self.title


class WorkoutTemplateItem(models.Model):
    """
    One exercise per item (confirmed). These are NOT dated/logged; they're template content.
    """
    template = models.ForeignKey(
        WorkoutTemplate, on_delete=models.CASCADE, related_name="items"
    )
    exercise = models.ForeignKey(
        Exercise, on_delete=models.PROTECT, related_name="template_items"
    )
    order = models.PositiveIntegerField(default=0)

    # prescription fields (nullable to support different exercise types)
    sets = models.PositiveIntegerField(null=True, blank=True)
    reps = models.PositiveIntegerField(null=True, blank=True)
    weight = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    weight_unit = models.CharField(
        max_length=5, choices=(("lb", "lb"), ("kg", "kg")), null=True, blank=True
    )
    duration = models.PositiveIntegerField(null=True, blank=True)
    distance = models.PositiveIntegerField(null=True, blank=True)
    distance_unit = models.CharField(
        max_length=5, choices=(("km", "km"), ("mi", "mi")), null=True, blank=True
    )
    rpe = models.PositiveIntegerField(null=True, blank=True)  # 1–10

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.template.title} - {self.exercise.name}"
    
class WorkoutPlan(models.Model):
    """
    Recurrence + program container. Generates Workout instances (calendar events).
    Attaches to templates via the through table WorkoutTemplatePlan.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workout_plans"
    )
    title = models.CharField(max_length=140)
    start_dt = models.DateTimeField()
    interval = models.PositiveIntegerField(default=1)
    cycles = models.PositiveIntegerField(default=1)
    is_public = models.BooleanField(default=False)

    # M2M to templates (composition)
    templates = models.ManyToManyField(
        WorkoutTemplate,
        through="WorkoutTemplatePlan",
        related_name="plans",
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "title")

    def __str__(self) -> str:
        return self.title
    
class WorkoutTemplatePlan(models.Model):
    """
    Through table connecting WorkoutPlans <-> WorkoutTemplates.
    """
    plan = models.ForeignKey(WorkoutPlan, on_delete=models.CASCADE, related_name="template_links")
    template = models.ForeignKey(WorkoutTemplate, on_delete=models.CASCADE, related_name="plan_links")
    order = models.PositiveIntegerField(default=0)
    time = models.TimeField()

    class Meta:
        unique_together = ("plan", "template", "order")
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.plan.title} ↔ {self.template.title}"

class Workout(models.Model):
    """
    Dated calendar instance (what the React calendar queries).
    Can be generated from a plan and/or template, but both are nullable for one-offs.
    """
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"
        CANCELED = "canceled", "Canceled"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workouts"
    )

    plan = models.ForeignKey(
        "WorkoutPlan",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workouts",
    )

    template = models.ForeignKey(
        "WorkoutTemplate",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_workouts",
        help_text="Template used to generate this workout instance (if applicable).",
    )

    title = models.CharField(max_length=140)
    start_dt = models.DateTimeField(db_index=True)
    end_dt = models.DateTimeField()

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PLANNED
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_dt", "id"]

    def __str__(self) -> str:
        return f"{self.title} @ {self.start_dt}"
    
    def clean(self):
        if self.start_dt and self.end_dt:
            conflicts = Workout.objects.filter(
                Q(start_dt__lt=self.end_dt, end_dt__gt=self.start_dt),
                user=self.user,
            )
            if self.pk:
                conflicts = conflicts.exclude(pk=self.pk)
            if conflicts.exists():
                raise ValidationError(
                    f"This workout conflicts with an existing workout on your calendar."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class WorkoutItem(models.Model):
    """
    One exercise per item (confirmed) within a specific Workout instance.
    This is the logged/scheduled data, not the reusable template data.
    """
    workout = models.ForeignKey(
        Workout, on_delete=models.CASCADE, related_name="items"
    )
    exercise = models.ForeignKey(
        Exercise, on_delete=models.PROTECT, related_name="workout_items"
    )
    order = models.PositiveIntegerField(default=0)

    # performance / prescription fields
    sets = models.PositiveIntegerField(null=True, blank=True)
    reps = models.PositiveIntegerField(null=True, blank=True)
    weight = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    weight_unit = models.CharField(
        max_length=5, choices=(("lb", "lb"), ("kg", "kg")), null=True, blank=True
    )
    duration = models.PositiveIntegerField(null=True, blank=True)
    distance = models.PositiveIntegerField(null=True, blank=True)
    distance_unit = models.CharField(
        max_length=5, choices=(("km", "km"), ("mi", "mi")), null=True, blank=True
    )
    rpe = models.PositiveIntegerField(null=True, blank=True)  # 1–10

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.workout.title} - {self.exercise.name}"