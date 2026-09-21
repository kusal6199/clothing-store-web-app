from decimal import Decimal
from pathlib import Path
from threading import Barrier, Thread
from time import sleep
from unittest.mock import patch

from django.core import signing
from django.db import OperationalError, close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .loyalty import read_reward_selection_token, reward_selection_token
from .models import Category, LoyaltyProgress, Order, OrderItem, Product, ProductVariant
from .services import confirm_order_paid, fulfill_order_reward


class CustomerRewardFlowTests(TestCase):
    phone = "9801234567"

    def setUp(self):
        self.tops = Category.objects.create(name="Tops", slug="customer-reward-tops")
        self.bottoms = Category.objects.create(name="Bottoms", slug="customer-reward-bottoms")
        self.tee = Product.objects.create(
            name="Reward Tee", slug="customer-reward-tee", category=self.tops, price=Decimal("500.00"),
            images=["/static/tee.jpg"],
        )
        self.hoodie = Product.objects.create(
            name="Reward Hoodie", slug="customer-reward-hoodie", category=self.tops, price=Decimal("900.00"),
        )
        self.trousers = Product.objects.create(
            name="Other Trousers", slug="customer-reward-trousers", category=self.bottoms, price=Decimal("700.00"),
        )
        self.tee_black = ProductVariant.objects.create(product=self.tee, size="M", color="Black", stock=20)
        self.tee_white_oos = ProductVariant.objects.create(product=self.tee, size="M", color="White", stock=0)
        self.tee_no_color = ProductVariant.objects.create(product=self.tee, size="L", color=None, stock=8)
        self.hoodie_blue = ProductVariant.objects.create(product=self.hoodie, size="L", color="Blue", stock=7)
        self.other_variant = ProductVariant.objects.create(product=self.trousers, size="M", color="Black", stock=6)

    def put_in_cart(self, quantity=1):
        session = self.client.session
        session["cart"] = {self.tee_black.pk: {"quantity": quantity}}
        session.save()

    def available_reward(self, purchase_count=10):
        return LoyaltyProgress.objects.create(
            phone=self.phone, category=self.tops, purchase_count=purchase_count,
        )

    def pending_reward_order(self, number="CUSTOMER-REWARD"):
        order = Order.objects.create(
            order_number=number, customer_name="Reward Customer", phone=self.phone,
            delivery_address="Kathmandu", subtotal=Decimal("500.00"), total=Decimal("500.00"),
            payment_status="paid", order_status="confirmed", reward_category=self.tops,
        )
        OrderItem.objects.create(
            order=order, product=self.tee, product_name=self.tee.name,
            size="M", color="Black", price=Decimal("500.00"), quantity=1,
        )
        return order

    def checkout_data(self, **changes):
        data = {
            "customer_name": "Reward Customer", "phone": self.phone,
            "delivery_address": "Kathmandu", "delivery_zone": "inside",
            "payment_method": "manual", "reward_variant_id": self.hoodie_blue.pk,
        }
        data.update(changes)
        return data

    def test_loyalty_api_groups_products_and_only_in_stock_variants(self):
        self.available_reward()
        self.put_in_cart()
        payload = self.client.get(reverse("loyalty_options"), {"phone": "+977 980-123-4567"}).json()

        reward = payload["rewards"][0]
        self.assertEqual((reward["category_id"], reward["category"], reward["available"]),
                         (self.tops.pk, "Tops", 1))
        products = {product["id"]: product for product in reward["products"]}
        self.assertEqual(set(products), {self.tee.pk, self.hoodie.pk})
        self.assertEqual(products[self.tee.pk]["image"], "/static/tee.jpg")
        variants = {variant["id"]: variant for variant in products[self.tee.pk]["variants"]}
        self.assertEqual(set(variants), {self.tee_black.pk, self.tee_no_color.pk})
        self.assertEqual(variants[self.tee_black.pk], {
            "id": self.tee_black.pk, "size": "M", "color": "Black", "stock": 20,
        })
        self.assertIsNone(variants[self.tee_no_color.pk]["color"])
        self.assertNotIn(self.tee_white_oos.pk, variants)

    def test_checkout_has_separate_dependent_controls_and_prefilled_lookup(self):
        self.available_reward()
        self.put_in_cart()
        session = self.client.session
        session["checkout_draft"] = {"phone": self.phone, "reward_variant_id": self.hoodie_blue.pk}
        session.save()
        response = self.client.get(reverse("checkout"))

        self.assertContains(response, 'data-reward-product')
        self.assertContains(response, 'data-reward-size')
        self.assertContains(response, 'data-reward-color')
        self.assertContains(response, f'data-selected-variant="{self.hoodie_blue.pk}"')
        self.assertContains(response, f'value="{self.phone}"')
        script = Path("static/js/site.js").read_text()
        self.assertIn("productSelect.onchange", script)
        self.assertIn("sizeSelect.onchange", script)
        self.assertIn("loadLoyalty();", script)

    def test_checkout_reward_keeps_totals_and_records_exact_free_variant(self):
        progress = self.available_reward()
        self.put_in_cart()
        response = self.client.post(reverse("checkout"), self.checkout_data())
        order = Order.objects.get()
        reward = order.items.get(is_reward_item=True)

        self.assertRedirects(response, reverse("order_success", args=[order.order_number]))
        self.assertEqual((order.subtotal, order.delivery_charge, order.total),
                         (Decimal("500.00"), Decimal("100.00"), Decimal("600.00")))
        self.assertEqual((reward.product, reward.size, reward.color, reward.price, reward.quantity),
                         (self.hoodie, "L", "Blue", Decimal("0.00"), 1))
        confirm_order_paid(order.pk)
        progress.refresh_from_db()
        self.hoodie_blue.refresh_from_db()
        self.assertEqual(progress.free_items_redeemed, 1)
        self.assertEqual(self.hoodie_blue.stock, 6)

    def test_checkout_rejects_other_category_missing_and_out_of_stock_variants(self):
        for variant_id in (self.other_variant.pk, self.tee_white_oos.pk, "missing-variant"):
            with self.subTest(variant_id=variant_id):
                Order.objects.all().delete()
                LoyaltyProgress.objects.all().delete()
                self.available_reward()
                self.put_in_cart()
                response = self.client.post(reverse("checkout"), self.checkout_data(reward_variant_id=variant_id))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Choose a reward from a category in your bag.")
                self.assertFalse(Order.objects.exists())

    def test_checkout_selection_survives_validation_error(self):
        self.available_reward()
        self.put_in_cart()
        response = self.client.post(reverse("checkout"), self.checkout_data(customer_name=""))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"]["reward_variant_id"].value(), self.hoodie_blue.pk)
        self.assertContains(response, f'data-selected-variant="{self.hoodie_blue.pk}"')

    def test_signed_customer_link_rejects_tampering_and_expiry(self):
        self.available_reward()
        order = self.pending_reward_order()
        token = reward_selection_token(order)
        self.assertEqual(self.client.get(reverse("reward_selection", args=[token])).status_code, 200)
        self.assertEqual(self.client.get(reverse("reward_selection", args=[token + "tampered"])).status_code, 404)
        with self.assertRaises(signing.SignatureExpired):
            read_reward_selection_token(token, max_age=-1)
        with patch("shop.views.read_reward_selection_token", side_effect=signing.SignatureExpired):
            self.assertEqual(self.client.get(reverse("reward_selection", args=[token])).status_code, 410)

    def test_customer_selection_is_exact_zero_price_and_idempotent(self):
        progress = self.available_reward()
        order = self.pending_reward_order()
        url = reverse("reward_selection", args=[reward_selection_token(order)])
        first = self.client.post(url, {"reward_variant_id": self.hoodie_blue.pk})
        second = self.client.post(url, {"reward_variant_id": self.tee_black.pk})

        self.assertRedirects(first, url)
        self.assertEqual(second.status_code, 200)
        order.refresh_from_db()
        progress.refresh_from_db()
        self.hoodie_blue.refresh_from_db()
        self.tee_black.refresh_from_db()
        reward = order.items.get(is_reward_item=True)
        self.assertEqual((reward.product, reward.size, reward.color, reward.price, reward.quantity),
                         (self.hoodie, "L", "Blue", Decimal("0.00"), 1))
        self.assertEqual(order.milestone_reward_item, reward)
        self.assertEqual(order.reward_selection_source, "customer")
        self.assertEqual(progress.free_items_redeemed, 1)
        self.assertEqual(self.hoodie_blue.stock, 6)
        self.assertEqual(self.tee_black.stock, 20)
        self.assertEqual(order.items.filter(is_reward_item=True).count(), 1)

    def test_customer_selection_rejects_wrong_missing_and_unavailable_variants(self):
        progress = self.available_reward()
        order = self.pending_reward_order()
        url = reverse("reward_selection", args=[reward_selection_token(order)])
        for variant_id in (self.other_variant.pk, self.tee_white_oos.pk, "missing"):
            response = self.client.post(url, {"reward_variant_id": variant_id})
            self.assertEqual(response.status_code, 200)
            order.refresh_from_db()
            progress.refresh_from_db()
            self.assertFalse(order.reward_fulfilled)
            self.assertEqual(progress.free_items_redeemed, 0)
            self.assertFalse(order.items.filter(is_reward_item=True).exists())

    def test_manual_paid_order_shows_secure_link_only_to_placing_session(self):
        self.put_in_cart(quantity=10)
        response = self.client.post(reverse("checkout"), self.checkout_data(reward_variant_id=""))
        order = Order.objects.get()
        self.assertRedirects(response, reverse("order_success", args=[order.order_number]))
        confirm_order_paid(order.pk)

        result = self.client.get(reverse("order_success", args=[order.order_number]))
        self.assertContains(result, "You earned one free item from Tops")
        self.assertContains(result, "Choose my free item")
        anonymous_result = self.client_class().get(reverse("order_success", args=[order.order_number]))
        self.assertNotContains(anonymous_result, "Choose my free item")


