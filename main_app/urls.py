from django.urls import path, include
from .views import MuscleGroupViewSet, ExerciseViewSet, WorkoutViewSet, WorkoutItemViewSet, WorkoutTemplateViewSet, WorkoutTemplateItemViewSet, WorkoutPlanViewSet, WorkoutTemplatePlanViewSet, CreateUserView, LoginView, VerifyUserView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register("muscle-groups", MuscleGroupViewSet, basename="musclegroup")
router.register("exercises", ExerciseViewSet, basename="exercise")
router.register("workouts", WorkoutViewSet, basename="workout")
router.register("workout-items", WorkoutItemViewSet, basename="workout-item")
router.register("workout-templates", WorkoutTemplateViewSet, basename="workout-template")
router.register("workout-template-items", WorkoutTemplateItemViewSet, basename="workout-template-item")
router.register("workout-plans", WorkoutPlanViewSet, basename="workout-plan")
router.register("workout-template-plans", WorkoutTemplatePlanViewSet, basename="workout-template-plan")

urlpatterns = [
  path('api/', include(router.urls)),
  path('users/register/', CreateUserView.as_view(), name='register'),
  path('users/login/', LoginView.as_view(), name='login'),
  path('users/token/refresh/', VerifyUserView.as_view(), name='token_refresh'),
]