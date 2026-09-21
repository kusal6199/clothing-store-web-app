import base64
import io
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from . import esewa
from .checks import esewa_uat_configuration
from .models import Category, LoyaltyProgress, Order, Product, ProductVariant, PromoCode, Setting
from .services import InvalidOrderTransition, cancel_pending_order, confirm_order_paid


class StatusBody(io.BytesIO):
    status = 200


@override_settings(ESEWA_SECRET_KEY="synthetic-test-secret", ESEWA_MERCHANT_CODE="EPAYTEST",
                   SITE_URL="http://127.0.0.1:8000")
class EsewaFlowTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Tops", slug="tops")
        self.product = Product.objects.create(name="Tee", slug="tee", category=self.category,
                                              price=Decimal("1200.00"))
        self.variant = ProductVariant.objects.create(product=self.product, size="M", stock=5)
        Setting.objects.create(key="delivery_inside_valley", value="100")
        self.client.post(reverse("cart_add"), {"variant_id": self.variant.pk, "quantity": 2})

    def place(self, **extra):
        data = {"customer_name": "Buyer", "phone": "9800000000", "delivery_address": "Test address",
                "delivery_zone": "inside", "payment_method": "esewa"}
        data.update(extra)
        response = self.client.post(reverse("checkout"), data)
        return response, Order.objects.latest("created_at")

    def status(self, order, *, status="COMPLETE", **changes):
        payload = {"product_code": order.esewa_product_code,
                   "transaction_uuid": order.esewa_transaction_uuid,
                   "total_amount": float(order.total), "status": status,
                   "ref_id": "REF123" if status == "COMPLETE" else None}
        payload.update(changes)
        return StatusBody(json.dumps(payload).encode())

    def signed_data(self, order, **changes):
        payload = {"transaction_code": "REF123", "status": "COMPLETE",
                   "total_amount": "2500.0", "transaction_uuid": order.esewa_transaction_uuid,
                   "product_code": order.esewa_product_code,
                   "signed_field_names": esewa.RESPONSE_FIELDS}
        payload.update(changes)
        message = ",".join(f"{key}={payload[key]}" for key in esewa.RESPONSE_FIELDS.split(","))
        payload["signature"] = esewa.sign(message)
        return base64.b64encode(json.dumps(payload).encode()).decode()

    def test_pending_order_and_server_signed_form(self):
        response, order = self.place()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(order.payment_method, "esewa")
        self.assertEqual(order.payment_status, "pending")
        self.assertEqual(order.total, Decimal("2500.00"))
        self.assertEqual(order.esewa_product_code, "EPAYTEST")
        self.assertContains(response, esewa.PAYMENT_URL)
        fields = response.context["payment_fields"]
        self.assertEqual(fields["amount"], "2400.00")
        self.assertEqual(fields["product_delivery_charge"], "100.00")
        self.assertEqual(fields["total_amount"], "2500.00")
        self.assertEqual(fields["signature"], esewa.sign(
            f"total_amount=2500.00,transaction_uuid={order.esewa_transaction_uuid},product_code=EPAYTEST"))
        self.assertEqual(self.variant.stock, 5)

    def test_uat_configuration_rejects_trailing_parenthesis_typo(self):
        with override_settings(ESEWA_SECRET_KEY="synthetic-uat-key"):
            self.assertTrue(esewa.configured())
            self.assertEqual(esewa_uat_configuration(None), [])
        with override_settings(ESEWA_SECRET_KEY="synthetic-uat-key("):
            self.assertFalse(esewa.configured())
            self.assertEqual(esewa_uat_configuration(None)[0].id, "shop.E001")

    def test_status_check_uses_working_uat_host_and_configured_ca_bundle(self):
        _, order = self.place()
        with (override_settings(ESEWA_CA_BUNDLE="/tmp/test-ca.pem"),
              patch("shop.esewa.ssl.create_default_context", return_value="context") as context,
              patch("shop.esewa.urlopen", return_value=self.status(order, status="PENDING")) as request):
            self.assertEqual(esewa.status_response(order)["status"], "PENDING")
        context.assert_called_once_with(cafile="/tmp/test-ca.pem")
        self.assertTrue(request.call_args.args[0].startswith(
            "https://rc-epay.esewa.com.np/api/epay/transaction/status/?"))
        self.assertEqual(request.call_args.kwargs["context"], "context")

    def test_discounted_amount_is_signed_from_stored_order(self):
        PromoCode.objects.create(code="SAVE10", influencer_name="Test", discount_percent=10)
        response, order = self.place(promo_code="SAVE10")
        fields = response.context["payment_fields"]
        self.assertEqual(order.total, Decimal("2260.00"))
        self.assertEqual(fields["amount"], "2160.00")
        self.assertEqual(fields["total_amount"], "2260.00")
        self.assertEqual(fields["signature"], esewa.sign(
            f"total_amount=2260.00,transaction_uuid={order.esewa_transaction_uuid},product_code=EPAYTEST"))

    def test_signed_success_and_status_settle_once(self):
        _, order = self.place()
        url = reverse("esewa_success", args=[order.esewa_transaction_uuid])
        with patch("shop.esewa.urlopen", side_effect=lambda *a, **kw: self.status(order)) as check:
            first = self.client.get(url, {"data": self.signed_data(order)})
            second = self.client.get(url, {"data": self.signed_data(order)})
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.payment_status, "paid")
        self.assertEqual(order.esewa_ref_id, "REF123")
        self.assertEqual(self.variant.stock, 3)
        self.assertEqual(LoyaltyProgress.objects.get(phone=order.phone).purchase_count, 2)
        self.assertEqual(check.call_count, 1)
        self.assertContains(self.client.get(reverse("esewa_result", args=[order.esewa_transaction_uuid])),
                            "verified with eSewa")
        self.assertEqual(self.client.session.get("cart"), {})

    def test_pending_attempt_blocks_duplicate_checkout_and_old_result_keeps_new_cart(self):
        _, order = self.place()
        duplicate = self.client.post(reverse("checkout"), {
            "customer_name": "Buyer", "phone": "9800000000", "delivery_address": "Test",
            "delivery_zone": "inside", "payment_method": "manual"})
        self.assertRedirects(duplicate, reverse("esewa_result", args=[order.esewa_transaction_uuid]))
        self.assertEqual(Order.objects.count(), 1)
        with patch("shop.esewa.urlopen", return_value=self.status(order)):
            self.client.get(reverse("esewa_success", args=[order.esewa_transaction_uuid]),
                            {"data": self.signed_data(order)})
        session = self.client.session
        session["cart"][self.variant.pk]["quantity"] = 3
        session.save()
        self.client.get(reverse("esewa_result", args=[order.esewa_transaction_uuid]))
        self.assertEqual(self.client.session["cart"][self.variant.pk]["quantity"], 3)

    def test_changed_cart_rechecks_and_releases_expired_attempt_before_checkout(self):
        _, order = self.place()
        session = self.client.session
        session["cart"][self.variant.pk]["quantity"] = 3
        session.save()
        with patch("shop.esewa.urlopen", return_value=self.status(order, status="NOT_FOUND")):
            response = self.client.get(reverse("checkout"))
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "failed")
        self.assertEqual(order.order_status, "cancelled")
        self.assertEqual(order.esewa_status, "not_found")
        self.assertNotIn("pending_esewa_transaction_uuid", self.client.session)
        self.assertEqual(self.client.session["cart"][self.variant.pk]["quantity"], 3)

    def test_result_can_safely_recheck_and_return_to_checkout(self):
        _, order = self.place()
        result_url = reverse("esewa_result", args=[order.esewa_transaction_uuid])
        self.assertContains(self.client.get(result_url), "Check and return to checkout")
        with patch("shop.esewa.urlopen", return_value=self.status(order, status="NOT_FOUND")):
            response = self.client.post(reverse("esewa_return_to_checkout", args=[order.esewa_transaction_uuid]))
        self.assertRedirects(response, reverse("checkout"))
        order.refresh_from_db()
        self.assertEqual((order.payment_status, order.order_status), ("failed", "cancelled"))
        self.assertNotIn("pending_esewa_transaction_uuid", self.client.session)

    def test_return_to_checkout_keeps_active_pending_attempt_locked(self):
        _, order = self.place()
        with patch("shop.esewa.urlopen", return_value=self.status(order, status="PENDING")):
            response = self.client.post(reverse("esewa_return_to_checkout", args=[order.esewa_transaction_uuid]))
        self.assertRedirects(response, reverse("esewa_result", args=[order.esewa_transaction_uuid]))
        order.refresh_from_db()
        self.assertEqual((order.payment_status, order.order_status, order.esewa_status),
                         ("pending", "pending", "pending"))
        self.assertEqual(self.client.session["pending_esewa_transaction_uuid"], order.esewa_transaction_uuid)

    def test_tampered_or_mismatched_signed_returns_never_settle(self):
        _, order = self.place()
        url = reverse("esewa_success", args=[order.esewa_transaction_uuid])
        invalid = self.signed_data(order)[:-2] + "AA"
        with patch("shop.esewa.urlopen") as check:
            for data in (invalid, self.signed_data(order, total_amount="2501.0"),
                         self.signed_data(order, product_code="OTHER"),
                         self.signed_data(order, transaction_uuid="different")):
                self.client.get(url, {"data": data})
            check.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "pending")
        self.assertEqual(order.esewa_status, "uncertain")
        self.assertEqual(self.variant.stock, 5)

    def test_numeric_response_amount_preserves_exact_signed_text(self):
        _, order = self.place()
        message = (f"transaction_code=REF123,status=COMPLETE,total_amount=2500.00,"
                   f"transaction_uuid={order.esewa_transaction_uuid},product_code=EPAYTEST,"
                   f"signed_field_names={esewa.RESPONSE_FIELDS}")
        encoded = base64.b64encode((
            '{"transaction_code":"REF123","status":"COMPLETE","total_amount":2500.00,'
            f'"transaction_uuid":"{order.esewa_transaction_uuid}","product_code":"EPAYTEST",'
            f'"signed_field_names":"{esewa.RESPONSE_FIELDS}","signature":"{esewa.sign(message)}"}}'
        ).encode()).decode()
        self.assertEqual(esewa.verify_return_data(encoded, order)["total_amount"], "2500.00")

    def test_status_mismatch_and_timeout_stay_pending(self):
        _, order = self.place()
        url = reverse("esewa_success", args=[order.esewa_transaction_uuid])
        for mismatch in ({"total_amount": 1.0}, {"transaction_uuid": "different"},
                         {"product_code": "OTHER"}):
            with patch("shop.esewa.urlopen", return_value=self.status(order, **mismatch)):
                self.client.get(url, {"data": self.signed_data(order)})
        order.refresh_from_db()
        self.assertEqual(order.esewa_status, "uncertain")
        self.assertEqual(order.payment_status, "pending")
        with patch("shop.esewa.urlopen", side_effect=TimeoutError):
            self.client.post(reverse("esewa_check", args=[order.esewa_transaction_uuid]))
        self.assertEqual(Order.objects.get(pk=order.pk).payment_status, "pending")
        with patch("shop.esewa.urlopen", return_value=self.status(order, status="PENDING")):
            self.client.post(reverse("esewa_check", args=[order.esewa_transaction_uuid]))
        self.assertEqual(Order.objects.get(pk=order.pk).esewa_status, "pending")

    def test_missing_success_data_does_not_settle_until_status_check(self):
        _, order = self.place()
        with patch("shop.esewa.urlopen") as check:
            self.client.get(reverse("esewa_success", args=[order.esewa_transaction_uuid]))
            check.assert_not_called()
        self.assertEqual(Order.objects.get(pk=order.pk).payment_status, "pending")
        with patch("shop.esewa.urlopen", return_value=self.status(order)):
            self.client.post(reverse("esewa_check", args=[order.esewa_transaction_uuid]))
        self.assertEqual(Order.objects.get(pk=order.pk).payment_status, "paid")

    def test_unavailable_merchant_configuration_keeps_existing_attempt_uncertain(self):
        _, order = self.place()
        with override_settings(ESEWA_SECRET_KEY=""):
            self.assertEqual(self.client.get(reverse("esewa_failure", args=[order.esewa_transaction_uuid])).status_code, 302)
            self.assertEqual(self.client.post(reverse("esewa_check", args=[order.esewa_transaction_uuid])).status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "pending")
        self.assertEqual(order.esewa_status, "uncertain")

    def test_old_pending_order_can_be_reconciled_without_browser_callback(self):
        from datetime import timedelta
        from django.core.management import call_command
        from django.utils import timezone

        _, order = self.place()
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=6))
        with patch("shop.esewa.urlopen", return_value=self.status(order)):
            call_command("check_esewa_payments", stdout=io.StringIO())
        self.assertEqual(Order.objects.get(pk=order.pk).payment_status, "paid")

    def test_failure_status_cancels_once_and_releases_promo(self):
        promo = PromoCode.objects.create(code="SAVE10", influencer_name="Test", discount_percent=10)
        _, order = self.place(promo_code="SAVE10")
        self.assertEqual(promo.orders.count(), 1)
        with patch("shop.esewa.urlopen", side_effect=lambda *a, **kw: self.status(order, status="CANCELED")):
            url = reverse("esewa_failure", args=[order.esewa_transaction_uuid])
            self.client.get(url)
            self.client.get(url)
        order.refresh_from_db()
        promo.refresh_from_db()
        self.assertEqual(order.order_status, "cancelled")
        self.assertEqual(order.payment_status, "failed")
        self.assertEqual(promo.current_uses, 0)
        self.assertEqual(self.variant.stock, 5)
        self.assertContains(self.client.get(reverse("esewa_result", args=[order.esewa_transaction_uuid])),
                            'href="/checkout/">Return to checkout</a>')
        next_order = self.client.post(reverse("checkout"), {
            "customer_name": "Buyer", "phone": "9800000000", "delivery_address": "Test",
            "delivery_zone": "inside", "payment_method": "manual", "promo_code": "SAVE10"})
        self.assertEqual(next_order.status_code, 302)
        self.assertEqual(Order.objects.count(), 2)

    def test_server_complete_on_failure_url_can_settle(self):
        _, order = self.place()
        with patch("shop.esewa.urlopen", return_value=self.status(order)):
            self.client.get(reverse("esewa_failure", args=[order.esewa_transaction_uuid]))
        self.assertEqual(Order.objects.get(pk=order.pk).payment_status, "paid")

    def test_manual_admin_transitions_cannot_bypass_verification(self):
        _, order = self.place()
        with self.assertRaises(InvalidOrderTransition):
            confirm_order_paid(order.pk)
        with self.assertRaises(InvalidOrderTransition):
            cancel_pending_order(order.pk)
        self.assertEqual(Order.objects.get(pk=order.pk).payment_status, "pending")

    def test_complete_status_with_stock_shortage_needs_review(self):
        _, order = self.place()
        self.variant.stock = 0
        self.variant.save(update_fields=["stock"])
        with patch("shop.esewa.urlopen", return_value=self.status(order)):
            self.client.get(reverse("esewa_success", args=[order.esewa_transaction_uuid]),
                            {"data": self.signed_data(order)})
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "pending")
        self.assertEqual(order.esewa_status, "needs_review")

    def test_signed_reference_mismatch_needs_review(self):
        _, order = self.place()
        with patch("shop.esewa.urlopen", return_value=self.status(order, ref_id="OTHER")):
            self.client.get(reverse("esewa_success", args=[order.esewa_transaction_uuid]),
                            {"data": self.signed_data(order)})
        self.assertEqual(Order.objects.get(pk=order.pk).esewa_status, "needs_review")
        self.assertEqual(Order.objects.get(pk=order.pk).payment_status, "pending")

    @override_settings(ESEWA_SECRET_KEY="")
    def test_missing_secret_disables_esewa_and_preserves_manual_checkout(self):
        self.assertNotContains(self.client.get(reverse("checkout")), "eSewa UAT</label>")
        response = self.client.post(reverse("checkout"), {
            "customer_name": "Buyer", "phone": "9800000000", "delivery_address": "Test",
            "delivery_zone": "inside", "payment_method": "esewa"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)
        manual = self.client.post(reverse("checkout"), {
            "customer_name": "Buyer", "phone": "9800000000", "delivery_address": "Test",
            "delivery_zone": "inside"})
        self.assertEqual(manual.status_code, 302)
        self.assertEqual(Order.objects.get().payment_method, "manual")
