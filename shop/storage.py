"""Server-side product media upload to Supabase Storage or local development media."""
import mimetypes
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "AVIF": ".avif"}


def save_image(upload, folder="products"):
    if upload.size > 8 * 1024 * 1024:
        raise ValidationError("Images must be under 8 MB.")
    try:
        image = Image.open(upload)
        image.verify()
        file_format = image.format
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError("Upload a valid JPEG, PNG, WebP, or AVIF image.") from exc
    if file_format not in ALLOWED_FORMATS:
        raise ValidationError("Upload a JPEG, PNG, WebP, or AVIF image.")
    upload.seek(0)
    data = upload.read()
    filename = f"{folder}/{uuid4().hex}{ALLOWED_FORMATS[file_format]}"
    supabase_url = getattr(settings, "SUPABASE_URL", "").rstrip("/")
    service_key = getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")
    bucket = getattr(settings, "SUPABASE_STORAGE_BUCKET", "store-media")
    if supabase_url and service_key:
        path = quote(filename, safe="/")
        endpoint = f"{supabase_url}/storage/v1/object/{quote(bucket)}/{path}"
        request = Request(endpoint, data=data, method="POST", headers={
            "apikey": service_key, "Authorization": f"Bearer {service_key}",
            "Content-Type": Image.MIME.get(file_format, mimetypes.guess_type(filename)[0] or "application/octet-stream"),
            "Cache-Control": "max-age=3600",
        })
        try:
            with urlopen(request, timeout=30) as response:
                if response.status not in (200, 201):
                    raise ValidationError("Storage upload failed.")
        except HTTPError as exc:
            raise ValidationError(f"Storage upload failed ({exc.code}).") from exc
        return f"{supabase_url}/storage/v1/object/public/{quote(bucket)}/{path}"
    saved = default_storage.save(filename, ContentFile(data))
    return settings.MEDIA_URL.rstrip("/") + "/" + saved
