# Project handoff for future VS Code / Codex chats

Updated: 2026-09-19

## User goal and relationship to the original

The client wants the existing clothing ecommerce project rebuilt as a Django application. The user asked for a separate folder on the Desktop so both versions can be developed and compared side by side. The original project is `/Users/kushalkadel/Desktop/Jersey-main`; this Django project is `/Users/kushalkadel/Desktop/Jersey-Django`. Do not overwrite the original site or point Django migrations at its database.

The original is a Next.js/React/TypeScript storefront and custom admin. Its current source of truth is `prisma/schema.prisma`, `src/app`, `src/components`, and `src/lib` in `Jersey-main`. Its README describes an older jersey version and is partly stale; inspect code and current schema for feature comparisons. The original database URL points to Supabase PostgreSQL. The user explicitly said existing orders and eSewa/payment records are dummy tests and payment work is not a priority.

## Architecture chosen

- Django 5.2, Django templates, CSS, and small browser JavaScript. No Next.js or React runtime in this folder.
- Django ORM; local SQLite for independent development. `config/settings.py` accepts `DATABASE_URL` for a **separate** Supabase PostgreSQL project later.
- Django admin for model management, with a custom overview page at `/dashboard/`.
- Local `media/uploads/` contains copied original public image assets. New admin uploads can use a public Supabase Storage bucket if server-only settings are provided.
- `.env` contains a new local development secret. It has no original database credentials. Do not print or commit secrets.

## Current implementation

- Storefront: homepage with dynamic sections and slides, catalog/search/filters, product details and gallery, session cart, checkout, contact form, review form, sitemap, and robots.txt.
- Store logic: server-side prices, delivery charges, promo code discounts, variant stock checks, optional loyalty reward, pending order creation, and idempotent admin action to confirm paid orders, deduct stock, and update loyalty progress.
- Admin: products/variants, categories, collections, tags, homepage content, messages, reviews, settings, orders, promo codes, plus CSV order export.
- Scheduled `send_review_requests` management command; SMTP can be configured later.
- Public catalog/homepage data was copied read-only from the original Supabase database into local `db.sqlite3`: 4 products, 9 categories, 4 hero slides, and associated public content. Operational data, customer orders/messages, and original admin credentials were not copied. The import script is `scripts/import_public_catalog.py`.
- `README.md` has setup, database, and Storage instructions. The project has its own `.venv` and dependencies installed.
- The repository now has a sanitized `fixtures/public_catalog.json` and 21 referenced public images under `static/catalog/`. A fresh clone can run `loaddata` without access to the original database. The fixture excludes reviews, operational records, payment settings, and credentials. The local database and `media/` remain ignored.

## Verification already done

