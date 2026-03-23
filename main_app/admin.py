from django.contrib import admin
from .models import MuscleGroup, Exercise, Workout, WorkoutItem, WorkoutTemplate, WorkoutTemplateItem, WorkoutPlan, WorkoutTemplatePlan
from django.utils import timezone
from django.contrib import messages

@admin.action(description="Create workout from template")
def create_workout_from_template(modeladmin, request, queryset):
    if queryset.count() > 1:
        modeladmin.message_user(request, "Please select only one template at a time.", level="error")
        return
    
    template = queryset.first()
    workout = Workout.objects.create(
        user=request.user,
        title=template.title,
        start_dt=timezone.now(),  # required field
        end_dt=timezone.now(),
        template=template,
    )

    for template_item in template.items.all():
        WorkoutItem.objects.create(
            workout=workout,
            exercise=template_item.exercise,
            sets=template_item.sets,
            reps=template_item.reps,
            weight=template_item.weight,
            weight_unit=template_item.weight_unit,
            duration_seconds=template_item.duration_seconds,
            distance_meters=template_item.distance_meters
        )
        
    modeladmin.message_user(request, f"Workout '{workout.title}' created successfully.")

class WorkoutItemInline(admin.TabularInline):
    model = WorkoutItem
    extra = 1  # Number of empty forms to display for adding new items

class WorkoutAdmin(admin.ModelAdmin):
    inlines = [WorkoutItemInline]

class WorkoutTemplateItemInline(admin.TabularInline):
    model = WorkoutTemplateItem
    extra = 1  # Number of empty forms to display for adding new items
    ordering = ['order', 'id']
    fk_name = 'template'

class WorkoutTemplateAdmin(admin.ModelAdmin):
    inlines = [WorkoutTemplateItemInline]
    actions = [create_workout_from_template]
    list_display = ("title", "user", "is_public", "is_rest_placeholder", "duration")

class WorkoutTemplatePlanInline(admin.TabularInline):
    model = WorkoutTemplatePlan
    extra = 1  # Number of empty forms to display for adding new items

class WorkoutPlanAdmin(admin.ModelAdmin):
    inlines = [WorkoutTemplatePlanInline]

admin.site.register(MuscleGroup)
admin.site.register(Exercise)
admin.site.register(Workout, WorkoutAdmin)
admin.site.register(WorkoutTemplate, WorkoutTemplateAdmin)
admin.site.register(WorkoutPlan, WorkoutPlanAdmin)