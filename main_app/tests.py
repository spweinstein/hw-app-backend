from datetime import date, datetime, time as time_cls, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    Exercise,
    Workout,
    WorkoutItem,
    WorkoutPlan,
    WorkoutTemplate,
    WorkoutTemplateItem,
    WorkoutTemplatePlan,
)
from .services.workout_scheduling import (
    build_plan_slots_for_date_range,
    create_workouts_from_plan_slots_atomic,
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

    def test_datetime_string_uses_supplied_timezone(self):
        end_raw = "2030-01-02T00:30:00+14:00"
        client_tz = ZoneInfo("Pacific/Kiritimati")

        self.assertEqual(
            parse_inclusive_end_date(end_raw, tz=client_tz),
            date(2030, 1, 2),
        )


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
        tz_name = timezone.get_current_timezone_name()
        url = f"/api/workout-plans/{self.plan.id}/generate/"
        resp = self.client.post(
            url,
            {
                "start_dt": start.isoformat(),
                "end_dt": end_d.isoformat(),
                "tz": tz_name,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Workout.objects.filter(pk=existing.pk).exists(),
            "Existing future plan workout should not be deleted",
        )
        ids = resp.data.get("workout_ids") or []
        self.assertEqual(len(ids), 2)

    def test_generate_uses_client_timezone_for_inclusive_end_date(self):
        client_tz = ZoneInfo("Pacific/Kiritimati")
        start = timezone.make_aware(datetime(2030, 1, 1, 9, 0, 0), client_tz)
        end_raw = "2030-01-02T00:30:00+14:00"
        url = f"/api/workout-plans/{self.plan.id}/generate/"

        resp = self.client.post(
            url,
            {
                "start_dt": start.isoformat(),
                "end_dt": end_raw,
                "tz": "Pacific/Kiritimati",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["start_date"], "2030-01-01")
        self.assertEqual(resp.data["end_date"], "2030-01-02")
        self.assertEqual(resp.data["created_count"], 2)
        self.assertEqual(len(resp.data.get("workout_ids") or []), 2)


class PlanGenerateCacheTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("cacheuser", password="testpass123")
        self.exercise = Exercise.objects.create(name="Bench Press")
        self.plan = WorkoutPlan.objects.create(user=self.user, title="Cache Week")

        self.push = WorkoutTemplate.objects.create(
            user=self.user,
            title="Push",
            duration=45,
        )
        self.pull = WorkoutTemplate.objects.create(
            user=self.user,
            title="Pull",
            duration=50,
        )

        for template in (self.push, self.pull):
            WorkoutTemplateItem.objects.create(
                template=template,
                exercise=self.exercise,
                order=0,
                sets=3,
                reps=8,
            )

        self.push_link = WorkoutTemplatePlan.objects.create(
            plan=self.plan,
            template=self.push,
            order=0,
            time=time_cls(9, 0),
        )
        self.pull_link = WorkoutTemplatePlan.objects.create(
            plan=self.plan,
            template=self.pull,
            order=1,
            time=time_cls(10, 0),
        )

    def test_reuses_template_items_across_repeated_slots(self):
        start = timezone.make_aware(datetime(2030, 1, 1, 9, 0, 0))
        candidate_slots = [
            (start, start + timedelta(minutes=45), self.push_link),
            (
                start + timedelta(days=1),
                start + timedelta(days=1, minutes=50),
                self.pull_link,
            ),
            (start + timedelta(days=2), start + timedelta(days=2, minutes=45), self.push_link),
            (
                start + timedelta(days=3),
                start + timedelta(days=3, minutes=50),
                self.pull_link,
            ),
        ]

        with CaptureQueriesContext(connection) as ctx:
            created_ids = create_workouts_from_plan_slots_atomic(
                user=self.user,
                plan=self.plan,
                candidate_slots=candidate_slots,
            )

        self.assertEqual(len(created_ids), 4)
        template_item_queries = [
            q
            for q in ctx.captured_queries
            if q["sql"].lstrip().upper().startswith("SELECT")
            and "main_app_workouttemplateitem" in q["sql"]
        ]
        self.assertLessEqual(
            len(template_item_queries),
            len({slot[2].template_id for slot in candidate_slots}),
        )


class AuthAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_returns_tokens_and_user(self):
        resp = self.client.post(
            "/users/register/",
            {
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "testpass123",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("refresh", resp.data)
        self.assertIn("access", resp.data)
        self.assertEqual(resp.data["user"]["username"], "newuser")
        self.assertTrue(User.objects.filter(username="newuser").exists())

    def test_register_rejects_duplicate_username(self):
        payload = {
            "username": "dupuser",
            "email": "dupuser@example.com",
            "password": "testpass123",
        }
        first = self.client.post("/users/register/", payload, format="json")
        second = self.client.post("/users/register/", payload, format="json")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_returns_tokens_for_valid_credentials(self):
        User.objects.create_user("loginuser", password="testpass123")

        resp = self.client.post(
            "/users/login/",
            {"username": "loginuser", "password": "testpass123"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("refresh", resp.data)
        self.assertIn("access", resp.data)
        self.assertEqual(resp.data["user"]["username"], "loginuser")

    def test_login_rejects_invalid_credentials(self):
        User.objects.create_user("loginuser", password="testpass123")

        resp = self.client.post(
            "/users/login/",
            {"username": "loginuser", "password": "wrong-password"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_verify_user_returns_authenticated_user_payload(self):
        register_resp = self.client.post(
            "/users/register/",
            {
                "username": "verifyuser",
                "email": "verifyuser@example.com",
                "password": "testpass123",
            },
            format="json",
        )

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {register_resp.data['access']}"
        )
        resp = self.client.get("/users/token/refresh/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("refresh", resp.data)
        self.assertIn("access", resp.data)
        self.assertEqual(resp.data["user"]["username"], "verifyuser")


class PublicCatalogPaginationAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("cataloguser", password="testpass123")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.public_templates = [
            WorkoutTemplate.objects.create(
                user=self.user,
                title="Alpha template",
                description="First public template",
                duration=30,
                is_public=True,
            ),
            WorkoutTemplate.objects.create(
                user=self.user,
                title="Beta template",
                description="Second public template",
                duration=40,
                is_public=True,
            ),
            WorkoutTemplate.objects.create(
                user=self.user,
                title="Gamma template",
                description="Third public template",
                duration=50,
                is_public=True,
            ),
        ]
        WorkoutTemplate.objects.create(
            user=self.user,
            title="Hidden template",
            description="Private template",
            duration=60,
        )

        self.public_plans = [
            WorkoutPlan.objects.create(
                user=self.user,
                title="Alpha plan",
                description="First public plan",
                is_public=True,
            ),
            WorkoutPlan.objects.create(
                user=self.user,
                title="Beta plan",
                description="Second public plan",
                is_public=True,
            ),
            WorkoutPlan.objects.create(
                user=self.user,
                title="Gamma plan",
                description="Third public plan",
                is_public=True,
            ),
        ]
        WorkoutPlan.objects.create(
            user=self.user,
            title="Hidden plan",
            description="Private plan",
        )

    def _assert_page_response(self, response, expected_count, expected_len):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)
        self.assertEqual(response.data["count"], expected_count)
        self.assertEqual(len(response.data["results"]), expected_len)

    def test_public_templates_are_paginated_and_searchable(self):
        page1 = self.client.get(
            "/api/workout-templates/",
            {"scope": "public", "page": 1, "page_size": 2},
            format="json",
        )
        self._assert_page_response(page1, expected_count=3, expected_len=2)

        search = self.client.get(
            "/api/workout-templates/",
            {"scope": "public", "search": "beta", "page": 1, "page_size": 2},
            format="json",
        )
        self._assert_page_response(search, expected_count=1, expected_len=1)
        self.assertEqual(search.data["results"][0]["title"], "Beta template")

    def test_public_plans_are_paginated_and_searchable(self):
        page1 = self.client.get(
            "/api/workout-plans/",
            {"scope": "public", "page": 1, "page_size": 2},
            format="json",
        )
        self._assert_page_response(page1, expected_count=3, expected_len=2)

        search = self.client.get(
            "/api/workout-plans/",
            {"scope": "public", "search": "beta", "page": 1, "page_size": 2},
            format="json",
        )
        self._assert_page_response(search, expected_count=1, expected_len=1)
        self.assertEqual(search.data["results"][0]["title"], "Beta plan")


class WorkoutConflictTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("conflictuser", password="testpass123")

    def _create_workout(self, start_hour, end_hour, title="Workout"):
        return Workout.objects.create(
            user=self.user,
            title=title,
            start_dt=timezone.make_aware(datetime(2026, 6, 1, start_hour, 0, 0)),
            end_dt=timezone.make_aware(datetime(2026, 6, 1, end_hour, 0, 0)),
        )

    def test_overlapping_workouts_raise_validation_error(self):
        self._create_workout(9, 10)

        with self.assertRaises(DjangoValidationError):
            self._create_workout(9, 11, title="Overlap")

    def test_adjacent_workouts_are_allowed(self):
        self._create_workout(9, 10)
        adjacent = self._create_workout(10, 11, title="Adjacent")

        self.assertIsNotNone(adjacent.pk)
        self.assertEqual(Workout.objects.count(), 2)

    def test_saving_existing_workout_in_same_slot_is_allowed(self):
        workout = self._create_workout(9, 10)
        workout.notes = "Updated notes"

        workout.save()

        self.assertEqual(Workout.objects.count(), 1)
        self.assertEqual(workout.notes, "Updated notes")


class WorkoutOwnershipAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="testpass123")
        self.other = User.objects.create_user("other", password="testpass123")
        self.client = APIClient()
        self.owned_workout = Workout.objects.create(
            user=self.owner,
            title="Owner workout",
            start_dt=timezone.make_aware(datetime(2026, 7, 1, 9, 0, 0)),
            end_dt=timezone.make_aware(datetime(2026, 7, 1, 10, 0, 0)),
        )
        self.other_workout = Workout.objects.create(
            user=self.other,
            title="Other workout",
            start_dt=timezone.make_aware(datetime(2026, 7, 1, 11, 0, 0)),
            end_dt=timezone.make_aware(datetime(2026, 7, 1, 12, 0, 0)),
        )

    def _response_items(self, response):
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]
        return response.data

    def test_workout_crud_is_scoped_to_authenticated_user(self):
        self.client.force_authenticate(user=self.other)

        list_resp = self.client.get("/api/workouts/")
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)

        items = self._response_items(list_resp)
        returned_ids = {item["id"] for item in items}
        self.assertIn(self.other_workout.id, returned_ids)
        self.assertNotIn(self.owned_workout.id, returned_ids)

        detail_url = f"/api/workouts/{self.owned_workout.id}/"
        self.assertEqual(
            self.client.get(detail_url).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.patch(detail_url, {"notes": "nope"}, format="json").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.delete(detail_url).status_code,
            status.HTTP_404_NOT_FOUND,
        )


class WorkoutPlanTemplateAccessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("planowner", password="testpass123")
        self.other = User.objects.create_user("otheruser", password="testpass123")
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

        self.private_template = WorkoutTemplate.objects.create(
            user=self.other,
            title="Hidden template",
            duration=30,
        )
        self.plan = WorkoutPlan.objects.create(user=self.owner, title="Owned plan")

    def test_create_rejects_unauthorized_template_ids(self):
        resp = self.client.post(
            "/api/workout-plans/",
            {
                "title": "New plan",
                "description": "",
                "is_public": False,
                "template_links": [
                    {
                        "template": self.private_template.id,
                        "order": 0,
                        "time": "09:00:00",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("You don't have access to templates", str(resp.data))
        self.assertFalse(WorkoutPlan.objects.filter(title="New plan").exists())

    def test_update_rejects_unauthorized_template_ids(self):
        resp = self.client.patch(
            f"/api/workout-plans/{self.plan.id}/",
            {
                "template_links": [
                    {
                        "template": self.private_template.id,
                        "order": 0,
                        "time": "09:00:00",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("You don't have access to templates", str(resp.data))
        self.assertEqual(self.plan.template_links.count(), 0)


class WorkoutCalendarListAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("caluser", password="testpass123")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.exercise = Exercise.objects.create(name="Push-up")
        self.start_dt = timezone.make_aware(datetime(2030, 1, 1, 9, 0, 0))
        self.workout = Workout.objects.create(
            user=self.user,
            title="Morning",
            start_dt=self.start_dt,
            end_dt=self.start_dt + timedelta(hours=1),
        )
        WorkoutItem.objects.create(
            workout=self.workout,
            exercise=self.exercise,
            order=0,
        )

    def test_calendar_range_list_uses_slim_shape(self):
        resp = self.client.get(
            "/api/workouts/",
            {
                "start": self.start_dt.isoformat(),
                "end": (self.start_dt + timedelta(days=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(
            set(resp.data[0].keys()),
            {"id", "title", "start_dt", "end_dt", "status", "notes"},
        )
        self.assertNotIn("items", resp.data[0])

    def test_workout_detail_still_returns_nested_items(self):
        resp = self.client.get(f"/api/workouts/{self.workout.id}/", format="json")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("items", resp.data)
        self.assertEqual(len(resp.data["items"]), 1)
