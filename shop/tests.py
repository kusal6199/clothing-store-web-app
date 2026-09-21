from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from .models import Category, HomepageSection, LoyaltyProgress, NewsletterSubscriber, Order, OrderItem, Product, ProductVariant, PromoCode, Setting
from .services import InvalidOrderTransition, confirm_order_paid, fulfill_order_reward


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


class DashboardAnalyticsTests(TestCase):
    def test_superuser_dashboard_counts_daily_orders_and_paid_product_sales(self):
        from datetime import timedelta
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        paid = Order.objects.create(order_number="PAID-TODAY", customer_name="A", phone="9800000000",
                                    delivery_address="Address", total=Decimal("500.00"), payment_status="paid")
        pending = Order.objects.create(order_number="PENDING-TODAY", customer_name="B", phone="9800000001",
                                       delivery_address="Address", total=Decimal("1000.00"))
        older = Order.objects.create(order_number="PAID-YESTERDAY", customer_name="C", phone="9800000002",
                                     delivery_address="Address", total=Decimal("300.00"), payment_status="paid")
        Order.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
        OrderItem.objects.create(order=paid, product_name="Tee", size="M", price=Decimal("250.00"), quantity=2)
        OrderItem.objects.create(order=older, product_name="Tee", size="M", price=Decimal("300.00"), quantity=1)
        OrderItem.objects.create(order=pending, product_name="Tee", size="M", price=Decimal("100.00"), quantity=10)
        OrderItem.objects.create(order=paid, product_name="Reward", size="M", price=Decimal("0.00"), quantity=1,
                                 is_reward_item=True)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        superuser = get_user_model().objects.create_superuser(username="admin", password="test-password")
        self.client.force_login(superuser)
        response = self.client.get(reverse("management:dashboard"))
        self.assertEqual(response.status_code, 200)
        days = response.context["chart"]
        self.assertEqual(len(days), 14)
        self.assertEqual(days[-1]["count"], 2)
        self.assertEqual(days[-1]["revenue"], Decimal("500.00"))
        self.assertEqual(days[-2]["count"], 1)
        self.assertEqual(response.context["top_products"][0]["quantity"], 3)
        self.assertContains(response, "Sales overview")


class StoreSettingsTests(TestCase):
    def test_only_superuser_can_edit_grouped_settings_with_valid_delivery_charges(self):
        from django.contrib.auth import get_user_model

        url = reverse("management:settings")
        self.assertEqual(self.client.get(url).status_code, 302)
        superuser = get_user_model().objects.create_superuser(username="settings-admin", password="test-password")
        self.client.force_login(superuser)
        self.assertContains(self.client.get(url), "Test payment instructions")
        values = {"site_name": "Example Store", "currency": "Rs", "delivery_inside_valley": "-1",
                  "delivery_outside_valley": "250", "email": "store@example.com"}
        invalid = self.client.post(url, values)
        self.assertEqual(invalid.status_code, 200)
        self.assertIn("delivery_inside_valley", invalid.context["form"].errors)
        self.assertFalse(Setting.objects.filter(key="site_name").exists())
        values["delivery_inside_valley"] = "125"
        self.assertEqual(self.client.post(url, values).status_code, 302)
        self.assertEqual(Setting.objects.get(key="site_name").value, "Example Store")
        self.assertEqual(Setting.objects.get(key="delivery_inside_valley").value, "125")
        self.assertEqual(Setting.objects.get(key="email").value, "store@example.com")
        product = Product.objects.create(name="Tee", slug="tee", price=Decimal("500.00"))
        variant = ProductVariant.objects.create(product=product, size="M", stock=1)
        self.client.post(reverse("cart_add"), {"variant_id": variant.pk, "quantity": 1})
        self.assertContains(self.client.get(reverse("checkout")), 'data-inside-charge="125"')


