from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from .models import Category, LoyaltyProgress, Order, Product, ProductVariant, PromoCode, Setting
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
