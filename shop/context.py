from .models import Category, Setting
from .seo import asset_url, site_url


def site_context(request):
    settings = dict(Setting.objects.values_list("key", "value"))
    return {
        "site_settings": settings,
        "nav_categories": Category.objects.filter(visible=True)[:8],
        "cart_count": sum(int(item.get("quantity", 0)) for item in request.session.get("cart", {}).values()),
        "canonical_url": site_url(request.path),
        "default_og_image": asset_url("/static/branding/logo.jpg"),
    }
