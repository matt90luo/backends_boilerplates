# tinysaas — a tiny SaaS backend boilerplate

A production-shaped starting point for a **tool-as-a-service / micro-tool gateway** SaaS:
users register, buy credits, call services through one virtual endpoint, and every call is
logged and billed.

It is deliberately small, but the seams are the ones you would otherwise add later:
RBAC, transactional email, rate limiting, presigned uploads, a uniform response envelope,
health probes and error reporting are all in place behind ports you can swap.

```
                 +-----------------------------------------------+
                 |  Client (web dashboard / SDK / curl)          |
                 +----------------------+------------------------+
                                        |  POST /api/v1/services/{slug}/execute
                                        v
+----------------------------------------------------------------------------+
|  FastAPI inbound adapter                                                   |
|  middleware: request id -> auth context -> rate limit -> routes            |
|  routes:     @inject + Depends(Provide[Container.<use_case>])              |
+------------------------------------+---------------------------------------+
                                     v
+----------------------------------------------------------------------------+
|  Application: use cases + ports (no framework, no SQL)                     |
|  ExecuteServiceUseCase   ReserveTopUpUseCase   ...                         |
+------+----------------------------------------------+----------------------+
       v                                              v
+-------------------------+              +---------------------------------+
|  Domain                 |              |  Outbound adapters              |
|  User / Wallet /        |              |  SQLAlchemy, Redis, S3, Stripe, |
|  Service / Invocation   |              |  Resend, arq, structlog         |
|  + domain services      |              +----------------+----------------+
+-------------------------+                               v
                                          +---------------------------------+
                                          |  Infrastructure (drivers, pools)|
                                          +---------------------------------+
```

## Demo flow

```
register -> admin grants credits (or Stripe Checkout) -> call a service
        -> credits are reserved, then settled (success) or refunded (failure)
        -> the call shows up in your usage logs (admins see everyone's)
```

## Architecture

Dependency direction is strictly **inward** — nothing in `domain` knows about FastAPI,
SQLAlchemy, Redis or Stripe.

| Layer | Package | Depends on | Contains |
| --- | --- | --- | --- |
| Domain | `src/tinysaas/domain` | nothing | entities, value objects, invariants, domain services (`CreditReservationService`, `AccessPolicy`) |
| Application | `src/tinysaas/application` | domain | ports (interfaces), use cases, DTOs/commands, application errors, plain config objects |
| Inbound adapters | `src/tinysaas/adapters/web` | application | routers, Pydantic schemas, middleware, exception handlers |
| Outbound adapters | `src/tinysaas/adapters/{persistence,security,ratelimit,mail,storage,executors,queue,payments,observability}` | application + domain | SQLAlchemy repositories, Argon2/JWT/API keys, Redis limiter, mailers, presigned storage, service executors, arq queue, Stripe gateway |
| Infrastructure | `src/tinysaas/infrastructure` | — | settings, engine/session factory, Redis/S3/HTTP clients, structlog, `Resources` lifecycle |
| Composition root | `src/tinysaas/containers` | everything | the **only** module that knows every concrete implementation |

### Composition root

`containers/container.py` wires implementations into use cases and hands the use cases to
the routes through `dependency_injector`:

```python
# containers/container.py
class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(modules=ROUTER_MODULES, auto_wire=True)

    settings = providers.Singleton(get_settings)
    resources = providers.Singleton(Resources, settings=settings)      # drivers only
    uow_factory = providers.Singleton(SqlAlchemyUnitOfWorkFactory, session_factory=...)

    execute_service_use_case = providers.Factory(
        ExecuteServiceUseCase,
        uow_factory=uow_factory,
        credits=credit_reservations,
        executor=executor,          # in-process demo handler or HTTP reverse proxy
        settlement=settlement,
        clock=clock,
        logger=logger,
    )
```

```python
# adapters/web/routers/services.py
@router.post("/services/{slug}/execute")
@inject
async def execute_service(
    slug: str,
    request: Request,
    use_case: ExecuteServiceUseCase = Depends(Provide[Container.execute_service_use_case]),
) -> Response: ...
```

Swapping infrastructure is a one-line change in the container: point `storage` at
`InMemoryObjectStorage` instead of S3, `mailer` at the console mailer instead of Resend, or
override a whole use case in a test (`container.uow_factory.override(providers.Object(...))`).

## Quickstart

Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/), PostgreSQL, Redis and an
S3-compatible store (the defaults match the local RustFS/MinIO setup used by this repo).
`make up` starts all three with docker compose if you prefer.

```bash
cp .env.example .env          # then set JWT_SECRET_KEY (+ Stripe/Resend if you use them)
make install                  # uv sync
make migrate                  # alembic upgrade head
make seed                     # admin user, 3 credit packages, 3 demo services
make dev                      # http://127.0.0.1:8000/docs
make worker                   # in a second terminal: async tasks
make smoke                    # end-to-end check against the running API
```

