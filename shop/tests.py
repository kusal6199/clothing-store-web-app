from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from .models import Category, HomepageSection, LoyaltyProgress, NewsletterSubscriber, Order, Product, ProductVariant, PromoCode, Setting
from .services import confirm_order_paid


class PublicCatalogFixtureTests(TestCase):
    fixtures = ["public_catalog.json"]

    def test_fresh_clone_renders_public_catalog_with_packaged_images(self):
        from django.contrib.staticfiles.finders import find

        self.assertEqual(Product.objects.count(), 4)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertContains(self.client.get(reverse("catalog")), Product.objects.first().name)
        for product in Product.objects.all():
            self.assertTrue(product.primary_image.startswith("/static/catalog/"))
            self.assertIsNotNone(find(product.primary_image.removeprefix("/static/")))


class CatalogFilterTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="T-Shirts", slug="t-shirts")

    def test_pagination_preserves_search_and_merchandising_filter(self):
        for number in range(25):
            Product.objects.create(name=f"Sample Tee {number:02}", slug=f"sample-tee-{number:02}",
                                   category=self.category, price=Decimal("100.00"), featured=True)
        Product.objects.create(name="Different Coat", slug="different-coat", price=Decimal("100.00"))
        response = self.client.get(reverse("catalog"), {"q": "Sample", "filter": "featured", "page": "1"})
        self.assertEqual(response.context["page"].paginator.count, 25)
        self.assertContains(response, 'name="filter" value="featured"')
        self.assertContains(response, '?q=Sample&amp;filter=featured&amp;page=2')
        next_page = self.client.get(reverse("catalog"), {"q": "Sample", "filter": "featured", "page": "2"})
        self.assertEqual(len(next_page.context["page"].object_list), 1)

    def test_size_and_color_must_be_available_on_same_variant(self):
        product = Product.objects.create(name="Two Colours", slug="two-colours", price=Decimal("100.00"))
        ProductVariant.objects.create(product=product, size="M", color="Blue", stock=2)
        ProductVariant.objects.create(product=product, size="L", color="Red", stock=2)
        unmatched = self.client.get(reverse("catalog"), {"size": "M", "color": "Red"})
        self.assertEqual(unmatched.context["page"].paginator.count, 0)
        matched = self.client.get(reverse("catalog"), {"size": "M", "color": "Blue"})
        self.assertEqual(matched.context["page"].paginator.count, 1)


class NewsletterTests(TestCase):
    def setUp(self):
        self.section = HomepageSection.objects.create(key="newsletter", title="Stay in Style")

    def test_visible_section_saves_valid_email_once_and_can_reactivate(self):
        self.assertContains(self.client.get(reverse("home")), 'action="/newsletter/subscribe/"')
        response = self.client.post(reverse("newsletter_subscribe"), {"email": " Shopper@Example.com "})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/#newsletter")
        subscriber = NewsletterSubscriber.objects.get()
        self.assertEqual(subscriber.email, "shopper@example.com")
        subscriber.active = False
        subscriber.save()
        self.client.post(reverse("newsletter_subscribe"), {"email": "shopper@example.com"})
        self.assertEqual(NewsletterSubscriber.objects.count(), 1)
        subscriber.refresh_from_db()
        self.assertTrue(subscriber.active)

    def test_invalid_email_and_hidden_section_do_not_collect_addresses(self):
        self.client.post(reverse("newsletter_subscribe"), {"email": "invalid"})
        self.assertEqual(NewsletterSubscriber.objects.count(), 0)
        self.section.visible = False
        self.section.save()
        self.assertNotContains(self.client.get(reverse("home")), 'action="/newsletter/subscribe/"')
        self.assertEqual(self.client.post(reverse("newsletter_subscribe"), {"email": "valid@example.com"}).status_code, 404)
        self.assertEqual(NewsletterSubscriber.objects.count(), 0)


class SearchMetadataTests(TestCase):
    def test_canonical_robots_and_sitemap_use_configured_site_url(self):
        from django.test import override_settings

        with override_settings(SITE_URL="https://store.example"):
            page = self.client.get(reverse("catalog") + "?q=tee")
            self.assertContains(page, '<link rel="canonical" href="https://store.example/catalog/">')
            self.assertContains(page, '<meta property="og:url" content="https://store.example/catalog/">')
            self.assertContains(self.client.get(reverse("robots")), "Sitemap: https://store.example/sitemap.xml")
            self.assertContains(self.client.get(reverse("sitemap")), "https://store.example/catalog/")

    def test_product_schema_is_absolute_and_script_safe(self):
        import json
        import re
        from django.test import override_settings

        product = Product.objects.create(name="Tee </script><script>alert(1)</script>", slug="tee",
                                         price=Decimal("1200.00"), images=["/static/catalog/products/tee.jpg"])
        ProductVariant.objects.create(product=product, size="M", stock=2)
        with override_settings(SITE_URL="https://store.example"):
            response = self.client.get(reverse("product_detail", args=[product.slug]))
        html = response.content.decode()
        self.assertIn('href="https://store.example/products/tee/"', html)
        self.assertNotIn("</script><script>", html)
        payload = re.search(r'<script type="application/ld\+json">(.*?)</script>', html)
        self.assertIsNotNone(payload)
        schema = json.loads(payload.group(1))
        self.assertEqual(schema["@type"], "Product")
        self.assertEqual(schema["offers"]["price"], "1200.00")
        self.assertEqual(schema["offers"]["priceCurrency"], "NPR")
        self.assertEqual(schema["offers"]["availability"], "https://schema.org/InStock")
        self.assertEqual(schema["image"], ["https://store.example/static/catalog/products/tee.jpg"])


