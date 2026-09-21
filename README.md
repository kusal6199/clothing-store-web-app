# Jersey Django

A separate Django rebuild of the clothing store in `Jersey-main`. It runs alongside the existing Next.js application and has its own migrations and database. The repository includes a public catalog fixture and its images for local evaluation. It excludes the local SQLite database, orders, messages, payment records, reviews, and admin credentials.

## What works

- Storefront: homepage sections, categories, collections, tags, product search and filters, product details, image gallery, cart, checkout, contact, newsletter signup, reviews, sitemap, and robots.txt.
- Store management: Django admin for catalog, variants, homepage, reviews, messages, newsletter subscribers, settings, promo codes, orders, and inventory; a custom overview at `/dashboard/` and grouped settings at `/dashboard/settings/`.
- Checkout: server-side prices, delivery charges, promo discounts, stock checks, pending orders, optional earned loyalty item, manual/QR payment, and eSewa ePay UAT payment with server-side verification. The paid transition updates stock and loyalty once.
- Media: local images for development. New admin uploads can go to a public Supabase Storage bucket when configured.
- Scheduled review email command with SMTP configuration.

Payments are test-only. Manual/QR orders stay pending for staff confirmation. eSewa orders use the UAT test wallet and are marked paid only after a matching server-to-server status check. Live payment endpoints are not configurable in this build.

For test orders, staff can use Django admin actions to mark an order paid or cancel an unpaid order. Cancelling an unpaid order releases its promo use and any pending loyalty reward reservation. Paid or refunded orders cannot be cancelled through that action; refunds still require a separate workflow.

The manual admin paid/cancel actions reject eSewa attempts. Staff can use **Check selected eSewa UAT payment statuses** in order admin. eSewa `COMPLETE` confirms the order, `CANCELED`/`NOT_FOUND` cancels it and releases promo use, and pending/ambiguous/unreachable results leave it pending. A completed payment that cannot pass stock or reference checks is flagged `needs_review` for investigation. Do not ask the customer to pay again while the result is uncertain.

## eSewa ePay UAT

Set these in your private `.env`:

```dotenv
ESEWA_MERCHANT_CODE=EPAYTEST
ESEWA_SECRET_KEY=YOUR_UAT_SECRET_FROM_ESEWA_DOCS
SITE_URL=http://127.0.0.1:8000
# Optional for Python installations without a usable default CA file:
# ESEWA_CA_BUNDLE=/etc/ssl/cert.pem
```

The merchant code defaults to the public UAT code `EPAYTEST`. `ESEWA_SECRET_KEY` has no default; without it, checkout offers only manual/QR. Copy the key from eSewa's [official Test Credentials page](https://developer.esewa.com.np/pages/Test-credentials). The ePay page currently displays an erroneous trailing parenthesis after the key; including it causes `ES104 Invalid payload signature`. Django's system check rejects that known typo. Do not store the key or wallet credentials in this repository.

The payment form and status check use eSewa's working UAT host at `https://rc-epay.esewa.com.np`. These URLs are fixed in code to keep this integration in UAT. The status host shown separately on the ePay page timed out during verification on 2026-09-21, while the payment host returned the existing transaction's `NOT_FOUND` status. `ESEWA_CA_BUNDLE` can point to the operating system CA bundle when a local Python installation has no default CA file; certificate verification remains enabled.

For a local browser test, restart Django after changing `.env`, add a product to the cart, choose **eSewa UAT** at checkout, and complete a test wallet payment. eSewa returns the browser to the Django success or failure URL. The result page has **Check payment status** and **Check and return to checkout** actions for pending or uncertain responses. If the customer returns to the store and changes the cart, checkout automatically rechecks the previous attempt. A definitive `CANCELED` or `NOT_FOUND` result releases it and permits a fresh order with a new UUID; `PENDING`, `AMBIGUOUS`, timeouts, and mismatches remain locked, while `COMPLETE` settles the original order. If the browser never returns, staff can run `manage.py check_esewa_payments` after five minutes (or schedule it periodically); this checks up to 100 old pending attempts per run and never treats a browser redirect as proof of payment. The signed amount is calculated from the stored Django order, including discounts and delivery. Automated tests mock the UAT status API; a real test-wallet transaction needs network access and a test login.

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

The product editor has separate upload fields for main product photos and detail gallery photos. Each save can append one image to each list; repeat to add more. Local uploads stay under the ignored `media/` directory.

## Review emails

Set SMTP details and `SITE_URL` as shown in `.env.example`, then schedule this command once daily:

```bash
.venv/bin/python manage.py send_review_requests
```

It sends one email for each eligible paid order placed 2–3 days earlier. The single link opens a page where the customer can review each distinct product separately for 30 days. Reviews still require admin approval. Development defaults to the console email backend.

## Side-by-side approach

Run the Next.js site on port 3000 and this Django site on port 8000. Keep the current app and its database untouched while comparing routes and admin workflows. Once the Django version is approved, migrate current operational data with a fresh export, configure a separate production database and media storage, and switch the domain.

## Remaining production work

The visual design is a Django recreation, so it needs a page-by-page client review for exact appearance and interaction parity. The production payment provider, deployment setup, secure HTTPS settings, and a final live-data cutover are separate steps. The included development database is for side-by-side evaluation.
