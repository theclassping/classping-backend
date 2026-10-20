# ClassPing production setup

This is a separate Compose project named `classping-backend-production`.
Development keeps port 8000; production uses loopback port 8001. Database and
Redis have separate project volumes and no published ports. No development data
is copied. The `release` container exits after migrations; that is expected.

## 1. Prepare configuration

Open PowerShell in `D:\RANIA\classping-backend` and start Docker Desktop.

```powershell
Copy-Item .env.production.example .env.production
```

Do not overwrite an existing production environment file. Edit `.env.production`:

| Variable | Required value |
| --- | --- |
| `DJANGO_SECRET_KEY` | Random secret of at least 50 characters; retain across releases |
| `POSTGRES_PASSWORD` | Random URL-safe password; hexadecimal is suitable |
| `R2_*` | Credentials and bucket dedicated to production media |
| `MAILJET_API_KEY`, `MAILJET_API_SECRET` | Mailjet API credentials |
| `MAIL_FROM_EMAIL` | Verified Mailjet sender |
| `PASSWORD_RESET_URL`, `SCHOOL_PASSWORD_RESET_URL` | Actual frontend reset routes |
| `DJANGO_ALLOWED_HOSTS` | Backend hostnames, without scheme or path |
| `SITE_URL` | Backend URL |
| `CORS_ALLOWED_ORIGINS` | Frontend origins, with scheme and port where needed |
| `CSRF_TRUSTED_ORIGINS` | Trusted origins used for browser form submissions |

Generate each secret separately using Docker, for example:

```powershell
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_hex(32))"
```

Use a private R2 bucket and configure its CORS to allow the actual frontend origins
and upload/download methods and headers. Existing Mailjet template IDs are inherited
from the application settings; verify those templates exist in the selected account.
Real environment files are excluded from Git and Docker builds.

## 2. Build and start

Always use this production file alone, not merged with the development Compose file.

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps -a
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail 100 web scheduler release
```

Open `http://localhost:8001/admin-web/`. A new database starts without accounts.
Create the first administrator interactively:

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

Verify the account's role and application permissions before use. Do not run demo
seeds against production. Keep exactly one scheduler instance.
The web healthcheck verifies a listening port; it is not a full application or
dependency readiness check.

## 3. Public HTTPS deployment

The initial example is for testing the production configuration on this computer.
It is bound to localhost and is not publicly hosted. For a real deployment, run
this stack on an always-on server and place an HTTPS reverse proxy in front of
`127.0.0.1:8001`. A host-installed proxy can access that port; a containerized
proxy must instead join the Compose network and connect to `web:8000`.

Set real backend/frontend domains in the URL and origin variables. Set
`HTTPS_ENABLED=True`; set `TRUST_PROXY_HEADERS=True` only when the trusted proxy
overwrites `X-Forwarded-Proto` and direct access to the backend is restricted.
Recreate services after configuration changes. Then run:

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml exec web python manage.py check --deploy
```

Review remaining warnings, including HSTS policy, before exposing real user data.
This configuration does not resolve application-level access isolation or the
unsigned local upload endpoint. Those remain go-live blockers from the audit.
Verify login, password reset email, role/data isolation, private media, invoices,
payments, and scheduled reminders in staging.

## 4. Update and stop

Back up the database before updates. Stop application processes before migrations
to avoid running old code against a changing schema:

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml stop web scheduler
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm release
```

Only if migrations succeed:

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate web scheduler
```

If migration fails, inspect logs and recover before restarting application services.
Changing `POSTGRES_PASSWORD` after initialization does not change the existing
database user's password; rotate it in PostgreSQL as a separate operation.

To stop the stack while preserving database and Redis volumes:

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

Do not add `-v`: that removes production data volumes. Arrange automatic backups
and test restoration before go-live. Running this stack on a laptop still requires
the laptop and Docker Desktop to stay running.
