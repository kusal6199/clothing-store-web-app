from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from shop import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/settings/", views.dashboard_settings, name="dashboard_settings"),
    path("", include("shop.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
