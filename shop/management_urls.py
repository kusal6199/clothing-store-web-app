from django.urls import path

from . import management_views as views

app_name = "management"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("products/", views.products, name="products"),
    path("products/add/", views.product_edit, name="product_add"),
    path("products/<str:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<str:pk>/delete/", views.product_delete, name="product_delete"),
    path("categories/", views.categories, name="categories"),
    path("categories/<str:kind>/add/", views.taxonomy_edit, name="taxonomy_add"),
    path("categories/<str:kind>/<str:pk>/edit/", views.taxonomy_edit, name="taxonomy_edit"),
    path("categories/<str:kind>/<str:pk>/delete/", views.taxonomy_delete, name="taxonomy_delete"),
    path("homepage/", views.homepage, name="homepage"),
    path("homepage/<str:kind>/add/", views.homepage_edit, name="homepage_add"),
    path("homepage/<str:kind>/<str:pk>/edit/", views.homepage_edit, name="homepage_edit"),
    path("homepage/<str:kind>/<str:pk>/toggle/", views.homepage_toggle, name="homepage_toggle"),
    path("homepage/<str:kind>/<str:pk>/delete/", views.homepage_delete, name="homepage_delete"),
    path("orders/", views.orders, name="orders"),
    path("orders/export/", views.orders_export, name="orders_export"),
    path("orders/<str:pk>/", views.order_detail, name="order_detail"),
    path("orders/<str:pk>/status/", views.order_status, name="order_status"),
    path("orders/<str:pk>/confirm-payment/", views.order_confirm_payment, name="order_confirm_payment"),
    path("orders/<str:pk>/cancel/", views.order_cancel, name="order_cancel"),
    path("orders/<str:pk>/check-esewa/", views.order_check_esewa, name="order_check_esewa"),
    path("orders/<str:pk>/fulfil-reward/", views.order_fulfil_reward, name="order_fulfil_reward"),
    path("loyalty/", views.loyalty, name="loyalty"),
    path("promo-codes/", views.promo_codes, name="promo_codes"),
    path("promo-codes/add/", views.promo_edit, name="promo_add"),
    path("promo-codes/<str:pk>/edit/", views.promo_edit, name="promo_edit"),
    path("promo-codes/<str:pk>/toggle/", views.promo_toggle, name="promo_toggle"),
    path("promo-codes/<str:pk>/delete/", views.promo_delete, name="promo_delete"),
    path("messages/", views.message_list, name="messages"),
    path("messages/<str:pk>/toggle/", views.message_toggle, name="message_toggle"),
    path("messages/<str:pk>/delete/", views.message_delete, name="message_delete"),
    path("settings/", views.settings_view, name="settings"),
]
