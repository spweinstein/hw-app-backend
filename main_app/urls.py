from django.urls import path, include
from .views import MuscleGroupViewSet, ExerciseViewSet, CreateUserView, LoginView, VerifyUserView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register("muscle-groups", MuscleGroupViewSet, basename="musclegroup")
router.register("exercises", ExerciseViewSet, basename="exercise")

urlpatterns = [
  path('api/', include(router.urls)),
  path('users/register/', CreateUserView.as_view(), name='register'),
  path('users/login/', LoginView.as_view(), name='login'),
  path('users/token/refresh/', VerifyUserView.as_view(), name='token_refresh'),
]