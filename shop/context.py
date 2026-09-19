from .models import Category, Setting


def site_context(request):
    settings = dict(Setting.objects.values_list("key", "value"))
    return {
        "site_settings": settings,
        "nav_categories": Category.objects.filter(visible=True)[:8],
        "cart_count": sum(int(item.get("quantity", 0)) for item in request.session.get("cart", {}).values()),
    }
