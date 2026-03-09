# HW App – Backend

The **Health is Wealth (HW) App Backend** is a Django REST API that powers the HW App frontend.

It provides authentication, profile management, exercise data, and workout planning features.

---

## Tech Stack

- Python
- Django
- Django REST Framework
- PostgreSQL
- JWT Authentication (SimpleJWT)
- Railway (deployment)

---

## Features

- JWT authentication
- User profile management
- Weight tracking and history
- Exercise library
- Workout templates and plans
- Django admin for seeding exercises and plans

---

## Core Models

### Profile

Stores user profile information.

Fields:

- `user`
- `height` (in inches)

---

### WeightLog

Tracks weight over time.

Fields:

- `user`
- `weight`
- `date`

---

### MuscleGroup

Defines muscle groups used by exercises.

Fields:

- `name`
- `description`

---

### Exercise

Exercise library used throughout the app.

Fields:

- `name`
- `exercise_type`
- `muscle_groups`
- `equipment`
- `instructions`
- `video_url`

---

### Workout System

Models used to generate workouts:

- `WorkoutTemplate`
- `WorkoutTemplateItem`
- `WorkoutPlan`
- `WorkoutTemplatePlan`
- `Workout`
- `WorkoutItem`

Workout plans generate dated workouts in a user's calendar.

---

## API Endpoints
```bash

/users
│
├── POST /users/register/
├── POST /users/login/
└── GET  /users/token/refresh/

/api
│
├── profiles
│   ├── GET    /api/profiles/:id/
│   └── PUT    /api/profiles/:id/
│
├── weight-logs
│   ├── GET    /api/weight-logs/
│   └── POST   /api/weight-logs/
│
├── muscle-groups
│   └── GET    /api/muscle-groups/
│
├── exercises
│   ├── GET    /api/exercises/
│   └── GET    /api/exercises/:id/
│
├── workouts
│   └── /api/workouts/
│
├── workout-items
│   └── /api/workout-items/
│
├── workout-templates
│   └── /api/workout-templates/
│
├── workout-template-items
│   └── /api/workout-template-items/
│
├── workout-plans
│   └── /api/workout-plans/
│
└── workout-template-plans
    └── /api/workout-template-plans/
```
### Authentication
Backend → identity verification

The API uses JWT authentication via `djangorestframework-simplejwt`.

### Token Generation

Users receive tokens when registering or logging in.

POST /users/register/
POST /users/login/

The server returns:

{
  refresh,
  access,
  user
}

### Authenticated Requests

Protected endpoints require a JWT access token.

Requests must include the header:

Authorization: Bearer <access_token>

### Permissions

Most API endpoints require authentication.

User-specific resources (profiles, weight logs) are filtered to the authenticated user to ensure users can only access their own data.