class AdminMediaTests(TestCase):
    def test_product_admin_saves_main_and_gallery_uploads_locally(self):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from django.contrib import admin
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image
        from .admin import ProductAdmin
        from .admin_forms import ProductAdminForm

        output = BytesIO()
        Image.new("RGB", (4, 4), color="green").save(output, format="PNG")
        image_bytes = output.getvalue()
        with TemporaryDirectory() as directory, override_settings(
            MEDIA_ROOT=Path(directory), MEDIA_URL="/uploads/", SUPABASE_URL="", SUPABASE_SERVICE_ROLE_KEY=""
        ):
            form = ProductAdminForm(data={
                "name": "Media Tee", "slug": "media-tee", "price": "500.00",
                "images": "", "gallery_images": "", "colors": "",
            }, files={
                "image_upload": SimpleUploadedFile("main.png", image_bytes, content_type="image/png"),
                "gallery_upload": SimpleUploadedFile("detail.png", image_bytes, content_type="image/png"),
            })
            self.assertTrue(form.is_valid(), form.errors)
            ProductAdmin(Product, admin.site).save_model(None, form.save(commit=False), form, False)
            product = Product.objects.get(slug="media-tee")
            self.assertEqual(len(product.images), 1)
            self.assertEqual(len(product.gallery_images), 1)
            self.assertEqual(product.colors, [])
            for url in [*product.images, *product.gallery_images]:
                self.assertTrue(url.startswith("/uploads/products/"))
                self.assertTrue((Path(directory) / url.removeprefix("/uploads/")).is_file())

    def test_admin_post_creates_product_with_blank_json_fields_and_variant(self):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from django.contrib.auth import get_user_model
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image

        output = BytesIO()
        Image.new("RGB", (4, 4), color="blue").save(output, format="PNG")
        image_bytes = output.getvalue()
        admin_user = get_user_model().objects.create_superuser(username="media-admin", password="test-password")
        self.client.force_login(admin_user)
        with TemporaryDirectory() as directory, override_settings(
            MEDIA_ROOT=Path(directory), MEDIA_URL="/uploads/", SUPABASE_URL="", SUPABASE_SERVICE_ROLE_KEY=""
        ):
            response = self.client.post(reverse("admin:shop_product_add"), {
                "name": "Admin Tee", "slug": "admin-tee", "price": "500.00",
                "images": "", "gallery_images": "", "colors": "",
                "image_upload": SimpleUploadedFile("main.png", image_bytes, content_type="image/png"),
                "gallery_upload": SimpleUploadedFile("detail.png", image_bytes, content_type="image/png"),
                "variants-TOTAL_FORMS": "1", "variants-INITIAL_FORMS": "0",
                "variants-MIN_NUM_FORMS": "0", "variants-MAX_NUM_FORMS": "1000",
                "variants-0-size": "Large", "variants-0-color": "Black", "variants-0-stock": "10",
                "variants-0-additional_price": "0.00", "_save": "Save",
            })
            self.assertEqual(response.status_code, 302, getattr(response, "context", None))
            product = Product.objects.get(slug="admin-tee")
            self.assertEqual(len(product.images), 1)
            self.assertEqual(len(product.gallery_images), 1)
            self.assertEqual(product.colors, [])
            self.assertEqual(product.variants.get().stock, 10)


