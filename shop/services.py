"""Checkout and paid-order transitions use server prices and database locks."""
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .models import LoyaltyProgress, Order, OrderItem, ProductVariant, PromoCode, Setting

MONEY = Decimal("0.01")


class InsufficientStock(Exception):
    pass


class InvalidPromo(Exception):
    pass


class InvalidOrderTransition(Exception):
    pass


def money(value):
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def store_settings():
    return dict(Setting.objects.values_list("key", "value"))


def cart_rows(cart):
    variant_ids = [key for key in cart if key]
    variants = ProductVariant.objects.select_related("product", "product__category").filter(pk__in=variant_ids, product__visibility=True)
    by_id = {variant.pk: variant for variant in variants}
    rows = []
    for variant_id, item in cart.items():
        variant = by_id.get(variant_id)
        if not variant:
            continue
        quantity = max(1, min(int(item.get("quantity", 1)), 99))
        unit_price = variant.product.current_price + variant.additional_price
        rows.append({
            "variant": variant,
            "product": variant.product,
            "quantity": quantity,
            "unit_price": unit_price,
            "line_total": money(unit_price * quantity),
        })
    return rows


def promo_for(code, subtotal, lock=False):
    query = PromoCode.objects
    if lock:
        query = query.select_for_update()
    promo = query.filter(code=code.strip().upper()).first()
    if not promo or not promo.active or (promo.expires_at and promo.expires_at <= timezone.now()):
        raise InvalidPromo("This promo code is unavailable.")
    if promo.max_uses is not None and promo.current_uses >= promo.max_uses:
        raise InvalidPromo("This promo code has reached its usage limit.")
    if not Decimal("0") < promo.discount_percent <= Decimal("100"):
        raise InvalidPromo("This promo code has an invalid discount.")
    return promo, money(subtotal * promo.discount_percent / Decimal("100"))


