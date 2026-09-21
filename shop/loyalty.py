"""Customer-facing loyalty catalog and signed reward selection links."""
from django.core import signing
from django.urls import reverse

from .models import Product, ProductVariant

REWARD_TOKEN_SALT = "shop.customer-milestone-reward"
REWARD_TOKEN_MAX_AGE = 60 * 60 * 24 * 30


def reward_selection_token(order):
    return signing.dumps({"order_id": order.pk}, salt=REWARD_TOKEN_SALT, compress=True)


def reward_selection_path(order):
    return reverse("reward_selection", args=[reward_selection_token(order)])


def read_reward_selection_token(token, *, max_age=REWARD_TOKEN_MAX_AGE):
    payload = signing.loads(token, salt=REWARD_TOKEN_SALT, max_age=max_age)
    order_id = payload.get("order_id") if isinstance(payload, dict) else None
    if not isinstance(order_id, str) or not order_id:
        raise signing.BadSignature("Invalid reward selection token")
    return order_id


def reward_catalog(category_id):
    """Return visible products and their distinct in-stock variants for one category."""
    products = Product.objects.filter(
        category_id=category_id, visibility=True, variants__stock__gt=0,
    ).distinct().order_by("name", "pk")
    variants = ProductVariant.objects.filter(
        product__category_id=category_id, product__visibility=True, stock__gt=0,
    ).select_related("product").order_by("product__name", "size", "color", "pk")
    by_product = {}
    for variant in variants:
        by_product.setdefault(variant.product_id, []).append({
            "id": variant.pk,
            "size": variant.size,
            "color": variant.color or None,
            "stock": variant.stock,
        })
    return [{
        "id": product.pk,
        "name": product.name,
        "image": product.primary_image,
        "variants": by_product.get(product.pk, []),
    } for product in products if by_product.get(product.pk)]
