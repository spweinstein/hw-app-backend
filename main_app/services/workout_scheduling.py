"""
Shared workout creation: calendar conflict rules, template item copy, plan generate.
Used by WorkoutSerializer, template schedule, and plan generate.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import APIException

from ..models import (
    Workout,
    WorkoutItem,
    WorkoutTemplate,
    WorkoutTemplateItem,
    WorkoutTemplatePlan,
)


class WorkoutScheduleConflictError(APIException):
    """Maps Workout model overlap validation to HTTP 409."""

    status_code = 409
    default_detail = "This workout conflicts with an existing workout on your calendar."
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


def _get_template_items(
    template: WorkoutTemplate,
    *,
    template_items_cache: dict[int, list[WorkoutTemplateItem]] | None = None,
) -> list[WorkoutTemplateItem]:
    """Return ordered template items, reusing an in-memory cache when available."""
    if template_items_cache is not None:
        cached_items = template_items_cache.get(template.pk)
        if cached_items is not None:
            return cached_items

    prefetched_items = getattr(template, "_prefetched_objects_cache", {}).get("items")
    if prefetched_items is not None:
        template_items = list(prefetched_items)
    else:
        template_items = list(
            template.items.select_related("exercise").order_by("order", "id")
        )

    if template_items_cache is not None:
        template_items_cache[template.pk] = template_items

    return template_items


def copy_template_items_to_workout(
    workout: Workout,
    template: WorkoutTemplate,
    *,
    template_items: list[WorkoutTemplateItem] | None = None,
) -> None:
    if template_items is None:
        template_items = _get_template_items(template)
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
    template_items: list[WorkoutTemplateItem] | None = None,
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
    copy_template_items_to_workout(
        workout,
        template,
        template_items=template_items,
    )
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


def parse_inclusive_end_date(raw, tz=None) -> date | None:
    """
    Parse end of generate range as a calendar date (inclusive).
    Accepts ISO date (YYYY-MM-DD) or datetime string.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if tz is None:
        tz = timezone.get_current_timezone()
    dt = parse_datetime(s)
    if dt is not None:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, tz)
        return timezone.localtime(dt, tz).date()
    d = parse_date(s)
    return d


def build_plan_slots_for_date_range(
    *,
    start_dt,
    end_date: date,
    ordered_links: list[WorkoutTemplatePlan],
    tz=None,
) -> list[tuple]:
    """
    One calendar day per link step (ordered cycle). Rest placeholders advance the day
    without a workout. Workouts use WorkoutTemplatePlan.time on that day.

    Returns list of (slot_start, slot_end, link) for non-rest templates only.
    """
    if not ordered_links:
        return []

    if tz is None:
        tz = timezone.get_current_timezone()
    cursor_date = timezone.localtime(start_dt, tz).date()
    if end_date < cursor_date:
        return []

    candidate_slots: list[tuple] = []
    i = 0
    n = len(ordered_links)

    while cursor_date <= end_date:
        link = ordered_links[i % n]
        if link.template.is_rest_placeholder:
            cursor_date = cursor_date + timedelta(days=1)
            i += 1
            continue

        slot_start = timezone.make_aware(
            datetime.combine(cursor_date, link.time),
            tz,
        )
        slot_end = slot_start + timedelta(minutes=link.template.duration)
        candidate_slots.append((slot_start, slot_end, link))
        cursor_date = cursor_date + timedelta(days=1)
        i += 1

    return candidate_slots


def create_workouts_from_plan_slots(
    *,
    user,
    plan,
    candidate_slots: list[tuple],
) -> list[int]:
    """
    Create workouts from plan slots (no deletes).
    candidate_slots: list of (slot_start, slot_end, link: WorkoutTemplatePlan)
    """
    created_ids: list[int] = []
    template_items_cache: dict[int, list[WorkoutTemplateItem]] = {}
    for slot_start, slot_end, link in candidate_slots:
        template_items = _get_template_items(
            link.template,
            template_items_cache=template_items_cache,
        )
        workout = create_workout_with_template_items(
            user=user,
            template=link.template,
            start_dt=slot_start,
            end_dt=slot_end,
            plan=plan,
            title=link.template.title,
            template_items=template_items,
        )
        created_ids.append(workout.id)
    return created_ids


def create_workouts_from_plan_slots_atomic(
    *,
    user,
    plan,
    candidate_slots: list[tuple],
) -> list[int]:
    """Same as create_workouts_from_plan_slots inside a single atomic block."""
    with transaction.atomic():
        return create_workouts_from_plan_slots(
            user=user, plan=plan, candidate_slots=candidate_slots
        )


def replace_workout_items(workout: Workout, items_data: list[dict] | None) -> None:
    """Delete existing items and bulk_create from validated item dicts (or clear if empty)."""
    if items_data is None:
        return
    workout.items.all().delete()
    if items_data:
        WorkoutItem.objects.bulk_create(
            [WorkoutItem(workout=workout, **item) for item in items_data]
        )
