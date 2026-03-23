from datetime import date, datetime, time as time_cls, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    Workout,
    WorkoutPlan,
    WorkoutTemplate,
    WorkoutTemplatePlan,
)
from .services.workout_scheduling import (
    build_plan_slots_for_date_range,
    parse_inclusive_end_date,
)


class BuildPlanSlotsForDateRangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("slotuser", password="testpass123")
        self.t_push = WorkoutTemplate.objects.create(
            user=self.user, title="Push", duration=60
        )
        self.t_rest = WorkoutTemplate.objects.create(
            user=self.user,
            title="Rest",
            duration=1,
            is_rest_placeholder=True,
        )
        self.plan = WorkoutPlan.objects.create(user=self.user, title="PPL")
        WorkoutTemplatePlan.objects.create(
            plan=self.plan,
            template=self.t_push,
            order=0,
            time=time_cls(10, 0),
        )
        WorkoutTemplatePlan.objects.create(
            plan=self.plan,
            template=self.t_rest,
            order=1,
            time=time_cls(12, 0),
        )
        WorkoutTemplatePlan.objects.create(
            plan=self.plan,
            template=self.t_push,
            order=2,
            time=time_cls(14, 0),
        )
        self.links = list(
            WorkoutTemplatePlan.objects.filter(plan=self.plan)
            .select_related("template")
            .order_by("order", "id")
        )

    def test_rest_consumes_day_three_days_two_workouts(self):
        start_dt = timezone.make_aware(datetime(2026, 6, 1, 8, 0, 0))
        end_date = date(2026, 6, 3)
        slots = build_plan_slots_for_date_range(
            start_dt=start_dt,
            end_date=end_date,
            ordered_links=self.links,
        )
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0][2].template_id, self.t_push.id)
        self.assertEqual(slots[1][2].template_id, self.t_push.id)
        self.assertEqual(
            timezone.localtime(slots[0][0]).date(), date(2026, 6, 1)
        )
        self.assertEqual(
            timezone.localtime(slots[1][0]).date(), date(2026, 6, 3)
        )

    def test_inclusive_end_empty_when_start_after_end(self):
        start_dt = timezone.make_aware(datetime(2026, 6, 10, 8, 0, 0))
        slots = build_plan_slots_for_date_range(
            start_dt=start_dt,
            end_date=date(2026, 6, 1),
            ordered_links=self.links,
        )
        self.assertEqual(slots, [])


class ParseInclusiveEndDateTests(TestCase):
    def test_iso_date_string(self):
        self.assertEqual(
            parse_inclusive_end_date("2026-03-22"), date(2026, 3, 22)
        )

    def test_datetime_string_uses_local_date(self):
        d = parse_inclusive_end_date("2026-03-22T15:30:00")
        self.assertEqual(d, date(2026, 3, 22))


class RestTemplateScheduleAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("scheduser", password="testpass123")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.rest_tpl = WorkoutTemplate.objects.create(
            user=self.user,
            title="Rest block",
            duration=1,
            is_rest_placeholder=True,
        )

    def test_schedule_rejects_rest_placeholder(self):
        url = f"/api/workout-templates/{self.rest_tpl.id}/schedule/"
        start = timezone.now().replace(microsecond=0) + timedelta(days=1)
        resp = self.client.post(
            url,
            {"start_dt": start.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class PlanGenerateAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("genuser", password="testpass123")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.tpl = WorkoutTemplate.objects.create(
            user=self.user, title="Lift", duration=45
        )
        self.plan = WorkoutPlan.objects.create(user=self.user, title="Week")
        WorkoutTemplatePlan.objects.create(
            plan=self.plan,
            template=self.tpl,
            order=0,
            time=time_cls(9, 0),
        )

    def test_generate_does_not_delete_existing_future_plan_workouts(self):
        far = timezone.now() + timedelta(days=365)
        existing = Workout.objects.create(
            user=self.user,
            plan=self.plan,
            template=self.tpl,
            title="Existing",
            start_dt=far,
            end_dt=far + timedelta(minutes=45),
        )

        start = timezone.make_aware(datetime(2030, 1, 1, 9, 0, 0))
        end_d = date(2030, 1, 2)
        url = f"/api/workout-plans/{self.plan.id}/generate/"
        resp = self.client.post(
            url,
            {"start_dt": start.isoformat(), "end_dt": end_d.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Workout.objects.filter(pk=existing.pk).exists(),
            "Existing future plan workout should not be deleted",
        )
        ids = resp.data.get("workout_ids") or []
        self.assertEqual(len(ids), 2)
