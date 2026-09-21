import re

from django.db import migrations


def normalize_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 13 and digits.startswith("977"):
        digits = digits[3:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def normalize_loyalty_data(apps, schema_editor):
    Order = apps.get_model("shop", "Order")
    LoyaltyProgress = apps.get_model("shop", "LoyaltyProgress")

    for order in Order.objects.all().only("pk", "phone").iterator():
        normalized = normalize_phone(order.phone)
        if normalized != order.phone:
            Order.objects.filter(pk=order.pk).update(phone=normalized)

    groups = {}
    for progress in LoyaltyProgress.objects.all().order_by("created_at", "pk"):
        key = (normalize_phone(progress.phone), progress.category_id)
        groups.setdefault(key, []).append(progress)
    for (phone, _category_id), rows in groups.items():
        primary, *duplicates = rows
        purchase_count = sum(row.purchase_count for row in rows)
        free_items_redeemed = sum(row.free_items_redeemed for row in rows)
        if duplicates:
            LoyaltyProgress.objects.filter(pk__in=[row.pk for row in duplicates]).delete()
        LoyaltyProgress.objects.filter(pk=primary.pk).update(
            phone=phone, purchase_count=purchase_count, free_items_redeemed=free_items_redeemed,
        )


class Migration(migrations.Migration):
    dependencies = [("shop", "0005_order_esewa_product_code_order_esewa_status_and_more")]

    operations = [migrations.RunPython(normalize_loyalty_data, migrations.RunPython.noop)]