Seeded data: admin `ADMIN_EMAIL`/`ADMIN_PASSWORD` (default `admin@tinysaas.local` /
`admin12345`) with 10 000 credits, packages `starter`/`pro`/`scale`, and the demo services
`echo` (sync, 1 credit), `slow-report` (async, 3 credits) and `always-fails` (used to
demonstrate refunds).

## API

Everything lives under `API_PREFIX` (`/api/v1`) except the probes.

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/sessions`, `DELETE /auth/sessions/{id}`, `POST /auth/verify-email`, `POST /auth/password-reset/request`, `POST /auth/password-reset/confirm` |
| Profile & keys | `GET|PATCH /users/me`, `POST /users/me/password`, `GET|POST /api-keys`, `DELETE /api-keys/{id}` |
| Billing | `GET /billing/packages`, `POST /billing/checkout` (`Idempotency-Key` required), `GET /billing/wallet`, `GET /billing/ledger`, `GET /billing/topups/{id}` |
| Webhook | `POST /webhooks/stripe` (signature verified) |
| Services | `GET /services`, `GET /services/{slug}`, `POST /services/{slug}/execute`, `POST /services/{slug}/tasks`, `GET /tasks/{id}` |
| Logs | `GET /me/invocations`, `GET /me/invocations/{id}` |
| Admin | `POST|GET /admin/services`, `PATCH|DELETE /admin/services/{id}`, `GET /admin/users`, `GET|PATCH /admin/users/{id}`, `POST /admin/users/{id}/credits`, `GET /admin/invocations`, `GET /admin/users/{id}/invocations` |
| Files | `POST /files/presign`, `POST /files/presign/download` |
| Probes | `GET /healthz` (liveness), `GET /readyz` (Postgres + Redis + storage) |

### Response envelope

```json
{ "success": true,  "data": { }, "meta": { "request_id": "..." } }
{ "success": false, "code": "INSUFFICIENT_CREDITS", "message": "credit 余额不足",
  "details": { "required": 5, "balance": 2 }, "request_id": "..." }
```

`X-Request-ID` is echoed on every response (and generated when absent). Two endpoints are
intentionally not wrapped: `POST /services/{slug}/execute` returns the **upstream body**
(a tool may return an image; billing metadata is in `X-Invocation-Id` /
`X-Credits-Charged` / `X-Replayed`) and the provider webhook.

Error codes map to statuses in `adapters/web/errors.py`, e.g. `VALIDATION_ERROR` 422,
`AUTH_*` 401, `FORBIDDEN` 403, `USER_NOT_FOUND`/`SERVICE_NOT_FOUND` 404,
`INSUFFICIENT_CREDITS` 402, `QUOTA_EXCEEDED`/`RATE_LIMITED` 429, `UPSTREAM_FAILED` 502,
`UPSTREAM_TIMEOUT` 504.

### Authentication

* **JWT access token** (short lived) in `Authorization: Bearer <token>`.
* **Refresh token**: opaque, only its HMAC digest is stored, rotated on every refresh,
  grouped in a family — replaying a rotated token revokes the whole family
  (`AUTH_REFRESH_REUSED`). Returned in the response body by default, or as an httpOnly
  cookie with `REFRESH_TRANSPORT=cookie`.
* **API keys** (`X-API-Key: tsk_<lookup>_<secret>`): hashed at rest, listable/revocable,
  authenticated by a single indexed lookup + constant-time digest comparison.

Middleware order (outermost first): `RequestContextMiddleware` → CORS →
`AuthContextMiddleware` (resolves the principal into `request.state`) →
`RateLimitMiddleware` → routes. Authentication never rejects a request; the route
dependencies (`require_user` / `require_admin`) do. All dependencies are `async` on purpose
so no request ever touches the threadpool.

## How credits work

`invocations` (the usage log) and `credit_ledger` (append-only money trail) are the two
tables behind billing. One call is a two-phase, compensating transaction:

1. **Reserve** — in a short transaction: `SELECT ... FOR UPDATE` on the wallet, then
   `balance -= cost`, `reserved += cost`, insert a `reserve` ledger row and a `pending`
   invocation. Not enough credits → `402` and no side effects.
2. **Dispatch** — no transaction is held while talking to the tool (sync: HTTP proxy or
   in-process handler; async: enqueue on Redis with the invocation id as the job id).
3. **Settle** — on a 2xx: `reserved -= cost`, `settle` ledger row, `succeeded`.
4. **Refund** — on anything else (4xx/5xx/timeout/exception): `balance += cost`,
   `reserved -= cost`, `refund` ledger row, status `refunded`; the caller gets 502/504.
   `failed` (no refund applied) always needs operator attention — that is why both states
   exist.

Idempotency: send `Idempotency-Key` on `execute`/`tasks` (and it is required on
`billing/checkout`). A repeat returns the recorded outcome (`X-Replayed: true`) without
charging again.

Quota and rate limits: `users.daily_quota` (free 20 / pro 1000, admin adjustable) caps
calls per user per UTC day; the middleware adds IP based windows for `/auth/login` (5/min),
`/auth/register` (10/h), `/auth/password-reset/request` (3/15min) and a per-user window for
service invocations (`RATE_LIMIT_SERVICE_PER_MINUTE`).

## Adding a new service

No new route, no gateway restart:

1. Deploy the worker and expose it over HTTP, e.g. `POST http://bg-worker:8080/predict`.
2. Register it:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/admin/services \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"slug":"bg-remove","name":"Background remover","credit_cost":5,
       "exec_mode":"sync","upstream_url":"http://bg-worker:8080/predict","timeout_secs":30}'
