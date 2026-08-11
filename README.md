# ClassPing Backend

Backend API for **ClassPing**, a school management system (CMS) built with Django and Django REST Framework.

ClassPing is designed to support school staff, teachers, students, and parents with authentication and school management functionality.

## Tech Stack

* Python 3.9+
* Django
* Django REST Framework
* PostgreSQL
* JWT Authentication
* Git

## Project Structure

```text
classping-backend/
├── apps/
│   ├── __init__.py
│   └── users/
│       ├── migrations/
│       ├── admin.py
│       ├── apps.py
│       ├── managers.py
│       ├── models.py
│       ├── permissions.py
│       ├── serializers.py
│       ├── urls.py
│       └── views.py
│
├── config/
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── .env
├── .gitignore
├── manage.py
├── requirements.txt
└── README.md
```

---

# Getting Started

Follow these steps to run ClassPing Backend locally.

## 1. Prerequisites

Make sure you have the following installed:

* Python 3.9 or higher
* PostgreSQL
* Git

Check your Python version:

```bash
python3 --version
```

Check PostgreSQL:

```bash
psql --version
```

Check Git:

```bash
git --version
```

---

# 2. Clone the Repository

Clone the repository:

```bash
git clone <REPOSITORY_URL>
```

Enter the project directory:

```bash
cd classping-backend
```

---

# 3. Create a Virtual Environment

Create a Python virtual environment:

```bash
python3 -m venv .venv
```

Activate it.

### macOS / Linux

```bash
source .venv/bin/activate
```

### Windows

```powershell
.venv\Scripts\activate
```

After activation, your terminal should show something similar to:

```text
(.venv) $
```

---

# 4. Install Dependencies

Make sure the virtual environment is activated.

Then install the project dependencies:

```bash
pip install -r requirements.txt
```

If you are setting up the project for the first time and `requirements.txt` does not exist yet:

```bash
pip install django
pip install djangorestframework
pip install djangorestframework-simplejwt
pip install psycopg2-binary
```

Then save the dependencies:

```bash
pip freeze > requirements.txt
```

---

# 5. PostgreSQL Setup

ClassPing currently uses PostgreSQL as its database.

Create a PostgreSQL database:

```sql
CREATE DATABASE classping;
```

Create a database user if needed:

```sql
CREATE USER classping WITH PASSWORD 'your-password';
```

Grant access:

```sql
GRANT ALL PRIVILEGES ON DATABASE classping TO classping;
```

You can also use an existing PostgreSQL user if your local setup already has one.

---

# 6. Environment Variables

Create a `.env` file in the project root:

```text
classping-backend/
├── .env
├── manage.py
└── ...
```

Example:

```env
DJANGO_DEBUG=True
DJANGO_SECRET_KEY=change-this-in-development

POSTGRES_DB=classping
POSTGRES_USER=classping
POSTGRES_PASSWORD=your-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### Important

Never commit `.env` to Git.

The `.env` file should be included in `.gitignore`.

Example:

```gitignore
.env
.venv/
__pycache__/
*.pyc
db.sqlite3
.idea/
.vscode/
.DS_Store
```

---

# 7. Database Configuration

Django should read the PostgreSQL configuration from environment variables.

Example `config/settings.py`:

```python
import os

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB"),
        "USER": os.getenv("POSTGRES_USER"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}
```

---

# 8. Custom User Model

ClassPing uses a custom User model.

The User model supports:

```text
ADMIN
STAFF
TEACHER
STUDENT
PARENT
```

The application uses email instead of username for authentication.

In `config/settings.py`:

```python
AUTH_USER_MODEL = "users.User"
```

The user app is located at:

```text
apps/users/
```

and registered as:

```python
INSTALLED_APPS = [
    # Django apps...

    "rest_framework",
    "rest_framework_simplejwt",

    "apps.users",
]
```

---

# 9. Run Database Migrations

Before starting the server, run:

```bash
python manage.py migrate
```

If you make changes to models:

```bash
python manage.py makemigrations
python manage.py migrate
```

---

# 10. Create a Superuser

Create an admin account:

```bash
python manage.py createsuperuser
```

You will be asked for:

```text
Email:
Password:
Password (again):
```

Because ClassPing uses email authentication, there is no username requirement.

---

# 11. Start the Development Server

Run:

```bash
python manage.py runserver
```

The API will be available at:

```text
http://127.0.0.1:8000/
```

Django Admin:

```text
http://127.0.0.1:8000/admin/
```

---

# Authentication

ClassPing uses JWT authentication.

## Login

Endpoint:

```http
POST /api/auth/login/
```

Request:

```json
{
    "email": "admin@classping.com",
    "password": "your-password"
}
```

Response:

```json
{
    "refresh": "your-refresh-token",
    "access": "your-access-token"
}
```

Use the `access` token when calling protected APIs:

```http
Authorization: Bearer <access-token>
```

---

# User API

## List Users

```http
GET /api/users/
```

Requires authentication.

Example:

```bash
curl http://127.0.0.1:8000/api/users/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## Create User

