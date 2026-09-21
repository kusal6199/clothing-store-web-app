from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from .models import Category, LoyaltyProgress, Message, Order, OrderItem, Product, ProductVariant, PromoCode


class ManagementAuthorizationTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="staff-only", password="test-password", is_staff=True,
        )
        self.admin = get_user_model().objects.create_superuser(
            username="store-owner", password="test-password",
        )

    def test_anonymous_is_sent_to_custom_login_and_staff_is_forbidden(self):
        url = reverse("management:products")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('management:login')}?next={url}")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get("/internal-admin/").status_code, 302)

    def test_superuser_can_access_every_management_section_and_mobile_nav_renders(self):
        self.client.force_login(self.admin)
        names = (
            "dashboard", "products", "categories", "homepage", "orders", "loyalty",
            "promo_codes", "messages", "settings",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"management:{name}")).status_code, 200)
        dashboard = self.client.get(reverse("management:dashboard"))
        self.assertContains(dashboard, "data-nav-open")
        self.assertContains(dashboard, "data-sidebar")
        self.assertContains(dashboard, "View Store")
        self.assertContains(dashboard, "Logout")

    def test_identity_and_permission_management_is_not_exposed(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management:dashboard"))
        for label in ("Users", "Groups", "Add staff", "Manage users", "Permissions"):
            self.assertNotContains(response, label)
        with self.assertRaises(NoReverseMatch):
            reverse("admin:auth_user_changelist")
        with self.assertRaises(NoReverseMatch):
            reverse("admin:auth_group_changelist")

    def test_custom_logout_is_post_only_and_legacy_dashboard_redirects(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("management:logout")).status_code, 405)
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("management:dashboard"))
        self.assertRedirects(self.client.post(reverse("management:logout")), reverse("management:login"))


class ManagementCrudTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="crud-admin", password="test-password",
        )
        self.client.force_login(self.admin)
        self.category = Category.objects.create(name="Tops", slug="tops")

    def test_product_and_variant_create_update_and_delete(self):
        create = self.client.post(reverse("management:product_add"), {
            "name": "Admin Tee", "slug": "admin-tee", "price": "500.00",
            "category": self.category.pk, "colors": "Black, White", "visibility": "on",
            "variants-TOTAL_FORMS": "1", "variants-INITIAL_FORMS": "0",
            "variants-MIN_NUM_FORMS": "0", "variants-MAX_NUM_FORMS": "1000",
            "variants-0-size": "M", "variants-0-color": "Black", "variants-0-stock": "6",
            "variants-0-additional_price": "25.00",
        })
        self.assertRedirects(create, reverse("management:products"))
        product = Product.objects.get(slug="admin-tee")
        self.assertEqual(product.colors, ["Black", "White"])
        self.assertEqual(product.variants.get().stock, 6)
        variant = product.variants.get()
        update = self.client.post(reverse("management:product_edit", args=[product.pk]), {
            "name": "Updated Tee", "slug": "admin-tee", "price": "550.00",
            "category": self.category.pk, "colors": "Black", "visibility": "on",
            "variants-TOTAL_FORMS": "1", "variants-INITIAL_FORMS": "1",
            "variants-MIN_NUM_FORMS": "0", "variants-MAX_NUM_FORMS": "1000",
            "variants-0-id": variant.pk, "variants-0-product": product.pk,
            "variants-0-size": "L", "variants-0-color": "Black", "variants-0-stock": "4",
            "variants-0-additional_price": "0.00",
        })
        self.assertRedirects(update, reverse("management:products"))
        product.refresh_from_db()
        self.assertEqual(product.name, "Updated Tee")
        self.assertEqual(product.variants.get().size, "L")
        self.assertEqual(self.client.get(reverse("management:product_delete", args=[product.pk])).status_code, 405)
        self.client.post(reverse("management:product_delete", args=[product.pk]))
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_taxonomy_promo_and_message_management(self):
        category_response = self.client.post(reverse("management:taxonomy_add", args=["collection"]), {
            "name": "Autumn", "slug": "autumn", "description": "Seasonal", "order": 2, "visible": "on",
        })
        self.assertEqual(category_response.status_code, 302)
        promo_response = self.client.post(reverse("management:promo_add"), {
            "code": "save10", "influencer_name": "Creator", "discount_percent": "10",
            "commission_percent": "5", "active": "on",
        })
        self.assertRedirects(promo_response, reverse("management:promo_codes"))
        promo = PromoCode.objects.get(code="SAVE10")
        Order.objects.create(
            order_number="PROMO-PAID", customer_name="Buyer", phone="9800000000",
            delivery_address="Kathmandu", total=Decimal("100.00"), payment_status="paid", promo_code=promo,
        )
        promo_page = self.client.get(reverse("management:promo_codes"))
        self.assertContains(promo_page, "Rs 5.00")
        self.assertEqual(self.client.get(reverse("management:promo_toggle", args=[promo.pk])).status_code, 405)
        self.client.post(reverse("management:promo_toggle", args=[promo.pk]))
        promo.refresh_from_db()
        self.assertFalse(promo.active)
        item = Message.objects.create(name="Customer", email="customer@example.com", message="Question")
        self.client.post(reverse("management:message_toggle", args=[item.pk]))
        item.refresh_from_db()
        self.assertTrue(item.is_read)


class ManagementOrderActionTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="orders-admin", password="test-password",
        )
        self.client.force_login(self.admin)
        self.tops = Category.objects.create(name="Tops", slug="action-tops")
        self.bottoms = Category.objects.create(name="Bottoms", slug="action-bottoms")
        self.product = Product.objects.create(name="Tee", slug="action-tee", category=self.tops, price=Decimal("100"))
        self.other = Product.objects.create(name="Trousers", slug="action-trousers", category=self.bottoms, price=Decimal("200"))
        self.variant = ProductVariant.objects.create(product=self.product, size="M", stock=30)
        self.other_variant = ProductVariant.objects.create(product=self.other, size="M", stock=5)

    def order(self, number, **changes):
        values = {
            "order_number": number, "customer_name": "Buyer", "phone": "9800000000",
            "delivery_address": "Kathmandu", "subtotal": Decimal("1000"), "total": Decimal("1000"),
        }
        values.update(changes)
        order = Order.objects.create(**values)
        OrderItem.objects.create(order=order, product=self.product, product_name=self.product.name,
                                 size="M", price=Decimal("100"), quantity=10)
        return order

    def test_manual_payment_action_is_post_only_and_idempotently_updates_loyalty(self):
        order = self.order("MANAGEMENT-MANUAL")
        url = reverse("management:order_confirm_payment", args=[order.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.client.post(url)
        order.refresh_from_db()
        progress = LoyaltyProgress.objects.get(phone=order.phone, category=self.tops)
        self.assertEqual(order.payment_status, "paid")
        self.assertEqual(progress.purchase_count, 10)
        self.assertEqual(order.reward_category, self.tops)

    def test_esewa_order_cannot_use_manual_payment_or_cancel_actions(self):
        order = self.order("MANAGEMENT-ESEWA", payment_method="esewa", esewa_transaction_uuid="management-esewa")
        self.client.post(reverse("management:order_confirm_payment", args=[order.pk]))
        self.client.post(reverse("management:order_cancel", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual((order.payment_status, order.order_status), ("pending", "pending"))
        with patch("shop.management_views.esewa.reconcile", return_value="pending") as reconcile:
            response = self.client.post(reverse("management:order_check_esewa", args=[order.pk]))
        self.assertRedirects(response, reverse("management:order_detail", args=[order.pk]))
        reconcile.assert_called_once()

    def test_reward_fulfilment_rejects_other_category_and_deducts_once(self):
        order = self.order("MANAGEMENT-REWARD", payment_status="paid", order_status="confirmed", reward_category=self.tops)
        LoyaltyProgress.objects.create(phone=order.phone, category=self.tops, purchase_count=10)
        url = reverse("management:order_fulfil_reward", args=[order.pk])
        self.client.post(url, {"variant": self.other_variant.pk})
        order.refresh_from_db()
        self.assertFalse(order.reward_fulfilled)
        self.client.post(url, {"variant": self.variant.pk})
        self.client.post(url, {"variant": self.variant.pk})
        order.refresh_from_db()
        self.variant.refresh_from_db()
        progress = LoyaltyProgress.objects.get(phone=order.phone, category=self.tops)
        self.assertTrue(order.reward_fulfilled)
        self.assertEqual(order.items.filter(is_reward_item=True, price=0).count(), 1)
        self.assertEqual(self.variant.stock, 29)
        self.assertEqual(progress.free_items_redeemed, 1)
