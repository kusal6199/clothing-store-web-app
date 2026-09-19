# Jersey Django

A separate Django rebuild of the clothing store in `Jersey-main`. It runs alongside the existing Next.js application and has its own migrations and database. The repository includes a public catalog fixture and its images for local evaluation. It excludes the local SQLite database, orders, messages, payment records, reviews, and admin credentials.

## What works

- Storefront: homepage sections, categories, collections, tags, product search and filters, product details, image gallery, cart, checkout, contact, newsletter signup, reviews, sitemap, and robots.txt.
- Store management: Django admin for catalog, variants, homepage, reviews, messages, newsletter subscribers, settings, promo codes, orders, and inventory; a custom overview at `/dashboard/`.
- Checkout: server-side prices, delivery charges, promo discounts, stock checks, pending orders, optional earned loyalty item, and an idempotent admin action to mark an order paid and deduct stock.
- Media: local images for development. New admin uploads can go to a public Supabase Storage bucket when configured.
- Scheduled review email command with SMTP configuration.

Payments are intentionally a test/manual workflow. Placing an order does not collect or verify payment, and it does not automatically mark the order paid.

The newsletter form stores email addresses in the local database and lets staff manage them in Django admin. It does not send marketing emails. Subscriber data is excluded from the public fixture and Git repository.

## Run locally

Requires Python 3.12 or newer.

```bash
cd ~/Desktop/Jersey-Django
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# Replace DJANGO_SECRET_KEY in .env with a unique development secret.
.venv/bin/python manage.py migrate
.venv/bin/python manage.py loaddata fixtures/public_catalog.json
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Open `http://127.0.0.1:8000/` for the shop and `http://127.0.0.1:8000/admin/` for management. Set `DJANGO_DEBUG=true` only for local development. Create a new admin account with `createsuperuser`; the existing Next.js admin password was not imported.

The fixture contains only public catalog and homepage content. Its images live in `static/catalog/`, so no local media folder or source database access is needed for a fresh clone. Run `loaddata` on a new database; it should not be used as a production data migration. Admin uploads and any new operational data remain local to your own database and `media/` folder. The optional `scripts/export_public_fixture.py` refreshes this fixture from the isolated Django development database, with an explicit model and settings allowlist.

Set `SITE_URL` to the public Django origin when deploying. Canonical links, Open Graph images, structured data, `robots.txt`, and `sitemap.xml` use it. The default is `http://127.0.0.1:8000` for local work.

For a quick check:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py test shop
```

## Use a separate Supabase database

Create a **new Supabase project** for the Django version, then put its connection string in `DATABASE_URL` in `.env`. Use the direct connection for a persistent host that supports IPv6, or Supabase's session pooler for an IPv4-only host. Do not point Django migrations at the existing Prisma database.

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require
```

Then run `manage.py migrate`. To copy current public catalog content into the new database:

```bash
.venv/bin/python scripts/import_public_catalog.py ~/Desktop/Jersey-main/.env
```

The import connects to the original database in **read-only mode** and copies public content only. It can be run again to refresh that content. It does not import operational records or credentials.

## Supabase Storage

Create a public bucket named `store-media` (or set another `SUPABASE_STORAGE_BUCKET`). Add the following server-side settings to `.env`:

```dotenv
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVER_ONLY_KEY
SUPABASE_STORAGE_BUCKET=store-media
```

New product, category, and hero images uploaded in Django admin will go to that bucket. Never put the service role key in browser code. Existing images in `media/uploads/` continue to use local URLs, so copy them to a persistent media location or migrate their URLs before deploying without local media.

## Review emails

Set SMTP details and `SITE_URL` as shown in `.env.example`, then schedule this command once daily:

```bash
.venv/bin/python manage.py send_review_requests
```

It sends one email for each eligible paid order placed 2–3 days earlier, with a review link for each product. Development defaults to the console email backend.

## Side-by-side approach

Run the Next.js site on port 3000 and this Django site on port 8000. Keep the current app and its database untouched while comparing routes and admin workflows. Once the Django version is approved, migrate current operational data with a fresh export, configure a separate production database and media storage, and switch the domain.

## Remaining production work

The visual design is a Django recreation, so it needs a page-by-page client review for exact appearance and interaction parity. The production payment provider, deployment setup, secure HTTPS settings, and a final live-data cutover are separate steps. The included development database is for side-by-side evaluation.
