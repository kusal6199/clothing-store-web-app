# Django rebuild requirements and parity checklist

Updated: 2026-09-21. This is a **source-derived working checklist**, not a formally approved client specification. The user asked for the existing clothing ecommerce project to be rebuilt side by side in Python Django. Compare against the current code in `/Users/kushalkadel/Desktop/Jersey-main`; its README still describes an older jersey version. Record any new client requirements here.

## Agreed scope and constraints

1. Build a separate Django application at `/Users/kushalkadel/Desktop/Jersey-Django`. Keep the original Next.js project running and unchanged while comparing the two.
2. The final application should be Django based. Django renders the storefront with templates; browser interactions can use HTML, CSS, and small amounts of JavaScript. Next.js/React do not need to run in the final Django deployment.
3. Supabase is acceptable for PostgreSQL and optionally Storage. Use a **separate new Supabase project/database** while developing; never run Django migrations against the existing Prisma database.
4. Existing eSewa, QR, orders, and payment transactions are tests/dummy data. The user requested eSewa ePay **TEST/UAT** integration on 2026-09-20. Live payment integration remains deferred and is not a launch blocker.
5. Preserve URLs and user journeys where practical. Compare the Django storefront and admin to the original before calling the rebuild complete.

## Status legend

- **Implemented**: Working Django route/model/admin workflow exists and has at least basic verification.
- **Partial**: Some behavior exists; feature or presentation parity remains.
- **Pending**: Not implemented or not connected.
- **Deferred**: User explicitly deprioritized it.

## Storefront

| Requirement from current project | Django status | What remains |
|---|---|---|
| Dynamic homepage: hero slides, promo banner, new arrivals, categories, collections, featured products, best sellers, why-us, reviews, social, contact | Partial | Sections render from imported content; exact design and small interactions need comparison. The source uses a fixed section order. |
| Responsive navigation and footer | Partial | Implemented in templates/CSS; perform desktop and mobile visual QA. |
| Catalog search and filters for category, collection, tag, size, colour, price, in-stock, flags, and sorting | Implemented | Query parameters now survive pagination, merchandising flags survive filter form submits, and size/colour match one stocked variant. Continue visual and source edge-case comparison. |
| Product page with images, size/colour variants, price, stock, material/care text, reviews, related products | Partial | Variant selection now updates displayed price and stock; hover zoom is present. Browser interaction and design comparison remain. |
| Cart add/update/remove with persistence | Implemented | Django sessions provide persistence; compare browser behavior and test multiple variants. |
| Checkout with customer/delivery fields, delivery-zone charges, server-side prices, promo discounts, loyalty item | Partial | Delivery and promo previews now update the summary; server recalculates final charges. Browser interaction and loyalty presentation still need comparison. |
| QR/manual payment instructions and order success | Partial | QR display and pending order creation work. Screenshot upload and richer confirmation flow are pending. |
| eSewa ePay UAT checkout and verification | Implemented | Server signs the stored total, verifies the signed return when present and UAT status response, and confirms only matching complete payments. The known UAT key typo is rejected. Cancelled/expired attempts safely release checkout after a status recheck; pending/ambiguous/timeout results remain locked. An exact Django form received HTTP 302 and opened UAT's ePay login page; wallet login/payment and callback QA remain. Live payments remain deferred. |
| Contact form and editable contact details | Implemented | Check appearance and notification needs. |
| Token-based product reviews, approval, and review request emails | Partial | One email now opens all products in an order, with separate moderated reviews and 30-day expiry. Schedule the command and run browser/email delivery QA for deployment. |
| SEO title/description, sitemap, robots, canonical URLs, Open Graph, structured data | Implemented | Canonical and social metadata plus home/product JSON-LD render from `SITE_URL`; verify production domain and crawl results during deployment. |
| Newsletter section | Implemented | The original only showed a success toast. Django now renders the configurable section and stores validated subscriber addresses locally for staff management. Marketing email delivery remains a future decision. |
| Smooth animations, loading feedback, accessible responsive details | Partial | Basic CSS/JS exists; compare with original and improve where important. |