class ConcurrentCustomerRewardTests(TransactionTestCase):
    reset_sequences = True

    def test_two_simultaneous_submissions_cannot_redeem_twice(self):
        category = Category.objects.create(name="Concurrent Tops", slug="concurrent-tops")
        product = Product.objects.create(
            name="Concurrent Tee", slug="concurrent-tee", category=category, price=Decimal("100.00"),
        )
        variant = ProductVariant.objects.create(product=product, size="M", color="Black", stock=4)
        order = Order.objects.create(
            order_number="CONCURRENT-REWARD", customer_name="Buyer", phone="9811111111",
            delivery_address="Kathmandu", payment_status="paid", order_status="confirmed",
            reward_category=category, total=Decimal("100.00"),
        )
        LoyaltyProgress.objects.create(phone=order.phone, category=category, purchase_count=10)
        gate = Barrier(2)
        failures = []

        def redeem():
            close_old_connections()
            gate.wait()
            for attempt in range(4):
                try:
                    fulfill_order_reward(order.pk, variant.pk, selection_source="customer")
                    break
                except OperationalError as exc:
                    if attempt == 3:
                        failures.append(exc)
                    sleep(0.02)
            close_old_connections()

        threads = [Thread(target=redeem), Thread(target=redeem)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        order.refresh_from_db()
        variant.refresh_from_db()
        progress = LoyaltyProgress.objects.get(phone=order.phone, category=category)
        self.assertTrue(order.reward_fulfilled)
        self.assertEqual(order.items.filter(is_reward_item=True).count(), 1)
        self.assertEqual(variant.stock, 3)
        self.assertEqual(progress.free_items_redeemed, 1)
