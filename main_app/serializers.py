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
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)  # Add a password field, make it write-only
    email = serializers.EmailField(required=False, allow_blank=True)  # Make email optional

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password')

    def create(self, validated_data):
      user = User.objects.create_user(
          username=validated_data['username'],
          email=validated_data.get('email', ''),
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
        read_only_fields = ["user"]


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
            "distance_unit",
            "rpe",
            "notes",
        ]
        
        read_only_fields = ["workout"]


class WorkoutSerializer(serializers.ModelSerializer):
    items = WorkoutItemSerializer(many=True, required=False)

    class Meta:
        model = Workout
        fields = "__all__"
        read_only_fields = ["user","created_at", "updated_at"]

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


class WorkoutCalendarSerializer(serializers.ModelSerializer):
    """Slim workout shape for calendar list responses."""

    class Meta:
        model = Workout
        fields = ["id", "title", "start_dt", "end_dt", "status", "notes"]
    
class WorkoutTemplateItemSerializer(serializers.ModelSerializer):
    exercise_detail = ExerciseSerializer(source="exercise", read_only=True)

    class Meta:
        model = WorkoutTemplateItem
        fields = "__all__"
        read_only_fields = ["template"]


class WorkoutTemplateSerializer(serializers.ModelSerializer):
    items = WorkoutTemplateItemSerializer(many=True, required=False)
    username = serializers.CharField(
        source="user.username", read_only=True
    )
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

        if validated_data.get("is_rest_placeholder") and items_data:
            raise serializers.ValidationError(
                {"items": "Rest placeholder templates cannot include exercises."}
            )

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

        is_rest_placeholder = validated_data.get(
            "is_rest_placeholder", instance.is_rest_placeholder
        )
        if is_rest_placeholder and items_data:
            raise serializers.ValidationError(
                {"items": "Rest placeholder templates cannot include exercises."}
            )

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
            elif instance.is_rest_placeholder:
                instance.items.all().delete()
        return instance

class WorkoutTemplatePlanSerializer(serializers.ModelSerializer):
    template_detail = WorkoutTemplateSerializer(source="template", read_only=True)

    class Meta:
        model = WorkoutTemplatePlan
        fields = "__all__"
        read_only_fields = ["plan"]

class WorkoutPlanSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        source="user.username", read_only=True
    )
    # Write: send list of through-table objects
    template_links = WorkoutTemplatePlanSerializer(
        many=True, required=False
    )

    class Meta:
        model = WorkoutPlan
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at", "user"]


    def _validate_and_resolve_template_links(self, links_data, user):
        """Validate access and resolve template objects in link dicts.

        Returns None when links_data is None (field omitted), an empty list
        when links_data is empty, or a cleaned list with 'id' stripped and
        template foreign keys replaced with resolved model instances.
        Raises ValidationError if any template is inaccessible to the user.
        """
        if links_data is None:
            return None
        if not links_data:
            return []

        template_ids = []
        for link in links_data:
            template = link.get("template")
            if template is not None:
                template_ids.append(template.id if hasattr(template, "id") else template)

        valid_templates = WorkoutTemplate.objects.filter(
            Q(id__in=template_ids) & (Q(user=user) | Q(is_public=True))
        )
        template_map = {t.id: t for t in valid_templates}

        invalid_ids = set(template_ids) - set(template_map.keys())
        if invalid_ids:
            raise serializers.ValidationError(
                {"template_links": f"You don't have access to templates: {sorted(invalid_ids)}"}
            )

        cleaned_links = []
        for link in links_data:
            cleaned = {k: v for k, v in link.items() if k != "id"}
            template = cleaned.get("template")
            if template is not None:
                template_id = template.id if hasattr(template, "id") else template
                cleaned["template"] = template_map[template_id]
            cleaned_links.append(cleaned)

        return cleaned_links

    def create(self, validated_data):
        request = self.context["request"]
        links_data = validated_data.pop("template_links", [])
        validated_data["user"] = request.user

        # Returns cleaned links: id stripped, template objects resolved and access-checked.
        clean_links = self._validate_and_resolve_template_links(links_data, request.user)

        with transaction.atomic():
            plan = WorkoutPlan.objects.create(**validated_data)
            if clean_links:
                WorkoutTemplatePlan.objects.bulk_create(
                    [WorkoutTemplatePlan(plan=plan, **link) for link in clean_links]
                )
        return plan

    def update(self, instance, validated_data):
        links_data = validated_data.pop("template_links", None)
        request = self.context["request"]

        # Returns cleaned links: id stripped, template objects resolved and access-checked.
        # None means the field was omitted (no-op); [] means explicitly cleared.
        clean_links = self._validate_and_resolve_template_links(links_data, request.user)

        with transaction.atomic():
            for attr, val in validated_data.items():
                setattr(instance, attr, val)
            instance.save()

            if links_data is not None:
                # Replace links if provided
                WorkoutTemplatePlan.objects.filter(plan=instance).delete()
                if clean_links:
                    WorkoutTemplatePlan.objects.bulk_create(
                        [WorkoutTemplatePlan(plan=instance, **link) for link in clean_links]
                    )
            
            # Refresh the instance from database to get updated template_links
            instance.refresh_from_db()
            # Clear the prefetch cache to force reload
            if hasattr(instance, '_prefetched_objects_cache'):
                instance._prefetched_objects_cache = {}
        
        return instance

    def to_representation(self, instance):
        """Sort template_links by order then id for stable client-side rendering."""
        representation = super().to_representation(instance)
        if representation.get('template_links'):
            representation['template_links'].sort(
                key=lambda x: (x.get('order', 0), x.get('id', 0))
            )
        return representation
