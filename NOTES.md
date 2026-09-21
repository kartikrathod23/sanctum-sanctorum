# Sanctum Sanctorum — Implementation Notes

## Live URL

https://sanctum-sanctorum-dlho.onrender.com

The application is deployed as a public Render web service. The frontend and API are served
from the same application, so no separate frontend URL is required.

The database is seeded automatically when the production database is empty. The Members page
can be used to create a new member and sign in, so no special credentials are required.

---

## What I completed

I completed the required bookstore functionality across books, members, orders, loans, and reports.

### Books

- Added ISBN-13 normalization and checksum validation.
- Added validation for book title, author, price, and stock.
- Added duplicate ISBN handling.
- Implemented book lookup.
- Implemented search by title or author.
- Implemented restricted-book filtering.
- Implemented price range filtering.
- Implemented sorting and pagination.
- Implemented book updates using PATCH.
- Preserved the required behaviour for ignored fields such as `isbn` and unknown fields.

### Members

- Added member validation and email normalization.
- Added case-insensitive duplicate email handling.
- Implemented member lookup.
- Implemented member order listing.
- Implemented member statistics.
- Implemented tier-based behaviour used by orders and loans.
- Added pagination support for `GET /members`.

### Orders

- Implemented order creation and validation.
- Added member and book existence checks.
- Added restricted-book access rules.
- Added stock validation with all-or-nothing behaviour.
- Implemented tier-based discounts.
- Implemented the bulk quantity discount.
- Implemented discount calculation and integer-cent pricing.
- Stored the book price at the time an order is created.
- Implemented payment.
- Implemented cancellation and stock restoration.
- Preserved the submitted order item order.
- Added concurrency protection when multiple orders try to purchase the last available copy of a book.
- A failed order does not partially reserve stock.

### Loans

- Completed the loan model and lifecycle.
- Implemented borrowing and returning books.
- Added the 14-day loan period.
- Added tier-based concurrent loan limits.
- Added restricted-book access rules.
- Prevented borrowing when a member has an overdue loan.
- Prevented duplicate active loans for the same book.
- Added stock decrement on borrowing and restoration on return.
- Implemented overdue status.
- Implemented late fees based on started days of lateness.
- Applied the late-fee cap using the book price at the time of return.
- Implemented loan status filtering.

### Reports

- Implemented the top-books report.
- Reports count copies from paid orders only.
- Report titles use the book's current title.

### Additional test coverage

I added separate edge-case tests for cases that are easy to get wrong, including:

- Unknown PATCH fields.
- Orders failing because a book does not exist without changing stock.
- Restricted multi-item orders not partially reserving stock.
- Discount limits for large orders.
- Late fees using the current book price when a book is returned.
- Overdue loans that have not yet been returned having no recorded late fee.
- Reports using the current book title.
- Concurrent orders competing for the last available copy of a book.

The existing acceptance tests were kept intact; the additional cases were added separately.

---

## Architecture and design decisions

The existing project already separated the application into routers, services, models,
schemas, and database code, so I kept that structure rather than moving the application
towards a different architecture.

### Thin routers and service layer

The routers are responsible mainly for HTTP concerns such as parsing requests, dependencies,
and returning responses.

The main business rules live in `app/services/`.

For example, order creation, discount calculation, stock reservation, loan rules, and late
fees are handled by services rather than being implemented directly inside the FastAPI routes.

This keeps the business logic easier to test and avoids putting large amounts of logic into
the HTTP layer.

### SQLAlchemy models

The existing SQLAlchemy model structure was retained and extended where required, especially
for the loan lifecycle.

Relationships between members, orders, order items, books, and loans are represented using
SQLAlchemy relationships rather than duplicating lookup logic across the application.

### Current time

All business logic that depends on the current time uses the existing `get_now` dependency.

I did not use direct `datetime.now()` calls for business rules, so the application's time-based
behaviour remains compatible with the frozen clock used by the test suite.

### Local SQLite and production PostgreSQL

The application continues to use SQLite by default for local development and tests.

For production, I added PostgreSQL support through `SANCTUM_DATABASE_URL` and deployed the
database using Supabase PostgreSQL.

This gives the deployed application persistent storage while keeping the local test suite
independent of any external database.

This was also important because the assignment explicitly requires the tests to work locally
without external services.