```http
POST /api/users/
```

Example:

```json
{
    "email": "teacher@classping.com",
    "password": "teacher123",
    "first_name": "John",
    "last_name": "Teacher",
    "role": "TEACHER"
}
```

## Get User

```http
GET /api/users/{id}/
```

## Update User

```http
PATCH /api/users/{id}/
```

Example:

```json
{
    "first_name": "Jane",
    "role": "TEACHER"
}
```

## Delete User

```http
DELETE /api/users/{id}/
```

User deletion is currently implemented as a soft delete by setting:

```text
is_active = false
```

This helps preserve historical school data.

---

# Common Development Commands

## Start the server

```bash
python manage.py runserver
```

## Create migrations

```bash
python manage.py makemigrations
```

## Apply migrations

```bash
python manage.py migrate
```

## Create superuser

```bash
python manage.py createsuperuser
```

## Django shell

```bash
python manage.py shell
```

## Run tests

```bash
python manage.py test
```

## Check the project

```bash
python manage.py check
```

---

# Typical Workflow for Contributors

After pulling the latest changes:

```bash
git pull
```

Activate your virtual environment:

```bash
source .venv/bin/activate
```

Install any new dependencies:

```bash
pip install -r requirements.txt
```

Apply database migrations:

```bash
python manage.py migrate
```

Run the server:

```bash
python manage.py runserver
```

---

# Creating a New Django App

Django apps are stored inside the `apps/` directory.

Example:

```bash
python manage.py startapp students apps/students
```

After creating an app, update `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...

    "apps.students",
]
```

Also make sure the app configuration uses the correct Python path.

Example `apps/students/apps.py`:

```python
from django.apps import AppConfig


class StudentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.students"
```

---

# Git Workflow

Create a feature branch before making changes:

```bash
git checkout -b feature/user-authentication
```

After making changes:

```bash
git status
git add .
git commit -m "feat: add user authentication"
```

Push the branch:

```bash
git push origin feature/user-authentication
```

Avoid committing:

```text
.env
.venv/
__pycache__/
*.pyc
```

---

# Environment Requirements

Each developer should have their own local `.env`.

Example:

```env
DJANGO_DEBUG=True
DJANGO_SECRET_KEY=local-development-secret

POSTGRES_DB=classping
POSTGRES_USER=classping
POSTGRES_PASSWORD=your-local-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Do not share production credentials through Git.

---

# Troubleshooting

## `ModuleNotFoundError`

Example:

```text
ModuleNotFoundError: No module named 'django'
```

Make sure the virtual environment is active:

```bash
source .venv/bin/activate
```

Then:

```bash
pip install -r requirements.txt
```

---

## PostgreSQL driver error

Example:

```text
Error loading psycopg2 or psycopg module
```

Install:

```bash
pip install psycopg2-binary
```

Then:

```bash
pip freeze > requirements.txt
```

---

## Database connection error

Check that PostgreSQL is running:

```bash
pg_isready
```

Check your `.env`:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=classping
POSTGRES_USER=classping
POSTGRES_PASSWORD=your-password
```

---

## Authentication error

If the API returns:

```json
{
    "detail": "Authentication credentials were not provided."
}
```

you need to send a JWT access token:

```http
Authorization: Bearer YOUR_ACCESS_TOKEN
```

First authenticate through:

```http
POST /api/auth/login/
```

---

# Development Notes

ClassPing is currently in active development.

Current functionality:

* Custom User model
* Email-based authentication
* JWT authentication
* User CRUD
* User roles
* PostgreSQL
* Django REST Framework

Planned functionality:

* Student profiles
* Teacher profiles
* Parent profiles
* Schools
* Classes
* Attendance
* Assignments
* Announcements
* Notifications
* Role-based permissions
* School-specific data isolation

---

# Local Development Quick Start

For an experienced contributor, the complete setup is:

```bash
git clone <REPOSITORY_URL>
cd classping-backend

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# Create and configure .env

python manage.py migrate
python manage.py createsuperuser

python manage.py runserver
```

Then open:

```text
http://127.0.0.1:8000/
```

Admin:

```text
http://127.0.0.1:8000/admin/
```

API:

```text
http://127.0.0.1:8000/api/
```