- `manage.py check` passed in the Desktop copy.
- Four Django tests passed for checkout, promo pricing, loyalty accounting, and review email deduplication.
- A fifth test now loads the public fixture into a fresh test database and checks that the storefront and packaged images render. All five tests pass.
- Catalog filter work after the first push: pagination now preserves active search and filter parameters; applying sidebar filters retains a homepage merchandising filter; size and colour must match the same stocked variant. Two focused tests cover these cases, bringing the suite to seven passing tests.
- The source newsletter was a display-only form that showed success without storing an address. Django now renders the configurable section on the homepage, validates and stores unique normalized addresses locally, allows staff to deactivate/reactivate them in admin, and never exports them in the public fixture. Two tests cover signup, validation, repeat signup, and hidden-section behavior. Nine tests pass after migration `0003_newslettersubscriber`.
- Public SEO metadata now uses `SITE_URL` for canonical URLs, Open Graph/Twitter cards, robots sitemap declaration, and sitemap entries. Home and product pages emit escaped JSON-LD with ClothingStore/Product data; product pages include current price, stock availability, and absolute image URLs. Two tests cover canonical URL and script-safe schema output; eleven tests pass.
- Product detail selection now updates the displayed unit price and stock count from the chosen variant, limits the quantity input to available stock, and supports hover image zoom. The server still calculates cart prices from database values. A test checks surcharge data in the page and the resulting cart price; twelve tests pass and `node --check static/js/site.js` passes. A local browser UI surface was unavailable, so interactive visual QA remains pending.
- Checkout now displays an initial total and updates delivery, promo discount, and total when the customer changes zone or validates a promo code. Promo preview calls the Django endpoint with CSRF; order creation recalculates prices and validates the code again. A test checks rendered charges, promo validation, and the final outside-valley order total. Thirteen Django tests and JavaScript syntax checking pass.
- The staff dashboard now shows a 14-day order chart with daily paid revenue details and top products by quantity from paid, non-reward order items. A staff-only dashboard test covers daily counts, pending-versus-paid revenue, and top-product attribution. Fourteen Django tests pass.
- The original homepage source renders sections in a fixed order; its homepage admin edits visibility/titles but has no section reorder control. The Django checklist no longer treats reordering as missing source parity.
- Staff now have a grouped settings form at `/dashboard/settings/` for branding, contact, social links, delivery charges, test payment instructions/QR, and newsletter copy. Nonnegative delivery charges and contact URLs are validated before saving to the existing Setting model. A test covers staff access, validation, saving, and the updated checkout charge. Fifteen Django tests pass.
- Product admin now has separate main-image and gallery-image upload fields, each appending to the correct image list. A temporary media directory test confirms both uploads are stored and referenced without touching the source project or publishing local media. Sixteen Django tests pass.
- Review request emails now send one order link. It opens a page for all distinct products, permits one moderated submission per product, and expires after 30 days. A test covers duplicate order items, one email/link, both submissions, repeat-submit rejection, and expiry. Seventeen Django tests pass; scheduling the command remains a deployment task.
- Promo discounts are bounded to 0–100% in admin/model validation and checked again during checkout, so malformed direct database values cannot create a negative order total. The paid-order action now rejects cancelled or refunded orders before inventory or loyalty changes. Migration `0004` adds the validators. Nineteen Django tests pass.
- An external HTML formatter rewrote `home.html` and `dashboard.html` during this milestone and split Django template tags; their render tests failed. The last working committed versions were restored after saving copies in `/private/tmp`, and the full suite passed again. `.prettierignore` now excludes Django templates from Prettier formatting.
- Unpaid test orders can now be cancelled through a dedicated Django admin action. It releases promo usage and pending loyalty reservations exactly once; paid/refunded orders are rejected. Directly changing an order to cancelled in the admin form is disallowed so staff use the accounting action. A test covers idempotency, promo reuse, reward reservation release, and paid-order rejection. Twenty Django tests pass.
- Product admin POSTs with blank `images`, `gallery_images`, or `colors` JSON fields now save empty lists; image uploads also append safely if an older record contains null image lists. A full admin POST test creates a product with main/gallery uploads and a variant. `manage.py check` and all 21 Django tests pass. The local development database has an admin account; its credentials and database are not tracked.
- Django test client rendered the homepage, catalog, product, cart, checkout, contact, sitemap, admin login, and loyalty lookup successfully.
- Browser visual QA could not be performed because no browser surface was available in that session. The visual design still needs comparison against the original site.
- The original `Jersey-main` Git working tree was clean after creating this separate project.

The source-derived feature checklist and current status live in `REQUIREMENTS.md`. It is a working checklist, not a formal client sign-off.

## Next work

1. Run the two sites side by side and compare every public page and admin workflow for functionality and appearance. Improve the Django templates/CSS where needed.
2. Create a Django superuser on each new environment with `.venv/bin/python manage.py createsuperuser` when admin access is needed; no default credentials are shipped.
3. Keep order/payment handling in test scope unless the user changes priorities. Do not enable live eSewa from the original's test integration.
4. When the user provides a **new** Supabase project, configure its database and Storage separately, migrate the Django schema there, and import public data with `scripts/import_public_catalog.py`. Do not run Django migrations on the original Prisma database.
5. Before launch, plan fresh operational-data migration, persistent media URLs, production hosting/HTTPS settings, and end-to-end browser QA.

## Useful commands

```bash
cd /Users/kushalkadel/Desktop/Jersey-Django
./run-dev.sh
.venv/bin/python manage.py check
.venv/bin/python manage.py test shop
.venv/bin/python manage.py createsuperuser
```

The original site can run on port 3000; Django runs on port 8000. See `README.md` for environment details.

## GitHub review workflow

The remote at `https://github.com/kusal6199/clothing-store-web-app.git` was inspected on 2026-09-19 and was empty. Git was initialized locally; `main` contains only the empty root commit `f653940` and has been pushed to `origin/main`. The Django application belongs on `test`, which should branch from that root. After each verified milestone, update this handoff and `REQUIREMENTS.md`, commit, and push `origin/test`. The user reviews and manually merges into `main`. Never force-push or put application changes directly on `main`. Verify ignored files and do not publish credentials, the local SQLite database, customer records, or other private data.

The initial Django baseline was committed and pushed on `test` as `25a8b32`. The catalog filter milestone follows it on the same branch; use `git log -1` for its commit hash after publication.