class PromoAndOrderGuardTests(TestCase):
    def test_invalid_promo_percent_cannot_create_negative_total(self):
        from django.core.exceptions import ValidationError

        promo = PromoCode.objects.create(code="TOO-MUCH", influencer_name="Test", discount_percent=Decimal("150.00"))
        with self.assertRaises(ValidationError):
            promo.full_clean()
        product = Product.objects.create(name="Tee", slug="promo-tee", price=Decimal("100.00"))
        variant = ProductVariant.objects.create(product=product, size="M", stock=1)
        self.client.post(reverse("cart_add"), {"variant_id": variant.pk, "quantity": 1})
        self.assertEqual(self.client.post(reverse("promo_validate"), {"code": promo.code}).status_code, 400)
        checkout = self.client.post(reverse("checkout"), {
            "customer_name": "Test", "phone": "9800000000", "delivery_address": "Address",
            "delivery_zone": "inside", "promo_code": promo.code,
        })
        self.assertEqual(checkout.status_code, 200)
        self.assertContains(checkout, "invalid discount")
        self.assertEqual(Order.objects.count(), 0)

    def test_cancelled_order_cannot_be_marked_paid_or_deduct_stock(self):
        from .services import InvalidOrderTransition

        product = Product.objects.create(name="Tee", slug="cancelled-tee", price=Decimal("100.00"))
        variant = ProductVariant.objects.create(product=product, size="M", stock=3)
        order = Order.objects.create(order_number="CANCELLED-TEST", customer_name="Test", phone="9800000000",
                                     delivery_address="Address", order_status="cancelled", total=Decimal("100.00"))
        OrderItem.objects.create(order=order, product=product, product_name=product.name, size="M",
                                 price=Decimal("100.00"), quantity=1)
        with self.assertRaises(InvalidOrderTransition):
            confirm_order_paid(order.pk)
        variant.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(variant.stock, 3)
        self.assertEqual(order.payment_status, "pending")


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

    def test_checkout_summary_uses_delivery_zone_and_server_promo_validation(self):
        Setting.objects.create(key="delivery_outside_valley", value="250")
        PromoCode.objects.create(code="SAVE10", influencer_name="Test", discount_percent=Decimal("10.00"))
        self.client.post(reverse("cart_add"), {"variant_id": self.variant.id, "quantity": 1})
        initial = self.client.get(reverse("checkout"))
        self.assertContains(initial, 'data-inside-charge="100"')
        self.assertContains(initial, 'data-outside-charge="250"')
        self.assertContains(initial, 'data-total>Rs 1300</strong>')
        self.assertEqual(initial.content.decode().count('name="promo_code"'), 1)
        promo = self.client.post(reverse("promo_validate"), {"code": "SAVE10"})
        self.assertEqual(promo.json()["discount"], "120.00")
        outside = self.client.post(reverse("checkout"), {
            "customer_name": "Test Customer", "phone": "9800000000", "delivery_address": "Test address",
            "delivery_zone": "outside", "promo_code": "SAVE10", "email": "",
        })
        self.assertEqual(outside.status_code, 302)
        self.assertEqual(Order.objects.get().total, Decimal("1330.00"))

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

    def test_unpaid_cancellation_releases_promo_and_reward_reservation_once(self):
        from .services import cancel_pending_order, InvalidOrderTransition
        from .admin_forms import OrderAdminForm

        promo = PromoCode.objects.create(code="ONCE", influencer_name="Test", discount_percent=Decimal("10.00"), max_uses=1)
        LoyaltyProgress.objects.create(phone="9800000000", category=self.category, purchase_count=10)
        self.client.post(reverse("cart_add"), {"variant_id": self.variant.id, "quantity": 1})
        response = self.client.post(reverse("checkout"), {
            "customer_name": "Test Customer", "phone": "9800000000", "delivery_address": "Test address",
            "delivery_zone": "inside", "promo_code": "ONCE", "reward_variant_id": self.variant.id,
        })
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        promo.refresh_from_db()
        self.assertEqual(promo.current_uses, 1)
        direct_edit = OrderAdminForm(instance=order, data={"order_status": "cancelled"})
        self.assertIn("order_status", direct_edit.errors)
        cancel_pending_order(order.pk)
        cancel_pending_order(order.pk)
        order.refresh_from_db()
        promo.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.order_status, "cancelled")
        self.assertEqual(promo.current_uses, 0)
        self.assertEqual(self.variant.stock, 5)
        self.assertFalse(Order.objects.filter(phone="9800000000", reward_category=self.category,
                                              payment_status="pending").exclude(order_status="cancelled").exists())
        self.client.post(reverse("cart_add"), {"variant_id": self.variant.id, "quantity": 1})
        reused = self.client.post(reverse("checkout"), {
            "customer_name": "Test Customer", "phone": "9800000000", "delivery_address": "Test address",
            "delivery_zone": "inside", "promo_code": "ONCE",
        })
        self.assertEqual(reused.status_code, 302)
        new_order = Order.objects.exclude(pk=order.pk).get()
        confirm_order_paid(new_order.pk)
        with self.assertRaises(InvalidOrderTransition):
            cancel_pending_order(new_order.pk)
        promo.refresh_from_db()
        self.assertEqual(promo.current_uses, 1)


