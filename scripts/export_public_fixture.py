"""Export only public catalog content and its local images for fresh clones.

Run against the isolated Django development database. Operational records,
reviews, payment settings, and credentials are deliberately never serialized.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.conf import settings
from django.core import serializers
from shop.models import Category, Collection, HeroSlide, HomepageSection, Product, ProductVariant, PromoBanner, Setting, Tag

PUBLIC_SETTINGS = {
    "address", "currency", "delivery_inside_valley", "delivery_outside_valley",
    "email", "facebook", "footer_about", "footer_copyright", "instagram",
    "newsletter_subtitle", "newsletter_title", "phone", "site_name", "site_tagline",
}
MODELS = (Category, Collection, Tag, Product, ProductVariant, HeroSlide, HomepageSection, PromoBanner)
UPLOAD_URL = re.compile(r"/uploads/([A-Za-z0-9_./-]+)")


def public_url(match):
    relative = Path(match.group(1))
    source = (Path(settings.MEDIA_ROOT) / relative).resolve()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if not source.is_relative_to(media_root) or not source.is_file():
        raise FileNotFoundError(f"Missing public catalog image: {relative}")
    target = ROOT / "static" / "catalog" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return "/static/catalog/" + relative.as_posix()


def rewrite(value):
    if isinstance(value, dict):
        return {key: rewrite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite(item) for item in value]
    if isinstance(value, str):
        return UPLOAD_URL.sub(public_url, value)
    return value


def main():
    objects = [obj for model in MODELS for obj in model.objects.order_by("pk")]
    objects.extend(Setting.objects.filter(key__in=PUBLIC_SETTINGS).order_by("pk"))
    data = rewrite(json.loads(serializers.serialize("json", objects)))
    fixture = ROOT / "fixtures" / "public_catalog.json"
    fixture.parent.mkdir(exist_ok=True)
    fixture.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"Exported {len(data)} public objects to {fixture.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