### Deployment architecture

I deployed the FastAPI application and the existing static frontend together as one Render
web service.

The frontend already uses relative API paths such as `/books`, `/members`, and `/orders`,
so serving both from the same origin avoids the need for a separate frontend deployment and
additional API URL configuration.

Render is responsible for running the FastAPI application, while Supabase provides the
production PostgreSQL database.

The production service uses:

- Build command: `uv sync --no-dev`
- Start command: `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check: `/health`

### Database initialization

The application creates the required tables on startup and seeds the demo data when the
database is empty.

For this assignment, I kept this approach instead of introducing a migration framework.

For a larger production application with an evolving schema, I would use explicit database
migrations such as Alembic.

---

## Trade-offs

### One Render service instead of separate frontend and backend deployments

The frontend is already a static frontend served by FastAPI and uses relative API URLs.

Keeping them together made the deployment simpler and avoided unnecessary cross-origin
configuration.

A separate frontend deployment could make sense for a larger application, but it would not
provide much benefit for this project.

### PostgreSQL in production, SQLite locally

Using PostgreSQL in production gives the application persistent hosted storage.

Keeping SQLite as the local default means the test suite remains fast and can be run without
network access or external services, which is also required by the assignment.

### Startup table creation instead of migrations

`Base.metadata.create_all()` is sufficient for this assignment and keeps the setup simple.

For a real production system with schema changes over time, migrations would be a better
choice.

### Transaction and stock handling

Order creation validates all books, permissions, and stock before making stock changes.

This prevents a failed multi-book order from leaving some books reserved and others unchanged.

For concurrent orders, stock reservation uses an atomic database update that only succeeds
when enough stock is still available. This prevents two simultaneous orders from consuming
the same last copy.

The implementation focuses on the behaviour required by the assignment without introducing
a larger inventory or distributed locking system.

---

## What I did not implement

All required features from the specification were implemented.

I also completed all three optional extras from the assignment:

- Added additional edge-case tests.
- Added concurrency protection for two simultaneous orders trying to purchase the last copy
  of a book.
- Added pagination support for `GET /members`.

There are no required or optional assignment features remaining incomplete.

---

## Ambiguities and assumptions

The specification was generally clear, so I did not need to change any acceptance tests or
make major assumptions.

One detail explicitly called out by the specification is mixed-case title ordering. The
behaviour of mixed-case sorting can differ between databases, and the specification states
that either behaviour is acceptable. I therefore kept the database's normal ordering rather
than adding custom case-folding logic.

For production, the application uses the same API and data model defined by the specification
while changing only the database backend from the default SQLite database to PostgreSQL.

---

## Verification

The application was tested locally using the project's `uv` workflow.

The test suite includes the original acceptance tests along with additional edge-case and
concurrency coverage. All tests pass successfully.

The deployed application was also tested manually through the public Render URL, including:

- Health/API availability.
- Catalog loading.
- Book search, filtering, sorting, and pagination.
- Member creation and sign-in.
- Member pagination.
- Order creation.
- Stock reduction after ordering.
- Concurrent orders competing for the last available copy.
- Order payment.
- Order cancellation and stock restoration.
- Persistence after refreshing the application.
- Borrowing and returning books.
- Restricted-book access rules.
- Reports.

The deployed application uses Supabase PostgreSQL, so the manual checks also verified that
changes persist after refreshing the application.

---

## AI usage

I used AI tools during the assignment as a development aid rather than as a replacement for
understanding the implementation.

I used them mainly for:

- Understanding the existing codebase and specification.
- Thinking through the business rules before implementing them.
- Debugging failing tests.
- Reviewing edge cases around orders, stock, loans, and late fees.
- Suggesting additional test cases.
- Debugging the PostgreSQL and Render deployment setup.
- Reviewing the final architecture and deployment choices.

I reviewed and tested the generated suggestions before keeping them in the project.

One example where I had to verify and override an AI suggestion was during the PostgreSQL
deployment. An initially used Supabase pooler hostname did not match the actual connection
details for the project and caused the deployed service to fail to connect to PostgreSQL.

I checked the connection details provided by Supabase and replaced it with the actual Session
Pooler hostname before continuing.

The final implementation and deployment configuration were tested locally and on the deployed
application rather than being accepted solely based on AI-generated suggestions.