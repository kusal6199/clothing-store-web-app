from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("catalog/", views.catalog, name="catalog"),
    path("products/<slug:slug>/", views.product_detail, name="product_detail"),
    path("cart/", views.cart, name="cart"),
    path("cart/add/", views.cart_add, name="cart_add"),
    path("cart/update/", views.cart_update, name="cart_update"),
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/esewa/success/<str:transaction_uuid>/", views.esewa_return, {"outcome": "success"}, name="esewa_success"),
    path("checkout/esewa/failure/<str:transaction_uuid>/", views.esewa_return, {"outcome": "failure"}, name="esewa_failure"),
    path("checkout/esewa/result/<str:transaction_uuid>/", views.esewa_result, name="esewa_result"),
    path("checkout/esewa/check/<str:transaction_uuid>/", views.esewa_check, name="esewa_check"),
    path("checkout/success/<str:order_number>/", views.order_success, name="order_success"),
    path("contact/", views.contact, name="contact"),
    path("newsletter/subscribe/", views.newsletter_subscribe, name="newsletter_subscribe"),
    path("promo/validate/", views.promo_validate, name="promo_validate"),
    path("loyalty/options/", views.loyalty_options, name="loyalty_options"),
    path("review/<str:token>/", views.review_by_token, name="review_by_token"),
    path("robots.txt", views.robots, name="robots"),
    path("sitemap.xml", views.sitemap, name="sitemap"),
]