```

Clients can immediately call `POST /api/v1/services/bg-remove/execute`. Use
`"exec_mode":"async"` for long jobs and `upstream_url` absent for the built-in in-process
demo handlers (`adapters/executors/inprocess.py`). The executor is selected per service in
`CompositeServiceExecutor`, so adding a third dispatch strategy is a new adapter plus one
container line.

## Adding a feature (the DDD recipe)

1. **Domain** — put the rule where it belongs (`domain/<context>/…`). Cross-aggregate rules
   become a domain service (see `CreditReservationService`).
2. **Ports** — if the use case needs I/O, add a `Protocol` in `application/ports/` and an
   in-memory double in `tests/fakes/`.
3. **Use case** — one class per use case in `application/use_cases/`, taking ports in
   `__init__`, returning an application DTO. No SQL, no HTTP, no SDK types.
4. **Adapter** — implement the port (`adapters/…`); keep third-party payloads inside the
   adapter and translate them into your own dataclasses.
5. **Web** — add the Pydantic request/response models, the route with
   `@inject` + `Depends(Provide[Container.<use_case>])`, and register the use case in
   `containers/container.py`.
6. **Migration + tests** — `alembic revision --autogenerate -m "..."`, then unit tests with
   the in-memory doubles and an API test through `httpx.ASGITransport`.

## Testing

```bash
make test               # unit + application + API tests, all against in-memory doubles
make test-integration   # real PostgreSQL / Redis / RustFS (opt-in, marked `integration`)
```

* `tests/domain` — invariants: wallet never negative, slug rules, invocation state machine,
  RBAC matrix.
* `tests/application` — use cases through the container with in-memory repositories, a fake
  clock, a stub executor and a fake payment gateway (reserve/settle/refund, idempotency,
  webhook replay, admin adjustments).
* `tests/adapters` — the HTTP contract: envelope and error codes, refresh rotation/reuse
  detection, rate limiting, RBAC visibility of logs, presigned uploads, Stripe adapter
  (price validation, signed webhooks) and the email templates rendered with `StrictUndefined`.
* `tests/integration` — `SELECT ... FOR UPDATE` on a real database, the Redis Lua sliding
  window and a real presigned PUT/GET round trip.

Tests run inside the locked environment: `uv run pytest` (or `make test`). The API tests use
`httpx.ASGITransport`, so no server and no network are required.

## Operations

* `Dockerfile` builds a uv-based image; the default command runs the API with
  `uvicorn tinysaas.adapters.web.app:create_app --factory`. Run the worker with
  `arq tinysaas.worker.WorkerSettings` (same image, different command).
* `docker-compose.dev.yml` provides PostgreSQL, Redis and RustFS for local development.
* `/healthz` is liveness only; `/readyz` pings Postgres, Redis and the bucket and returns
  `503` with a component report when something is down — use it for container probes and
  load-balancer health checks.
* Structured logs are JSON outside `local`/`test` (structlog) and carry `request_id`,
  `user_id`, `service_slug`, status and latency.
* Set `SENTRY_DSN` to report unhandled exceptions (disabled when empty). Every error
  response carries the same `request_id` you will find in Sentry/logs.
* Migrations: `uv run alembic revision --autogenerate -m "message"` then
  `uv run alembic upgrade head`. `alembic check` verifies the models and migrations agree.

## Deliberate v1 boundaries

* **Single-tenant accounts with global roles** (`user`/`admin`). The multi-tenancy seam is
  already there: every repository call is scoped by a `Principal` that carries `org_id`
  (always `None` today) — add `organizations`/`memberships` when you need workspaces.
* **Credits, not subscriptions**: Stripe is used for one-time credit purchases through
  hosted Checkout with pre-configured Prices. Recurring billing is intentionally out.
* **No frontend**: Swagger UI (`/docs`) is the interim dashboard; the JSON contract, the
  envelope and the ready-made `X-Request-ID` are what the real dashboard needs.
* **Email verification does not block login** by default (`REQUIRE_EMAIL_VERIFICATION`);
  the token and the email are already wired for when it should.
* **Celery/Kafka are out of scope**: arq on the Redis you already run covers the async
  task pipeline with far less operational weight.
