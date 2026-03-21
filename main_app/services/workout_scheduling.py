"""
Shared workout creation: calendar conflict rules, template item copy, plan regeneration.
Used by WorkoutSerializer, template schedule, and plan generate.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from ..models import Workout, WorkoutItem, WorkoutPlan, WorkoutTemplate, WorkoutTemplatePlan


class WorkoutScheduleConflictError(APIException):
    """Maps Workout model overlap validation to HTTP 409."""

    status_code = 409
    default_detail = "This workout conflicts with an existing calendar workout."
    default_code = "schedule_conflict"

    def __init__(
        self,
        django_error: DjangoValidationError | None = None,
        *,
        detail_message: str | None = None,
    ):
        msg = detail_message or self.default_detail
        if django_error is not None and getattr(django_error, "messages", None):
            detail = {"detail": str(msg), "errors": list(django_error.messages)}
        else:
            detail = msg
        super().__init__(detail=detail)


def copy_template_items_to_workout(workout: Workout, template: WorkoutTemplate) -> None:
    template_items = list(
        template.items.select_related("exercise").order_by("order", "id")
    )
    if not template_items:
        return
    WorkoutItem.objects.bulk_create(
        [
            WorkoutItem(
                workout=workout,
                exercise=ti.exercise,
                order=ti.order,
                sets=ti.sets,
                reps=ti.reps,
                weight=ti.weight,
                weight_unit=ti.weight_unit,
                duration=ti.duration,
                distance=ti.distance,
                distance_unit=ti.distance_unit,
                rpe=ti.rpe,
                notes=ti.notes,
            )
            for ti in template_items
        ]
    )


def create_workout_with_template_items(
    *,
    user,
    template: WorkoutTemplate,
    start_dt,
    end_dt,
    plan=None,
    title: str | None = None,
    notes: str = "",
    status: str = Workout.Status.PLANNED,
) -> Workout:
    """
    Create a workout and copy exercises from the template.
    Raises DjangoValidationError on calendar overlap (from Workout.save/full_clean).
    """
    workout = Workout.objects.create(
        user=user,
        plan=plan,
        template=template,
        title=title if title is not None else template.title,
        start_dt=start_dt,
        end_dt=end_dt,
        status=status,
        notes=notes or "",
    )
    copy_template_items_to_workout(workout, template)
    return workout


def create_workout_with_item_dicts(
    *,
    user,
    workout_kwargs: dict,
    items_data: list[dict],
) -> Workout:
    """
    Create a workout from flat fields (no user/items keys) + nested item dicts
    (already validated for WorkoutItem, e.g. from WorkoutItemSerializer).
    """
    workout = Workout.objects.create(user=user, **workout_kwargs)
    if items_data:
        WorkoutItem.objects.bulk_create(
            [WorkoutItem(workout=workout, **item) for item in items_data]
        )
    return workout


def schedule_workout_from_template(
    *,
    user,
    template: WorkoutTemplate,
    start_dt,
    end_dt=None,
) -> Workout:
    """Single template → one calendar workout (optionally custom end_dt)."""
    if end_dt is None:
        end_dt = start_dt + timedelta(minutes=template.duration)
    return create_workout_with_template_items(
        user=user,
        template=template,
        start_dt=start_dt,
        end_dt=end_dt,
    )


def build_plan_candidate_slots(plan: WorkoutPlan, ordered_links: list[WorkoutTemplatePlan]):
    """(start, end, link) tuples matching existing generate() semantics."""
    cycles = plan.cycles or 1
    template_count = len(ordered_links)
    candidate_slots = []
    for cycle_idx in range(cycles):
        for pos, link in enumerate(ordered_links):
            occurrence_index = cycle_idx * template_count + pos
            slot_start = plan.start_dt + timedelta(
                days=occurrence_index * plan.interval
            )
            slot_end = slot_start + timedelta(minutes=link.template.duration)
            candidate_slots.append((slot_start, slot_end, link))
    return candidate_slots


def regenerate_workouts_from_plan(
    *,
    user,
    plan: WorkoutPlan,
    candidate_slots: list[tuple],
) -> tuple[int, list[int]]:
    """
    Delete this user's future workouts tied to the plan, then create slots.
    candidate_slots: list of (slot_start, slot_end, link: WorkoutTemplatePlan)
    Returns (deleted_count, created_workout_ids).
    """
    now = timezone.now()
    with transaction.atomic():
        deleted_count, _ = Workout.objects.filter(
            user=user,
            plan=plan,
            start_dt__gte=now,
        ).delete()
        created_ids = []
        for slot_start, slot_end, link in candidate_slots:
            workout = create_workout_with_template_items(
                user=user,
                template=link.template,
                start_dt=slot_start,
                end_dt=slot_end,
                plan=plan,
                title=link.template.title,
            )
            created_ids.append(workout.id)
    return deleted_count, created_ids


def replace_workout_items(workout: Workout, items_data: list[dict] | None) -> None:
    """Delete existing items and bulk_create from validated item dicts (or clear if empty)."""
    if items_data is None:
        return
    workout.items.all().delete()
    if items_data:
        WorkoutItem.objects.bulk_create(
            [WorkoutItem(workout=workout, **item) for item in items_data]
        )
