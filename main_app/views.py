from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets, permissions, generics, status
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import ExerciseSerializer, MuscleGroupSerializer, UserSerializer, WorkoutSerializer, WorkoutItemSerializer, WorkoutTemplateSerializer, WorkoutTemplateItemSerializer, WorkoutPlanSerializer, WorkoutTemplatePlanSerializer, ProfileSerializer, WeightLogSerializer
from .models import Exercise, MuscleGroup, Workout, WorkoutItem, WorkoutTemplate, WorkoutTemplateItem, WorkoutPlan, WorkoutTemplatePlan, Profile, WeightLog

from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.utils.dateparse import parse_datetime
from django.db import models

from datetime import timedelta
from django.db import transaction
from django.db.models import Q, Prefetch
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework import status
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import PermissionDenied

from .services.workout_scheduling import (
    WorkoutScheduleConflictError,
    build_plan_candidate_slots,
    regenerate_workouts_from_plan,
    schedule_workout_from_template,
)

class ConflictError(Exception):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__("Workout schedule conflicts detected.")

# User Registration
class CreateUserView(generics.CreateAPIView):
  queryset = User.objects.all()
  serializer_class = UserSerializer

  def create(self, request, *args, **kwargs):
    response = super().create(request, *args, **kwargs)
    user = User.objects.get(username=response.data['username'])
    refresh = RefreshToken.for_user(user)
    return Response({
      'refresh': str(refresh),
      'access': str(refresh.access_token),
      'user': response.data
    })

# User Login
class LoginView(APIView):
  permission_classes = [permissions.AllowAny]

  def post(self, request):
    username = request.data.get('username')
    password = request.data.get('password')
    user = authenticate(username=username, password=password)
    if user:
      refresh = RefreshToken.for_user(user)
      return Response({
        'refresh': str(refresh),
        'access': str(refresh.access_token),
        'user': UserSerializer(user).data
      })
    return Response({'error': 'Invalid Credentials'}, status=status.HTTP_401_UNAUTHORIZED)

# User Verification
class VerifyUserView(APIView):
  permission_classes = [permissions.IsAuthenticated]

  def get(self, request):
    user = User.objects.get(username=request.user)  # Fetch user profile
    refresh = RefreshToken.for_user(request.user)  # Generate new refresh token
    return Response({
      'refresh': str(refresh),
      'access': str(refresh.access_token),
      'user': UserSerializer(user).data
    })
  
class IsOwnerOrReadOnlyPublic(permissions.BasePermission):
    """
    - Owners can do anything.
    - Non-owners can read if object has `is_public=True` (templates/plans).
    """
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            if hasattr(obj, "is_public") and obj.is_public:
                return True
            return getattr(obj, "user_id", None) == getattr(request.user, "id", None)
        return getattr(obj, "user_id", None) == getattr(request.user, "id", None)
    
class ProfileViewSet(viewsets.ModelViewSet):
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Limit profiles to the authenticated user
        return Profile.objects.filter(user=self.request.user)

    def get_object(self):
        # Always return (and if needed, create) the profile for the current user,
        # so frontend calls like /api/profiles/<userId>/ work even if the profile
        # doesn't yet exist.
        profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return profile


class WeightLogViewSet(viewsets.ModelViewSet):
    serializer_class = WeightLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return WeightLog.objects.filter(user=self.request.user).order_by("date")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class MuscleGroupViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MuscleGroup.objects.all().order_by("name")
    serializer_class = MuscleGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

class ExerciseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Exercise.objects.all().order_by("name")
    serializer_class = ExerciseSerializer
    permission_classes = [permissions.IsAuthenticated]

class WorkoutViewSet(viewsets.ModelViewSet):
    serializer_class = WorkoutSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Workout.objects.filter(user=self.request.user).order_by("start_dt", "id")

        # Optional date filtering for calendar views:
        # GET /api/workouts/?start=2026-03-01T00:00:00Z&end=2026-04-01T00:00:00Z
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        if start and end:
            start_dt = parse_datetime(start)
            end_dt = parse_datetime(end)
            if not start_dt or not end_dt:
                raise ValidationError("Invalid start/end. Use ISO datetime strings.")
            qs = qs.filter(start_dt__gte=start_dt, start_dt__lt=end_dt)

        return qs

class WorkoutItemViewSet(viewsets.ModelViewSet):
    serializer_class = WorkoutItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return WorkoutItem.objects.filter(workout__user=self.request.user).order_by("order", "id")

    def perform_create(self, serializer):
        workout = serializer.validated_data["workout"]
        if workout.user != self.request.user:
            raise ValidationError("You do not own this workout.")
        serializer.save()

class WorkoutTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = WorkoutTemplateSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnlyPublic]

    def get_permissions(self):
        # Schedule creates a workout for the current user from any template they can read
        # (own or public); IsOwnerOrReadOnlyPublic would block POST on others' templates.
        if getattr(self, "action", None) == "schedule":
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        scope = self.request.query_params.get("scope", "all")  # default: "all"

        if scope == "public":
            return WorkoutTemplate.objects.filter(is_public=True).order_by("-updated_at")
        elif scope == "user":
            return WorkoutTemplate.objects.filter(user=self.request.user).order_by("-updated_at")
        else:
            return WorkoutTemplate.objects.filter(
                (models.Q(user=self.request.user) | models.Q(is_public=True))
            ).distinct().order_by("-updated_at")

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        template = self.get_object()
        start_raw = request.data.get("start_dt")
        if not start_raw:
            raise ValidationError({"start_dt": "This field is required."})
        start_dt = parse_datetime(str(start_raw).strip())
        if start_dt is None:
            raise ValidationError({"start_dt": "Invalid datetime. Use ISO 8601 format."})
        if timezone.is_naive(start_dt):
            start_dt = timezone.make_aware(
                start_dt, timezone.get_current_timezone()
            )

        try:
            with transaction.atomic():
                workout = schedule_workout_from_template(
                    user=request.user,
                    template=template,
                    start_dt=start_dt,
                )
        except DjangoValidationError as e:
            raise WorkoutScheduleConflictError(django_error=e) from e

        workout = (
            Workout.objects.filter(pk=workout.pk)
            .prefetch_related(
                Prefetch(
                    "items",
                    queryset=WorkoutItem.objects.select_related("exercise").order_by(
                        "order", "id"
                    ),
                )
            )
            .get()
        )
        serializer = WorkoutSerializer(workout, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class WorkoutTemplateItemViewSet(viewsets.ModelViewSet):
    serializer_class = WorkoutTemplateItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Only items belonging to templates you own (or public templates if you want view-only)
        return WorkoutTemplateItem.objects.filter(template__user=self.request.user).order_by("order", "id")

    def perform_create(self, serializer):
        # Force template ownership check
        template = serializer.validated_data["template"]
        if template.user != self.request.user:
            raise ValidationError("You do not own this template.")
        serializer.save()


class WorkoutPlanViewSet(viewsets.ModelViewSet):
    serializer_class = WorkoutPlanSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnlyPublic]

    def get_permissions(self):
        """
        Override to allow generate action for public plans.
        """
        if self.action == 'generate':
            # For generate action, only require authentication
            # We'll check plan ownership/public status in the method itself
            return [permissions.IsAuthenticated()]
        # For other actions, use the default permissions
        return super().get_permissions()


    def get_queryset(self):
        # CRITICAL: Prefetch with explicit ordering to ensure correct order
        ordered_links = Prefetch(
            "template_links",
            queryset=WorkoutTemplatePlan.objects
                .select_related("template")
                .order_by("order", "id"),
        )

        scope = self.request.query_params.get("scope", "all")

        base_qs = WorkoutPlan.objects.prefetch_related(ordered_links)

        if scope == "public":
            return base_qs.filter(is_public=True).order_by("-updated_at")
        elif scope == "user":
            return base_qs.filter(user=self.request.user).order_by("-updated_at")
        else:
            return (
                base_qs
                .filter(Q(user=self.request.user) | Q(is_public=True))
                .distinct()
                .order_by("-updated_at")
            )

    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        plan = self.get_object()
        if not plan.is_public and plan.user != request.user:
            raise PermissionDenied("You can only generate workouts from your own plans or public plans.")
        
        cycles = plan.cycles or 1 
        if cycles < 1:
            raise ValidationError("cycles must be >= 1")

        links = (
            WorkoutTemplatePlan.objects
            .filter(plan=plan)
            .select_related("template")
            .prefetch_related("template__items__exercise")
            .order_by("order", "id")
        )
        if not links.exists():
            raise ValidationError("Plan has no templates.")

        ordered_links = list(links)
        candidate_slots = build_plan_candidate_slots(plan, ordered_links)

        try:
            deleted_count, created_ids = regenerate_workouts_from_plan(
                user=request.user,
                plan=plan,
                candidate_slots=candidate_slots,
            )
        except DjangoValidationError as e:
            raise WorkoutScheduleConflictError(
                django_error=e,
                detail_message="Generated workouts conflict with existing calendar workouts.",
            ) from e

        return Response(
            {
                "plan_id": plan.id,
                "cycles": cycles,
                "deleted_future_generated_count": deleted_count,
                "created_count": len(created_ids),
                "workout_ids": created_ids,
            },
            status=status.HTTP_201_CREATED,
        )

class WorkoutTemplatePlanViewSet(viewsets.ModelViewSet):
    serializer_class = WorkoutTemplatePlanSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = (
            WorkoutTemplatePlan.objects.select_related("plan", "template")
            .order_by("plan_id", "order", "id")
        )
        scope = self.request.query_params.get("scope", "all")
        if scope == "public":
            return qs.filter(plan__is_public=True)
        if scope == "user":
            return qs.filter(plan__user=self.request.user)
        return qs.filter(
            Q(plan__user=self.request.user) | Q(plan__is_public=True)
        ).distinct()

    def perform_create(self, serializer):
        plan = serializer.validated_data["plan"]
        template = serializer.validated_data["template"]
        if plan.user != self.request.user:
            raise ValidationError("You do not own this plan.")
        if template.user != self.request.user and not template.is_public:
            raise ValidationError("You can only attach your own templates (or public templates, if allowed).")
        serializer.save()