## Store management

| Requirement from current project | Django status | What remains |
|---|---|---|
| Admin login and account management | Implemented | Uses Django users/admin; create a new superuser locally. Original credentials were not copied. |
| Overview counts: products, orders, paid revenue, messages, visitors, customers | Partial | `/dashboard/` now has counts, a 14-day order chart with daily paid revenue, top products from paid orders, and linked recent orders; visual/admin workflow comparison remains. |
| Product, variant stock, category, collection, tag CRUD | Implemented | Managed through Django admin; compare validation and ease of use with original custom UI. |
| Image upload for products, categories, hero slides | Partial | Product admin now appends separate main and gallery photos even when their JSON fields are blank or null; a full admin POST with uploads and a variant is tested. Category/hero uploads and configured Supabase Storage still need end-to-end QA, plus production media migration. |
| Homepage content, visibility, titles, hero and promo management | Partial | Models are editable in Django admin; image preview/editor convenience still needs comparison. The source has no section reorder control. |
| Orders: list/search/filter/detail/status, mark paid, stock/loyalty transition, CSV export | Partial | Django admin covers these; unpaid cancellation releases promo/reward reservations once, and paid/cancelled transition guards exist. Paid refunds and custom status workflow still need comparison. Payments remain test-only. |
| Promo codes: validation, limits, percentage discount, attribution | Partial | Code, usage limit, and 0–100% discount validation plus admin CRUD exist. Influencer commission reports are pending. |
| Loyalty progress and free item redemption | Partial | Core count/redemption works with paid confirmation; compare all original reward/reservation/fulfilment edge cases. |
| Reviews and contact messages moderation | Implemented | Available through Django admin; compare convenience actions with original. |
| Settings: delivery, QR, contact, social, branding, footer | Implemented | Staff can edit grouped settings at `/dashboard/settings/`; delivery charges and contact URLs are validated. Compare convenience and presentation with the source. |
| Visitor tracking and analytics | Partial | Visitor count and records exist; charts/reporting and privacy review are pending. |

## Data, infrastructure, and verification

| Requirement | Status | What remains |
|---|---|---|
| Independent local Django project and environment | Implemented | `./run-dev.sh`, migrations, local SQLite, and a sanitized public catalog fixture work. Fresh clones can load the fixture without source database access. |
| Copy public source data without changing the source DB | Implemented | 4 products, 9 categories, 4 slides, and related public content imported from source in read-only mode. |
| Separate Supabase PostgreSQL database | Pending | User must create/provide a new project and connection string; then run Django migrations and public import. |
| Supabase Storage | Partial | Server-side upload code exists; new bucket and server-only key are not configured. Existing local media need migration for remote deployment. |
| Existing operational data migration | Pending | Fresh source export and mapping at cutover; dummy/test order records were intentionally excluded from local DB. |
| Development tests and route rendering | Partial | `manage.py check` and 42 tests pass, including safe eSewa cancellation/retry, the UAT key typo and status transport regressions, mocked signing/status/callback cases, fixture loading, catalog filters, newsletter signup, SEO metadata, variant prices, checkout totals, staff dashboard analytics, grouped settings, local product media, a full product admin POST, multi-product reviews, and order/promo transitions; test more admin and error flows as parity work continues. |
| Browser visual comparison | Pending | No browser surface was available in this session either; compare desktop/mobile views and interactions against Next.js when one is available. |
| Production deployment and domain switch | Pending | Configure Django host, HTTPS, persistent assets, background scheduling, backups, and monitoring after client approval. |
| Live eSewa/payment launch | Deferred | UAT integration does not configure live eSewa credentials or endpoints. Production onboarding and real transactions remain separate. |

## How to continue in a new chat

Read `AGENTS.md`, `PROJECT_CONTEXT.md`, this file, and `README.md`. Inspect the source code in `Jersey-main` for any row being implemented. Work through the pending/partial items in practical order, updating statuses only after verification. Do not claim the entire rebuild is complete solely because the Django app runs.