class ProductVariantPriceTests(TestCase):
    def test_variant_surcharge_is_shown_and_used_by_cart(self):
        from .services import cart_rows

        product = Product.objects.create(name="Premium Tee", slug="premium-tee", price=Decimal("1200.00"),
                                         discount_price=Decimal("1000.00"))
        variant = ProductVariant.objects.create(product=product, size="XL", stock=3,
                                                additional_price=Decimal("150.00"))
        detail = self.client.get(reverse("product_detail", args=[product.slug]))
        self.assertContains(detail, 'data-base-price="1000.00"')
        self.assertContains(detail, 'data-additional-price="150.00"')
        self.client.post(reverse("cart_add"), {"variant_id": variant.pk, "quantity": 2})
        rows = cart_rows(self.client.session["cart"])
        self.assertEqual(rows[0]["unit_price"], Decimal("1150.00"))
        self.assertEqual(rows[0]["line_total"], Decimal("2300.00"))


class CheckoutFlowTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="T-Shirts", slug="t-shirts")
        self.product = Product.objects.create(name="Everyday Tee", slug="everyday-tee", category=self.category, price=Decimal("1200.00"))
        self.variant = ProductVariant.objects.create(product=self.product, size="M", stock=5)
        Setting.objects.create(key="delivery_inside_valley", value="100")

    def test_order_uses_server_price_then_stock_changes_once_on_paid_transition(self):
        self.client.post(reverse("cart_add"), {"variant_id": self.variant.id, "quantity": 2})
        response = self.client.post(reverse("checkout"), {
            "customer_name": "Test Customer", "phone": "9800000000", "delivery_address": "Test address",
            "delivery_zone": "inside", "promo_code": "", "email": "",
        })
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.total, Decimal("2500.00"))
        self.assertEqual(order.payment_status, "pending")
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 5)
        confirm_order_paid(order.pk)
        confirm_order_paid(order.pk)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 3)
        self.assertEqual(LoyaltyProgress.objects.get(phone="9800000000").purchase_count, 2)

    def test_promo_code_discount_is_calculated_server_side(self):
        promo = PromoCode.objects.create(code="SAVE10", influencer_name="Test", discount_percent=Decimal("10.00"), max_uses=1)
        self.client.post(reverse("cart_add"), {"variant_id": self.variant.id, "quantity": 1})
        response = self.client.post(reverse("checkout"), {
            "customer_name": "Test Customer", "phone": "9800000000", "delivery_address": "Test address",
            "delivery_zone": "inside", "promo_code": "save10", "email": "",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.get().total, Decimal("1180.00"))
        promo.refresh_from_db()
        self.assertEqual(promo.current_uses, 1)

    def test_loyalty_reward_requires_earned_progress_and_is_redeemed_once(self):
        LoyaltyProgress.objects.create(phone="9800000000", category=self.category, purchase_count=10)
        self.client.post(reverse("cart_add"), {"variant_id": self.variant.id, "quantity": 1})
        response = self.client.post(reverse("checkout"), {
            "customer_name": "Test Customer", "phone": "9800000000", "delivery_address": "Test address",
            "delivery_zone": "inside", "promo_code": "", "reward_variant_id": self.variant.id,
        })
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.total, Decimal("1300.00"))
        confirm_order_paid(order.pk)
        self.variant.refresh_from_db()
        progress = LoyaltyProgress.objects.get(phone="9800000000")
        self.assertEqual(self.variant.stock, 3)
        self.assertEqual(progress.purchase_count, 11)
        self.assertEqual(progress.free_items_redeemed, 1)


class ReviewEmailTests(TestCase):
    def test_paid_order_receives_one_review_link(self):
        from datetime import timedelta
        from django.core import mail
        from django.core.management import call_command
        from django.test import override_settings
        from django.utils import timezone
        from .models import OrderItem, Review
        category = Category.objects.create(name="Accessories", slug="accessories")
        product = Product.objects.create(name="Canvas Cap", slug="canvas-cap", category=category, price=Decimal("700.00"))
        order = Order.objects.create(order_number="CS-TEST-EMAIL", customer_name="Tester",
            phone="9800000000", email="test@example.com", delivery_address="Test address",
            payment_status="paid", order_status="delivered", total=Decimal("700.00"))
        OrderItem.objects.create(order=order, product=product, product_name=product.name,
            size="One Size", price=Decimal("700.00"), quantity=1)
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(days=2, hours=12))
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            call_command("send_review_requests")
            call_command("send_review_requests")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Review.objects.filter(order=order).count(), 1)
