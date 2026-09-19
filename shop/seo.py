"""Absolute store URLs and safe JSON-LD for public search metadata."""
import json
from urllib.parse import urlsplit

from django.conf import settings
from django.utils.safestring import mark_safe


def site_url(path="/"):
    return settings.SITE_URL.rstrip("/") + "/" + path.lstrip("/")


def asset_url(value):
    if not value:
        return ""
    if urlsplit(value).scheme in {"http", "https"}:
        return value
    return site_url(value)


def json_ld(data):
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return mark_safe(payload)