def create_order(form_data, cart):
    with transaction.atomic():
        rows = cart_rows(cart)
        if not rows:
            raise InsufficientStock("Your cart is empty or its products are unavailable.")
        reward_variant = None
        reward_progress = None
        reward_id = form_data.get("reward_variant_id", "").strip()
        if reward_id:
            reward_variant = ProductVariant.objects.select_related("product").filter(
                pk=reward_id, product__visibility=True, stock__gt=0).first()
            purchased_categories = {row["product"].category_id for row in rows}
            if not reward_variant or reward_variant.product.category_id not in purchased_categories:
                raise InsufficientStock("Choose a reward from a category in your bag.")
            reward_progress = LoyaltyProgress.objects.select_for_update().filter(
                phone=form_data["phone"].strip(), category_id=reward_variant.product.category_id).first()
            pending = Order.objects.filter(phone=form_data["phone"].strip(),
                reward_category_id=reward_variant.product.category_id, payment_status="pending").exclude(
                order_status="cancelled").count()
            available = (reward_progress.purchase_count // 10 - reward_progress.free_items_redeemed - pending) if reward_progress else 0
            if available < 1:
                raise InsufficientStock("This loyalty reward is no longer available.")
        required = Counter()
        for row in rows:
            required[row["variant"].pk] += row["quantity"]
        if reward_variant:
            required[reward_variant.pk] += 1
        locked = {variant.pk: variant for variant in ProductVariant.objects.select_for_update().filter(pk__in=required)}
        for variant_id, quantity in required.items():
            variant = locked.get(variant_id)
            if not variant or variant.stock < quantity:
                raise InsufficientStock("One or more selected items are no longer available in that quantity.")
        subtotal = sum((row["line_total"] for row in rows), Decimal("0.00"))
        settings = store_settings()
        zone = form_data["delivery_zone"]
        charge = money(settings.get("delivery_outside_valley" if zone == "outside" else "delivery_inside_valley", "200" if zone == "outside" else "100"))
        promo = None
        discount = Decimal("0.00")
        if form_data.get("promo_code", "").strip():
            promo, discount = promo_for(form_data["promo_code"], subtotal, lock=True)
            PromoCode.objects.filter(pk=promo.pk).update(current_uses=F("current_uses") + 1)
        order = Order.objects.create(
            order_number=f"CS-{timezone.now():%y%m%d}-{uuid4().hex[:8].upper()}",
            customer_name=form_data["customer_name"], phone=form_data["phone"].strip(),
            email=form_data.get("email", ""), delivery_address=form_data["delivery_address"],
            city=form_data.get("city", ""), additional_notes=form_data.get("additional_notes", ""),
            delivery_zone=zone, delivery_charge=charge, subtotal=subtotal,
            discount_amount=discount, total=subtotal - discount + charge,
            promo_code=promo, reward_category_id=reward_variant.product.category_id if reward_variant else None,
            payment_method=form_data.get("payment_method", "manual"),
            esewa_transaction_uuid=uuid4().hex if form_data.get("payment_method") == "esewa" else None,
            esewa_product_code=form_data.get("esewa_product_code", "") if form_data.get("payment_method") == "esewa" else "",
            esewa_status="initiated" if form_data.get("payment_method") == "esewa" else "",
        )
        OrderItem.objects.bulk_create([
            OrderItem(order=order, product=row["product"], product_name=row["product"].name,
                      product_image=row["product"].primary_image, size=row["variant"].size,
                      color=row["variant"].color or "", price=row["unit_price"], quantity=row["quantity"])
            for row in rows
        ] + ([OrderItem(order=order, product=reward_variant.product,
            product_name=reward_variant.product.name, product_image=reward_variant.product.primary_image,
            size=reward_variant.size, color=reward_variant.color or "", price=Decimal("0.00"),
            quantity=1, is_reward_item=True)] if reward_variant else []))
        return order


def confirm_order_paid(order_id, *, verified_esewa=False):
    """Idempotently mark a payment paid, deduct stock, and count loyalty."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.payment_method == "esewa" and not verified_esewa:
            raise InvalidOrderTransition("eSewa orders require server-side verification.")
        if order.order_status == "cancelled" or order.payment_status == "refunded":
            raise InvalidOrderTransition("Cancelled or refunded orders cannot be marked paid.")
        if order.payment_status == "paid":
            return order
        items = list(order.items.select_related("product", "product__category"))
        requirements = Counter((item.product_id, item.size, item.color or "", item.quantity) for item in items if item.product_id)
        # Merge duplicate lines before decrementing.
        merged = Counter()
        for (product_id, size, color, quantity), count in requirements.items():
            merged[(product_id, size, color)] += quantity * count
        for (product_id, size, color), quantity in merged.items():
            updated = ProductVariant.objects.filter(product_id=product_id, size=size, color=color or None, stock__gte=quantity).update(stock=F("stock") - quantity)
            if not updated:
                raise InsufficientStock("Insufficient stock to confirm this order.")
        purchased = Counter()
        for item in items:
            if item.product and item.product.category_id and not item.is_reward_item:
                purchased[item.product.category_id] += item.quantity
        for category_id, quantity in purchased.items():
            progress, _ = LoyaltyProgress.objects.select_for_update().get_or_create(phone=order.phone, category_id=category_id)
            LoyaltyProgress.objects.filter(pk=progress.pk).update(purchase_count=F("purchase_count") + quantity)
        if order.reward_category_id:
            progress = LoyaltyProgress.objects.select_for_update().filter(
                phone=order.phone, category_id=order.reward_category_id).first()
            if not progress or progress.purchase_count // 10 - progress.free_items_redeemed < 1:
                raise InsufficientStock("Loyalty reward is no longer available.")
            LoyaltyProgress.objects.filter(pk=progress.pk).update(free_items_redeemed=F("free_items_redeemed") + 1)
            order.reward_fulfilled = True
        order.payment_status = "paid"
        if order.order_status == "pending":
            order.order_status = "confirmed"
        order.save(update_fields=["payment_status", "order_status", "reward_fulfilled", "updated_at"])
        return order


def cancel_pending_order(order_id, *, verified_esewa_failure=False):
    """Cancel an unpaid test order and release its promo/reward reservation."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.payment_method == "esewa" and not verified_esewa_failure:
            raise InvalidOrderTransition("Check eSewa's transaction status before cancelling this order.")
        if order.order_status == "cancelled":
            return order
        if order.payment_status in {"paid", "refunded"}:
            raise InvalidOrderTransition("Paid or refunded orders require a separate refund workflow.")
        if order.promo_code_id:
            PromoCode.objects.filter(pk=order.promo_code_id, current_uses__gt=0).update(current_uses=F("current_uses") - 1)
        order.order_status = "cancelled"
        order.save(update_fields=["order_status", "updated_at"])
        return order
