from rest_framework import serializers
from .models import MuscleGroup, Exercise
from django.contrib.auth.models import User

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)  # Add a password field, make it write-only

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password')

    def create(self, validated_data):
      user = User.objects.create_user(
          username=validated_data['username'],
          email=validated_data['email'],
          password=validated_data['password']  # Ensure the password is hashed
      )
      
      return user

class MuscleGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = MuscleGroup
        fields = '__all__'

class ExerciseSerializer(serializers.ModelSerializer):
    muscle_groups = MuscleGroupSerializer(many=True, read_only=True)
    muscle_group_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        write_only=True,
        source="muscle_groups",
        queryset=MuscleGroup.objects.all(),
        required=False,
    )
    
    class Meta:
        model = Exercise
        fields = '__all__'

