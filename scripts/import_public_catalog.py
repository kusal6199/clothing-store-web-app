"""Import public store content from the current Prisma database.

Reads the source PostgreSQL database in read-only mode. Imports catalog,
homepage, settings, and approved reviews into the Django database. Customer
orders, messages, visitor logs, payment records, and admin credentials are
intentionally excluded from this parallel development copy.
"""
import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.db import transaction
from psycopg.rows import dict_row
from shop.models import (Category, Collection, HeroSlide, HomepageSection, Product,
                         ProductVariant, PromoBanner, Review, Setting, Tag)
from source_inventory import connect


def rows(cursor, table):
    cursor.execute('SELECT * FROM "' + table + '"')
    return cursor.fetchall()


def parsed(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return fallback


def val(row, key, default=""):
    return row.get(key) if row.get(key) is not None else default


def import_data(cursor):
    for row in rows(cursor, "Category"):
        Category.objects.update_or_create(id=row["id"], defaults=dict(name=row["name"], slug=row["slug"],
            description=val(row, "description"), image=val(row, "image"), order=row["order"], visible=row["visible"]))
    for row in rows(cursor, "Collection"):
        Collection.objects.update_or_create(id=row["id"], defaults=dict(name=row["name"], slug=row["slug"],
            description=val(row, "description"), image=val(row, "image"), order=row["order"], visible=row["visible"]))
    for row in rows(cursor, "Tag"):
        Tag.objects.update_or_create(id=row["id"], defaults=dict(name=row["name"], slug=row["slug"]))
    for row in rows(cursor, "Product"):
        Product.objects.update_or_create(id=row["id"], defaults=dict(
            name=row["name"], slug=row["slug"], sku=row["sku"], category_id=row["categoryId"],
            description=val(row, "description"), price=Decimal(str(row["price"])),
            discount_price=Decimal(str(row["discountPrice"])) if row["discountPrice"] is not None else None,
            images=parsed(row["images"], []), gallery_images=parsed(row["galleryImages"], []),
            colors=parsed(row["colors"], []), material=val(row, "material"),
            care_instructions=val(row, "careInstructions"), featured=row["featured"],
            best_seller=row["bestSeller"], new_arrival=row["newArrival"], visibility=row["visibility"]),
        )
    for row in rows(cursor, "ProductVariant"):
        ProductVariant.objects.update_or_create(id=row["id"], defaults=dict(
            product_id=row["productId"], size=row["size"], color=row["color"],
            stock=row["stock"], additional_price=Decimal(str(row["additionalPrice"]))))
    for row in rows(cursor, "ProductTag"):
        Product.objects.get(pk=row["productId"]).tags.add(row["tagId"])
    for row in rows(cursor, "CollectionProduct"):
        Product.objects.get(pk=row["productId"]).collections.add(row["collectionId"])
    for row in rows(cursor, "HeroSlide"):
        HeroSlide.objects.update_or_create(id=row["id"], defaults=dict(
            title=row["title"], subtitle=val(row, "subtitle"), image=row["image"],
            link=val(row, "link"), button_text=val(row, "buttonText"), order=row["order"], visible=row["visible"]))
    for row in rows(cursor, "HomepageSection"):
        HomepageSection.objects.update_or_create(id=row["id"], defaults=dict(
            key=row["key"], title=row["title"], subtitle=val(row, "subtitle"),
            visible=row["visible"], order=row["order"], content=parsed(row["content"], {})))
    for row in rows(cursor, "PromoBanner"):
        PromoBanner.objects.update_or_create(id=row["id"], defaults=dict(
            text=row["text"], link=val(row, "link"), visible=row["visible"], order=row["order"]))
    for row in rows(cursor, "Setting"):
        Setting.objects.update_or_create(key=row["key"], defaults={"value": row["value"]})
    for row in rows(cursor, "Review"):
        if row["approved"] and row["comment"]:
            Review.objects.update_or_create(id=row["id"], defaults=dict(
                product_id=row["productId"], name=row["name"], rating=row["rating"],
                comment=row["comment"], avatar=val(row, "avatar"), approved=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source_env", help="Path to the existing Next.js .env file")
    args = parser.parse_args()
    with connect(args.source_env) as source, source.cursor(row_factory=dict_row) as cursor:
        with transaction.atomic():
            import_data(cursor)
    print("Imported public catalog and homepage data. Customer and payment data were excluded.")
