from rest_framework import serializers
from .models import (
    MuscleGroup,
    Exercise,
    Workout,
    WorkoutItem,
    WorkoutTemplate,
    WorkoutTemplateItem,
    WorkoutPlan,
    WorkoutTemplatePlan,
    Profile,
    WeightLog,
)
from django.contrib.auth.models import User
from django.db import transaction

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

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ["id", "height"]


class WeightLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeightLog
        fields = ["id", "user", "weight", "date"]


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


class WorkoutItemSerializer(serializers.ModelSerializer):
    exercise_detail = ExerciseSerializer(source="exercise", read_only=True)

    class Meta:
        model = WorkoutItem
        fields = [
            "id",
            "workout",
            "exercise",
            "exercise_detail",
            "order",
            "sets",
            "reps",
            "weight",
            "weight_unit",
            "duration",
            "distance",
            "rpe",
            "notes",
        ]
        read_only_fields = ["workout"]


class WorkoutSerializer(serializers.ModelSerializer):
    items = WorkoutItemSerializer(many=True, required=False)

    class Meta:
        model = Workout
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at"]

    def create(self, validated_data):
        request = self.context["request"]
        items_data = validated_data.pop("items", [])
        validated_data["user"] = request.user

        with transaction.atomic():
            workout = Workout.objects.create(**validated_data)
            if items_data:
                WorkoutItem.objects.bulk_create(
                    [WorkoutItem(workout=workout, **item) for item in items_data]
                )
        return workout

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)

        with transaction.atomic():
            for attr, val in validated_data.items():
                setattr(instance, attr, val)
            instance.save()

            if items_data is not None:
                instance.items.all().delete()
                if items_data:
                    WorkoutItem.objects.bulk_create(
                        [WorkoutItem(workout=instance, **item) for item in items_data]
                    )
        return instance
    
class WorkoutTemplateItemSerializer(serializers.ModelSerializer):
    exercise_detail = ExerciseSerializer(source="exercise", read_only=True)

    class Meta:
        model = WorkoutTemplateItem
        fields = "__all__"
        read_only_fields = ["template"]


class WorkoutTemplateSerializer(serializers.ModelSerializer):
    items = WorkoutTemplateItemSerializer(many=True, required=False)
    # If you want an easy "copy" action later, keeping source_template is helpful.
    source_template = serializers.PrimaryKeyRelatedField(
        queryset=WorkoutTemplate.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = WorkoutTemplate
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at"]

    def create(self, validated_data):
        request = self.context["request"]
        items_data = validated_data.pop("items", [])
        validated_data["user"] = request.user

        with transaction.atomic():
            template = WorkoutTemplate.objects.create(**validated_data)
            if items_data:
                WorkoutTemplateItem.objects.bulk_create(
                    [
                        WorkoutTemplateItem(template=template, **item)
                        for item in items_data
                    ]
                )
        return template

    def update(self, instance, validated_data):
        # - Update template fields
        # - If `items` is provided, replace all items (delete + recreate)
        items_data = validated_data.pop("items", None)

        with transaction.atomic():
            for attr, val in validated_data.items():
                setattr(instance, attr, val)
            instance.save()

            if items_data is not None:
                instance.items.all().delete()
                if items_data:
                    WorkoutTemplateItem.objects.bulk_create(
                        [
                            WorkoutTemplateItem(template=instance, **item)
                            for item in items_data
                        ]
                    )
        return instance

class WorkoutTemplatePlanSerializer(serializers.ModelSerializer):
    template_detail = WorkoutTemplateSerializer(source="template", read_only=True)

    class Meta:
        model = WorkoutTemplatePlan
        fields = "__all__"
        read_only_fields = ["plan"]

class WorkoutPlanSerializer(serializers.ModelSerializer):
    # Write: send list of through-table objects
    template_links = WorkoutTemplatePlanSerializer(
        many=True, required=False, source="workouttemplateplan_set"
    )

    class Meta:
        model = WorkoutPlan
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at"]

    def create(self, validated_data):
        request = self.context["request"]
        links_data = validated_data.pop("workouttemplateplan_set", [])
        validated_data["user"] = request.user

        with transaction.atomic():
            plan = WorkoutPlan.objects.create(**validated_data)
            if links_data:
                WorkoutTemplatePlan.objects.bulk_create(
                    [
                        WorkoutTemplatePlan(plan=plan, **link)
                        for link in links_data
                    ]
                )
        return plan

    def update(self, instance, validated_data):
        links_data = validated_data.pop("workouttemplateplan_set", None)

        with transaction.atomic():
            for attr, val in validated_data.items():
                setattr(instance, attr, val)
            instance.save()

            if links_data is not None:
                # Replace links if provided
                WorkoutTemplatePlan.objects.filter(plan=instance).delete()
                if links_data:
                    WorkoutTemplatePlan.objects.bulk_create(
                        [
                            WorkoutTemplatePlan(plan=instance, **link)
                            for link in links_data
                        ]
                    )
        return instance