# Django rebuild project guidance

This folder is a side-by-side Django rebuild of the clothing store in `/Users/kushalkadel/Desktop/Jersey-main`.

Before making changes, read `PROJECT_CONTEXT.md`, `REQUIREMENTS.md`, and `README.md`. Use the original Next.js project as a read-only feature and design reference. The user's goal is to complete and compare the Django version while the original remains available.

Keep Django migrations and development data separate from the original Prisma/Supabase database. A new Supabase project may be connected later. Payments, including eSewa, are test-only and are not a launch requirement yet.

Use `.venv/bin/python manage.py check` and relevant Django tests after substantive changes. Update `PROJECT_CONTEXT.md` when a milestone is completed or the plan changes so future chats can continue accurately. Never commit credentials from `.env`.

## GitHub workflow requested by the user

Target repository: `https://github.com/kusal6199/clothing-store-web-app.git`. Keep two branches, `main` and `test`. Inspect the remote and preserve any existing commits before initializing or connecting this local folder. Put all Django application changes on `test`. After each completed, verified task or milestone, commit and push `test` to `origin/test`, then report the commit hash. The user will review and manually merge `test` into `main`; do not merge or push application changes to `main`, and never force-push. If the remote is empty, establish an initial minimal `main` branch, then put the application on `test`. Before any push, verify `.env`, `.venv`, local databases, and credentials are excluded. If GitHub authentication is unavailable, explain the exact blocker instead of changing the branch policy.
