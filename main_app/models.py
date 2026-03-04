from django.db import models

# Create your models here.

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