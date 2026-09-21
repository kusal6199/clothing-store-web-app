from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", include("shop.management_urls")),
    path("internal-admin/", admin.site.urls),
    path("dashboard/", RedirectView.as_view(pattern_name="management:dashboard", permanent=False), name="dashboard"),
    path("dashboard/settings/", RedirectView.as_view(pattern_name="management:settings", permanent=False), name="dashboard_settings"),
    path("", include("shop.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
