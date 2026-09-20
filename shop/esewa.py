"""eSewa ePay v2 UAT request signing and server-side settlement."""
import base64
import binascii
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.db import transaction

from .models import Order
from .services import InsufficientStock, InvalidOrderTransition, cancel_pending_order, confirm_order_paid


PAYMENT_URL = "https://rc-epay.esewa.com.np/api/epay/main/v2/form"
STATUS_URL = "https://rc.esewa.com.np/api/epay/transaction/status/"
REQUEST_FIELDS = "total_amount,transaction_uuid,product_code"
RESPONSE_FIELDS = "transaction_code,status,total_amount,transaction_uuid,product_code,signed_field_names"


class EsewaVerificationError(Exception):
    pass


def configured():
    return bool(settings.ESEWA_SECRET_KEY and settings.ESEWA_MERCHANT_CODE)


def amount(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result != result.quantize(Decimal("0.01")):
            raise InvalidOperation
        return result.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise EsewaVerificationError("Invalid eSewa amount") from None


def sign(message):
    if not configured():
        raise EsewaVerificationError("eSewa UAT is not configured")
    digest = hmac.new(settings.ESEWA_SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def payment_fields(order):
    if order.payment_method != "esewa" or not order.esewa_transaction_uuid or not order.esewa_product_code:
        raise EsewaVerificationError("This is not an eSewa order")
    if not configured() or order.esewa_product_code != settings.ESEWA_MERCHANT_CODE:
        raise EsewaVerificationError("eSewa merchant configuration changed")
    if order.payment_status != "pending" or order.order_status == "cancelled":
        raise EsewaVerificationError("This payment attempt is no longer pending")
    total = f"{order.total:.2f}"
    delivery = f"{order.delivery_charge:.2f}"
    product_amount = f"{order.total - order.delivery_charge:.2f}"
    message = f"total_amount={total},transaction_uuid={order.esewa_transaction_uuid},product_code={order.esewa_product_code}"
    base = settings.SITE_URL
    return {
        "amount": product_amount, "tax_amount": "0", "total_amount": total,
        "transaction_uuid": order.esewa_transaction_uuid, "product_code": order.esewa_product_code,
        "product_service_charge": "0", "product_delivery_charge": delivery,
        "success_url": f"{base}/checkout/esewa/success/{order.esewa_transaction_uuid}/",
        "failure_url": f"{base}/checkout/esewa/failure/{order.esewa_transaction_uuid}/",
        "signed_field_names": REQUEST_FIELDS, "signature": sign(message),
    }


def verify_return_data(encoded, order):
    if not encoded or len(encoded) > 8192:
        raise EsewaVerificationError("Missing or oversized eSewa response")
    try:
        # Preserve the text of JSON numbers: 2500.00 and 2500.0 have the same
        # value but produce different HMAC messages.
        payload = json.loads(base64.b64decode(encoded, validate=True),
                             parse_float=str, parse_int=str)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise EsewaVerificationError("Invalid eSewa response") from None
    if not isinstance(payload, dict) or payload.get("signed_field_names") != RESPONSE_FIELDS:
        raise EsewaVerificationError("Unexpected eSewa signed fields")
    if any(isinstance(payload.get(key), bool) or not isinstance(payload.get(key), (str, int, float)) for key in RESPONSE_FIELDS.split(",")):
        raise EsewaVerificationError("Incomplete eSewa response")
    message = ",".join(f"{key}={payload[key]}" for key in RESPONSE_FIELDS.split(","))
    signature = payload.get("signature")
    if not isinstance(signature, str) or not hmac.compare_digest(sign(message), signature):
        raise EsewaVerificationError("Invalid eSewa response signature")
    if (payload["transaction_uuid"] != order.esewa_transaction_uuid
            or payload["product_code"] != order.esewa_product_code
            or amount(payload["total_amount"]) != order.total):
        raise EsewaVerificationError("eSewa response does not match this order")
    return payload


def status_response(order):
    query = urlencode({"product_code": order.esewa_product_code,
                       "total_amount": f"{order.total:.2f}",
                       "transaction_uuid": order.esewa_transaction_uuid})
    try:
        with urlopen(f"{STATUS_URL}?{query}", timeout=8) as response:
            if response.status != 200:
                raise EsewaVerificationError("eSewa status service returned an error")
            result = json.load(response, parse_float=Decimal, parse_int=Decimal)
    except (OSError, TimeoutError, ValueError, EsewaVerificationError):
        raise EsewaVerificationError("eSewa status could not be checked") from None
    if not isinstance(result, dict):
        raise EsewaVerificationError("Invalid eSewa status response")
    if (result.get("transaction_uuid") != order.esewa_transaction_uuid
            or result.get("product_code") != order.esewa_product_code
            or amount(result.get("total_amount")) != order.total):
        raise EsewaVerificationError("eSewa status does not match this order")
    return result


def set_state(order_id, state):
    Order.objects.filter(pk=order_id, payment_status="pending").exclude(order_status="cancelled").update(esewa_status=state)


def reconcile(order, *, signed_return=None):
    """Only the UAT status endpoint can authorize settlement or final cancellation."""
    if order.payment_method != "esewa" or not configured():
        raise EsewaVerificationError("eSewa UAT is not configured for this order")
    if order.payment_status == "paid":
        return "paid"
    if order.order_status == "cancelled":
        return "cancelled"
    try:
        result = status_response(order)
    except EsewaVerificationError:
        set_state(order.pk, "uncertain")
        return "uncertain"
    status = result.get("status")
    if status == "COMPLETE":
        reference = result.get("ref_id")
        if not isinstance(reference, str) or not reference or len(reference) > 100:
            set_state(order.pk, "needs_review")
            return "needs_review"
        if signed_return and signed_return.get("transaction_code") != reference:
            set_state(order.pk, "needs_review")
            return "needs_review"
        try:
            with transaction.atomic():
                locked = Order.objects.select_for_update().get(pk=order.pk)
                if (locked.esewa_transaction_uuid != order.esewa_transaction_uuid
                        or locked.esewa_product_code != result["product_code"]
                        or locked.total != amount(result["total_amount"])):
                    raise EsewaVerificationError("Stored eSewa order changed")
                confirmed = confirm_order_paid(locked.pk, verified_esewa=True)
                confirmed.esewa_status = "complete"
                confirmed.esewa_ref_id = reference
                confirmed.save(update_fields=["esewa_status", "esewa_ref_id", "updated_at"])
        except (InsufficientStock, InvalidOrderTransition, EsewaVerificationError):
            set_state(order.pk, "needs_review")
            return "needs_review"
        return "paid"
    if status in {"CANCELED", "NOT_FOUND"}:
        try:
            cancel_pending_order(order.pk, verified_esewa_failure=True)
        except InvalidOrderTransition:
            return "needs_review"
        Order.objects.filter(pk=order.pk, order_status="cancelled").update(
            payment_status="failed", esewa_status=status.lower())
        return "cancelled"
    set_state(order.pk, "pending" if status == "PENDING" else "uncertain")
    return "pending" if status == "PENDING" else "uncertain"