class LoyaltyMilestoneTests(TestCase):
    def setUp(self):
        self.tops = Category.objects.create(name="Tops", slug="loyalty-tops")
        self.bottoms = Category.objects.create(name="Bottoms", slug="loyalty-bottoms")
        self.tee = Product.objects.create(
            name="Loyalty Tee", slug="loyalty-tee", category=self.tops, price=Decimal("100.00"))
        self.hoodie = Product.objects.create(
            name="Loyalty Hoodie", slug="loyalty-hoodie", category=self.tops, price=Decimal("200.00"))
        self.trousers = Product.objects.create(
            name="Loyalty Trousers", slug="loyalty-trousers", category=self.bottoms, price=Decimal("300.00"))
        self.tee_variant = ProductVariant.objects.create(product=self.tee, size="M", stock=100)
        self.tee_large_variant = ProductVariant.objects.create(product=self.tee, size="L", stock=100)
        self.hoodie_variant = ProductVariant.objects.create(product=self.hoodie, size="L", stock=100)
        self.trouser_variant = ProductVariant.objects.create(product=self.trousers, size="M", stock=100)

    def order(self, number, phone, lines, **changes):
        fields = {
            "order_number": number, "customer_name": "Loyalty Customer", "phone": phone,
            "delivery_address": "Address", "subtotal": Decimal("100.00"),
            "total": Decimal("100.00"), "payment_method": "manual",
        }
        fields.update(changes)
        order = Order.objects.create(**fields)
        for variant, quantity, is_reward in lines:
            OrderItem.objects.create(
                order=order, product=variant.product, product_name=variant.product.name,
                size=variant.size, color=variant.color or "", price=Decimal("0.00") if is_reward else variant.product.price,
                quantity=quantity, is_reward_item=is_reward,
            )
        return order

    def test_one_manual_paid_order_of_ten_earns_pending_reward_once(self):
        order = self.order("LOYALTY-10", "+977 980-000-0000", [(self.tee_variant, 10, False)])
        self.assertFalse(LoyaltyProgress.objects.exists())
        confirm_order_paid(order.pk)
        confirm_order_paid(order.pk)

        order.refresh_from_db()
        progress = LoyaltyProgress.objects.get()
        self.tee_variant.refresh_from_db()
        self.assertEqual(order.phone, "9800000000")
        self.assertEqual((order.payment_status, order.reward_category_id, order.reward_fulfilled),
                         ("paid", self.tops.pk, False))
        self.assertEqual((progress.purchase_count, progress.free_items_redeemed), (10, 0))
        self.assertEqual(self.tee_variant.stock, 90)

    def test_two_paid_orders_combine_products_and_phone_formats_by_category(self):
        first = self.order("LOYALTY-6", "+977 981-234-5678", [(self.tee_variant, 6, False)])
        second = self.order("LOYALTY-4", "9812345678", [
            (self.hoodie_variant, 2, False), (self.tee_large_variant, 2, False)])
        confirm_order_paid(first.pk)
        confirm_order_paid(second.pk)

        first.refresh_from_db()
        second.refresh_from_db()
        progress = LoyaltyProgress.objects.get(phone="9812345678", category=self.tops)
        self.assertIsNone(first.reward_category_id)
        self.assertEqual(second.reward_category_id, self.tops.pk)
        self.assertEqual(progress.purchase_count, 10)
        self.assertEqual(LoyaltyProgress.objects.filter(phone="9812345678", category=self.tops).count(), 1)

    def test_additional_reward_from_twenty_items_remains_available_at_checkout(self):
        order = self.order("LOYALTY-20", "9812345679", [(self.tee_variant, 20, False)])
        confirm_order_paid(order.pk)
        session = self.client.session
        session["cart"] = {self.tee_variant.pk: {"quantity": 1}}
        session.save()

        payload = self.client.get(reverse("loyalty_options"), {"phone": "9812345679"}).json()
        self.assertEqual(payload["progress"][0]["qualifying_items"], 20)
        self.assertEqual(payload["progress"][0]["available"], 1)
        self.assertEqual(payload["rewards"][0]["available"], 1)
        order.refresh_from_db()
        self.assertEqual(order.reward_category_id, self.tops.pk)
        self.assertFalse(order.reward_fulfilled)

    def test_pending_failed_cancelled_refunded_nine_and_split_categories_do_not_earn(self):
        nine = self.order("LOYALTY-9", "9800000001", [(self.tee_variant, 9, False)])
        confirm_order_paid(nine.pk)
        self.order("LOYALTY-PENDING", "9800000002", [(self.tee_variant, 10, False)])
        self.order("LOYALTY-FAILED", "9800000003", [(self.tee_variant, 10, False)], payment_status="failed")
        self.order("LOYALTY-CANCELLED", "9800000004", [(self.tee_variant, 10, False)], order_status="cancelled")
        self.order("LOYALTY-REFUNDED", "9800000005", [(self.tee_variant, 10, False)], payment_status="refunded")
        split = self.order("LOYALTY-SPLIT", "9800000006", [
            (self.tee_variant, 5, False), (self.trouser_variant, 5, False)])
        confirm_order_paid(split.pk)

        nine.refresh_from_db()
        split.refresh_from_db()
        self.assertIsNone(nine.reward_category_id)
        self.assertEqual(LoyaltyProgress.objects.get(phone="9800000001").purchase_count, 9)
        self.assertFalse(LoyaltyProgress.objects.filter(phone__in=[
            "9800000002", "9800000003", "9800000004", "9800000005"]).exists())
        self.assertIsNone(split.reward_category_id)
        self.assertEqual(set(LoyaltyProgress.objects.filter(phone="9800000006").values_list("purchase_count", flat=True)), {5})

    def test_customer_reward_service_validates_category_and_redeems_once(self):
        order = self.order("LOYALTY-FULFIL", "9800000007", [(self.tee_variant, 10, False)])
        confirm_order_paid(order.pk)
        with self.assertRaises(InvalidOrderTransition):
            fulfill_order_reward(order.pk, self.trouser_variant.pk)

        fulfill_order_reward(order.pk, self.hoodie_variant.pk)
        fulfill_order_reward(order.pk, self.hoodie_variant.pk)

        order.refresh_from_db()
        self.hoodie_variant.refresh_from_db()
        progress = LoyaltyProgress.objects.get(phone="9800000007", category=self.tops)
        reward = order.items.get(is_reward_item=True)
        self.assertTrue(order.reward_fulfilled)
        self.assertEqual(order.milestone_reward_item, reward)
        self.assertEqual(order.reward_selection_source, "customer")
        self.assertEqual((reward.product, reward.price, reward.quantity), (self.hoodie, Decimal("0.00"), 1))
        self.assertEqual((progress.purchase_count, progress.free_items_redeemed), (10, 1))
        self.assertEqual(self.hoodie_variant.stock, 99)

    def test_free_item_does_not_earn_progress_and_lookup_reports_progress(self):
        LoyaltyProgress.objects.create(phone="9800000008", category=self.tops, purchase_count=10)
        order = self.order("LOYALTY-REDEEM", "9800000008", [
            (self.tee_variant, 1, False), (self.hoodie_variant, 1, True)],
            reward_category=self.tops)
        confirm_order_paid(order.pk)
        progress = LoyaltyProgress.objects.get(phone="9800000008", category=self.tops)
        self.assertEqual((progress.purchase_count, progress.free_items_redeemed), (11, 1))
        self.assertTrue(Order.objects.get(pk=order.pk).reward_fulfilled)

        session = self.client.session
        session["cart"] = {self.tee_variant.pk: {"quantity": 1}}
        session.save()
        response = self.client.get(reverse("loyalty_options"), {"phone": "+977 980-000-0008"})
        self.assertEqual(response.json()["progress"], [{
            "category_id": self.tops.pk, "category": "Tops", "qualifying_items": 11,
            "towards_next": 1, "available": 0,
        }])
        self.assertEqual(response.json()["rewards"], [])

    def test_admin_cannot_choose_customer_reward_and_blocks_shipping(self):
        from django.contrib.auth import get_user_model
        from .admin_forms import OrderAdminForm

        order = self.order("LOYALTY-ADMIN", "9800000009", [(self.tee_variant, 10, False)])
        confirm_order_paid(order.pk)
        form = OrderAdminForm(instance=Order.objects.get(pk=order.pk))
        self.assertNotIn("reward_variant", form.fields)
        shipping = OrderAdminForm({"order_status": "shipped"}, instance=Order.objects.get(pk=order.pk))
        self.assertFalse(shipping.is_valid())
        self.assertIn("customer must select", shipping.errors["order_status"][0])
        admin_user = get_user_model().objects.create_superuser(username="loyalty-admin", password="test-password")
        self.client.force_login(admin_user)
        response = self.client.get(reverse("admin:shop_order_change", args=[order.pk]))
        self.assertContains(response, "Awaiting customer reward selection")
        self.assertContains(response, "Buy 10 paid items from the same category using the same phone number")


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

    def test_one_link_reviews_all_products_once_and_expires(self):
        from datetime import timedelta
        from django.core import mail
        from django.core.management import call_command
        from django.test import override_settings
        from django.utils import timezone
        from .models import Review

        first = Product.objects.create(name="Tee", slug="review-tee", price=Decimal("500.00"))
        second = Product.objects.create(name="Hoodie", slug="review-hoodie", price=Decimal("900.00"))
        order = Order.objects.create(order_number="CS-MULTI-REVIEW", customer_name="Reviewer", phone="9800000000",
                                     email="reviewer@example.com", delivery_address="Address", payment_status="paid")
        for product in (first, second, first):
            OrderItem.objects.create(order=order, product=product, product_name=product.name, size="M",
                                     price=product.price, quantity=1)
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(days=2, hours=12))
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SITE_URL="https://store.example"):
            call_command("send_review_requests")
            call_command("send_review_requests")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].body.count("https://store.example/review/"), 1)
        self.assertEqual(Review.objects.filter(order=order).count(), 2)
        master = Review.objects.filter(order=order).first()
        url = reverse("review_by_token", args=[master.review_token])
        page = self.client.get(url)
        self.assertContains(page, first.name)
        self.assertContains(page, second.name)
        other = Review.objects.get(order=order, product=second)
        submission = {"product_id": second.pk, f"{other.pk}-rating": "4",
                      f"{other.pk}-comment": "A comfortable hoodie.", f"{other.pk}-name": "Happy Shopper"}
        self.assertEqual(self.client.post(url, submission).status_code, 302)
        other.refresh_from_db()
        self.assertIsNotNone(other.used_at)
        self.assertEqual(other.name, "Happy Shopper")
        self.assertFalse(other.approved)
        self.assertEqual(self.client.post(url, submission).status_code, 400)
        remaining = Review.objects.get(order=order, product=first)
        self.assertEqual(self.client.post(url, {"product_id": first.pk, f"{remaining.pk}-rating": "5",
                                                f"{remaining.pk}-comment": "A very good everyday tee."}).status_code, 302)
        self.assertContains(self.client.get(url), "Thank you for your feedback!")
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(days=31))
        self.assertEqual(self.client.get(url).status_code, 410)
