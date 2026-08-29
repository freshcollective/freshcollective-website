# Fresh Collective

Membership-based transformation platform for women.

## Architecture

```
fc-production/
├── frontend/   Next.js 16, TypeScript, Tailwind CSS  (yarn)
├── backend/    FastAPI, SQLAlchemy, PostgreSQL        (Python 3.12+)
├── prisma/     Reference schema (initial DB setup — superseded by Alembic)
└── docs/       Product brief, design principles, roadmap
```

**Local URLs**

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |

---

## Quick start

### Prerequisites

- PostgreSQL running locally with database `fc_prod`
- Python 3.12+ with pip
- Node.js 20+ with yarn

```bash
pg_isready -h localhost -p 5432
psql -U lindsey -d fc_prod -c "SELECT current_database();"
python3 --version
yarn --version
```

---

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then edit with real values
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**backend/.env**
```
DATABASE_URL=postgresql://lindsey:YOUR_PASSWORD@localhost:5432/fc_prod
JWT_SECRET=your-secure-random-secret-at-least-32-chars
FRONTEND_ORIGIN=http://localhost:3000
APP_ENV=development
```

Generate a secret: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`

---

### Frontend

```bash
cd frontend
yarn install
cp .env.example .env      # then edit with real values
yarn dev
```

**frontend/.env**
```
NEXT_PUBLIC_API_URL=http://localhost:8000
API_INTERNAL_URL=http://localhost:8000
```

> **Authentication transport (SEC-002).** Browsers talk to Next.js
> same-origin (`/api/*`); Next.js proxies to FastAPI server-to-server.
> That's why the frontend needs two backend URLs:
>
> - `API_INTERNAL_URL` — server-side proxy target (never sent to the browser).
> - `NEXT_PUBLIC_API_URL` — public host used only for `<img src>` on
>   uploaded media; application API calls do NOT use it.
>
> The frontend does **not** hold the JWT signing key. The backend's
> `JWT_SECRET` is the sole authority; Next.js middleware performs a
> cookie-presence routing check only, and the authoritative session
> check is `/api/auth/me` on the backend.

---

## API routes

### `/api/auth/` — public (rate limited)

| Method | Path | Auth required |
|--------|------|---------------|
| POST | `/api/auth/login` | No |
| POST | `/api/auth/signup` | No |
| POST | `/api/auth/logout` | No |
| GET | `/api/auth/me` | Yes (any user) |
| POST | `/api/auth/forgot-password` | No |
| POST | `/api/auth/reset-password` | No |

### `/api/client/` — authenticated members

| Method | Path |
|--------|------|
| GET | `/api/client/profile` |
| GET | `/api/client/real-journey` |
| GET | `/api/client/rooms` |
| GET | `/api/client/heart` |

### `/api/admin/` — admin role only

| Method | Path |
|--------|------|
| GET | `/api/admin/users` |
| PATCH | `/api/admin/users/{id}/role` |
| GET | `/api/admin/stats` |

---

## User management

### Create a test user
```bash
# Via the UI
open http://localhost:3000/signup

# Or via the API
curl -X POST http://localhost:8000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"name":"Test User","email":"test@example.com","password":"testpass123"}'
```

### Promote a user to admin
```bash
psql -U lindsey -d fc_prod \
  -c "UPDATE users SET role = 'admin' WHERE email = 'your@email.com';"
```

---

## Password reset (development)

1. Go to `/forgot-password`, enter an email
2. The reset URL is printed to the **uvicorn terminal**
3. Open that URL in a browser
4. Set a new password

Wire up a real email service in `backend/app/auth/routes.py` at the `# TODO` comment before going to production.

---

## Testing checklist

```
[ ] Homepage loads without login (Login + Join in header)
[ ] /dashboard redirects to /login when logged out
[ ] Signup creates user and sets session cookie
[ ] Login sets session cookie, redirects to /dashboard
[ ] /api/auth/me returns user when authenticated
[ ] Logout clears cookie, redirects to /
[ ] /api/client/profile → 401 when not logged in
[ ] /api/admin/users → 401 when not logged in
[ ] /api/admin/users → 403 when logged in as normal user
[ ] /api/admin/users → 200 when logged in as admin
[ ] Password reset URL appears in uvicorn console
[ ] Password reset link sets a new session
```

---

## Database migrations

```bash
cd backend && source .venv/bin/activate

# Apply all pending migrations
alembic upgrade head

# Create a new migration
alembic revision -m "describe your change"
# edit the generated file, then:
alembic upgrade head

# Roll back one migration
alembic downgrade -1
```

---

## Production deployment

| Item | Action required |
|------|----------------|
| Database | Update `DATABASE_URL` to point to managed PostgreSQL |
| `JWT_SECRET` | Generate a new secret — never reuse dev secrets. Set on backend only; the frontend never receives it. |
| `API_INTERNAL_URL` (frontend) | Auto-wired on Render from fc-api's `RENDER_EXTERNAL_URL`; server-side only. |
| `NEXT_PUBLIC_API_URL` (frontend) | Public backend host; used by the browser for `<img src>` on uploaded media only. |
| `FRONTEND_ORIGIN` | Set to your production domain |
| `APP_ENV` | Set to `production` to enable Secure cookies (requires HTTPS) |
| Email | Implement email sending in `backend/app/auth/routes.py` |
| Rate limiting | Replace in-memory slowapi with Redis-backed limiter |
| Backend | Deploy with uvicorn behind nginx/Caddy |
| Frontend | `yarn build` then deploy to Vercel/Fly.io/etc. |
