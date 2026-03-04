from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets, permissions, generics
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import ExerciseSerializer, MuscleGroupSerializer, UserSerializer
from .models import Exercise, MuscleGroup
from django.contrib.auth.models import User
from django.contrib.auth import authenticate

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

class MuscleGroupViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MuscleGroup.objects.all().order_by("name")
    serializer_class = MuscleGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

class ExerciseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Exercise.objects.all().order_by("name")
    serializer_class = ExerciseSerializer
    permission_classes = [permissions.IsAuthenticated]