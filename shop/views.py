from decimal import Decimal
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from .forms import CheckoutForm, ContactForm, NewsletterForm, ReviewForm
from .models import (
    Category, Collection, HeroSlide, HomepageSection, Message, NewsletterSubscriber, Order,
    Product, ProductVariant, PromoBanner, Review, Tag, Visitor, LoyaltyProgress,
)
from .services import InsufficientStock, InvalidPromo, cart_rows, create_order, promo_for, store_settings
from .seo import asset_url, json_ld, site_url


def track(request):
    if request.method == "GET" and not request.user.is_staff:
        try:
            Visitor.objects.create(ip=request.META.get("REMOTE_ADDR") or None,
                                   user_agent=request.META.get("HTTP_USER_AGENT", "")[:2000], path=request.path[:500])
        except Exception:
            pass


def home(request):
    track(request)
    sections = {section.key: section for section in HomepageSection.objects.all()}
    settings = store_settings()
    store_schema = {
        "@context": "https://schema.org", "@type": "ClothingStore",
        "name": settings.get("site_name", "Clothing Shop"),
        "description": settings.get("site_tagline", "Premium clothing and accessories"),
        "url": site_url("/"),
        "telephone": settings.get("phone", ""),
        "email": settings.get("email", ""),
        "address": settings.get("address", ""),
        "sameAs": [settings[key] for key in ("instagram", "facebook") if settings.get(key)],
    }
    return render(request, "shop/home.html", {
        "seo_title": settings.get("site_name", "Clothing Shop") + " — Premium Clothing Store",
        "seo_json_ld": json_ld(store_schema),
        "hero_slides": HeroSlide.objects.filter(visible=True),
        "promo_banner": PromoBanner.objects.filter(visible=True).first(),
        "sections": sections,
        "categories": Category.objects.filter(visible=True),
        "home_collections": Collection.objects.filter(visible=True),
        "new_arrivals": Product.objects.filter(visibility=True, new_arrival=True).prefetch_related("variants")[:8],
        "featured": Product.objects.filter(visibility=True, featured=True).prefetch_related("variants")[:8],
        "best_sellers": Product.objects.filter(visibility=True, best_seller=True).prefetch_related("variants")[:8],
        "reviews": Review.objects.filter(approved=True).exclude(comment="")[:6],
    })


def catalog(request):
    track(request)
    products = Product.objects.filter(visibility=True).select_related("category").prefetch_related("variants")
    q = request.GET.get("q", "").strip()
    if q:
        products = products.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(material__icontains=q))
    if category := request.GET.get("category"):
        products = products.filter(category__slug=category)
    if collection := request.GET.get("collection"):
        products = products.filter(collections__slug=collection)
    if tag := request.GET.get("tag"):
        products = products.filter(tags__slug=tag)
    variant_filters = {}
    if size := request.GET.get("size"):
        variant_filters["variants__size"] = size
    if color := request.GET.get("color"):
        variant_filters["variants__color__iexact"] = color
    if variant_filters or request.GET.get("inStock") == "1":
        products = products.filter(variants__stock__gt=0, **variant_filters)
    flag = request.GET.get("filter")
    if flag == "featured":
        products = products.filter(featured=True)
    elif flag == "best-sellers":
        products = products.filter(best_seller=True)
    elif flag == "new-arrivals":
        products = products.filter(new_arrival=True)
    if low := request.GET.get("min"):
        try:
            floor = Decimal(low)
            products = products.filter(Q(discount_price__gte=floor) | Q(discount_price__isnull=True, price__gte=floor))
        except Exception:
            pass
    if high := request.GET.get("max"):
        try:
            ceiling = Decimal(high)
            products = products.filter(Q(discount_price__lte=ceiling) | Q(discount_price__isnull=True, price__lte=ceiling))
        except Exception:
            pass
    order = request.GET.get("sort", "newest")
    products = products.order_by({"price-asc": "price", "price-desc": "-price", "name-asc": "name"}.get(order, "-created_at")).distinct()
    page = Paginator(products, 24).get_page(request.GET.get("page"))
    pagination_params = request.GET.copy()
    pagination_params.pop("page", None)
    return render(request, "shop/catalog.html", {
        "seo_title": "Shop All — " + store_settings().get("site_name", "Clothing Shop"),
        "page": page, "categories": Category.objects.filter(visible=True),
        "collections": Collection.objects.filter(visible=True), "tags": Tag.objects.all(),
        "sizes": ProductVariant.objects.filter(stock__gt=0).values_list("size", flat=True).distinct().order_by("size"),
        "colors": ProductVariant.objects.filter(stock__gt=0).exclude(color__isnull=True).exclude(color="").values_list("color", flat=True).distinct().order_by("color"),
        "selected": request.GET,
        "active_filter": flag if flag in {"featured", "best-sellers", "new-arrivals"} else "",
        "pagination_query": pagination_params.urlencode(),
    })


def product_detail(request, slug):
    track(request)
    product = get_object_or_404(Product.objects.select_related("category").prefetch_related("variants", "tags"), slug=slug, visibility=True)
    related = Product.objects.filter(visibility=True, category=product.category).exclude(pk=product.pk)[:4]
    store_name = store_settings().get("site_name", "Clothing Shop")
    product_schema = {
        "@context": "https://schema.org", "@type": "Product",
        "name": product.name, "description": product.description,
        "sku": product.sku or product.id,
        "image": [asset_url(image) for image in [*product.images, *product.gallery_images]],
        "brand": {"@type": "Brand", "name": store_name},
        "offers": {"@type": "Offer", "url": site_url(request.path),
                   "price": str(product.current_price), "priceCurrency": "NPR",
                   "availability": "https://schema.org/InStock" if product.in_stock else "https://schema.org/OutOfStock"},
    }
    if product.category:
        product_schema["category"] = product.category.name
    return render(request, "shop/product.html", {"product": product, "related": related,
        "seo_title": f"{product.name} — {store_name}",
        "seo_description": product.description[:160] or f"Buy {product.name} at {store_name}.",
        "seo_image": asset_url(product.primary_image), "seo_type": "product",
        "seo_json_ld": json_ld(product_schema),
        "reviews": product.reviews.filter(approved=True).exclude(comment="")[:10]})


def cart(request):
    rows = cart_rows(request.session.get("cart", {}))
    return render(request, "shop/cart.html", {"rows": rows, "subtotal": sum((row["line_total"] for row in rows), Decimal("0.00"))})


@require_POST
def cart_add(request):
    variant = get_object_or_404(ProductVariant.objects.select_related("product"), pk=request.POST.get("variant_id"), product__visibility=True)
    try:
        quantity = max(1, min(int(request.POST.get("quantity", "1")), 99))
    except ValueError:
        return HttpResponseBadRequest("Invalid quantity")
    cart_data = request.session.get("cart", {})
    previous = int(cart_data.get(variant.pk, {}).get("quantity", 0))
    if previous + quantity > variant.stock:
        messages.error(request, "That quantity is not available.")
        return redirect("product_detail", slug=variant.product.slug)
    cart_data[variant.pk] = {"quantity": previous + quantity}
    request.session["cart"] = cart_data
    messages.success(request, "Added to cart.")
    return redirect("cart")


@require_POST
def cart_update(request):
    variant_id = request.POST.get("variant_id", "")
    cart_data = request.session.get("cart", {})
    if variant_id not in cart_data:
        return redirect("cart")
    try:
        quantity = int(request.POST.get("quantity", "1"))
    except ValueError:
        return HttpResponseBadRequest("Invalid quantity")
    if quantity <= 0:
        cart_data.pop(variant_id, None)
    else:
        variant = get_object_or_404(ProductVariant, pk=variant_id)
        if quantity > variant.stock:
            messages.error(request, "That quantity is not available.")
        else:
            cart_data[variant_id]["quantity"] = min(quantity, 99)
    request.session["cart"] = cart_data
    return redirect("cart")


def checkout(request):
    rows = cart_rows(request.session.get("cart", {}))
    if not rows:
        messages.info(request, "Add something to your cart first.")
        return redirect("catalog")
    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            try:
                order = create_order(form.cleaned_data, request.session.get("cart", {}))
            except (InsufficientStock, InvalidPromo) as exc:
                form.add_error(None, str(exc))
            else:
                request.session["cart"] = {}
                return redirect("order_success", order_number=order.order_number)
    else:
        form = CheckoutForm(initial={"delivery_zone": "inside"})
    subtotal = sum((row["line_total"] for row in rows), Decimal("0.00"))
    settings = store_settings()
    return render(request, "shop/checkout.html", {"form": form, "rows": rows, "subtotal": subtotal,
        "inside_charge": settings.get("delivery_inside_valley", "100"),
        "outside_charge": settings.get("delivery_outside_valley", "200"),
        "qr_image": settings.get("qr_image", ""),
        "payment_instructions": settings.get("payment_instructions", "Place your order and follow the shop's payment instructions.")})


def order_success(request, order_number):
    # Order number only; no private customer or payment details are exposed.
    if not Order.objects.filter(order_number=order_number).exists():
        raise Http404
    return render(request, "shop/success.html", {"order_number": order_number})


def contact(request):
    track(request)
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Thanks! Your message has been sent.")
        return redirect("contact")
    return render(request, "shop/contact.html", {"form": form,
        "seo_title": "Contact Us — " + store_settings().get("site_name", "Clothing Shop")})


@require_POST
def newsletter_subscribe(request):
    if not HomepageSection.objects.filter(key="newsletter", visible=True).exists():
        raise Http404
    form = NewsletterForm(request.POST)
    if form.is_valid():
        subscriber, created = NewsletterSubscriber.objects.get_or_create(email=form.cleaned_data["email"])
        if not created and not subscriber.active:
            subscriber.active = True
            subscriber.save(update_fields=["active", "updated_at"])
        messages.success(request, "You're on the list for store updates.")
    else:
        messages.error(request, "Enter a valid email address to subscribe.")
    return redirect(reverse("home") + "#newsletter")


def promo_validate(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    rows = cart_rows(request.session.get("cart", {}))
    subtotal = sum((row["line_total"] for row in rows), Decimal("0.00"))
    try:
        promo, discount = promo_for(request.POST.get("code", ""), subtotal)
    except InvalidPromo as exc:
        return JsonResponse({"valid": False, "reason": str(exc)}, status=400)
    return JsonResponse({"valid": True, "code": promo.code, "discount": str(discount), "percent": str(promo.discount_percent)})



def loyalty_options(request):
    phone = request.GET.get("phone", "").strip()
    if len(phone) < 5:
        return JsonResponse({"rewards": []})
    selected_categories = {row["product"].category_id for row in cart_rows(request.session.get("cart", {}))}
    rewards = []
    for progress in LoyaltyProgress.objects.select_related("category").filter(phone=phone, category_id__in=selected_categories):
        reserved = Order.objects.filter(phone=phone, reward_category=progress.category, payment_status="pending").exclude(order_status="cancelled").count()
        available = progress.purchase_count // 10 - progress.free_items_redeemed - reserved
        if available < 1:
            continue
        variants = ProductVariant.objects.select_related("product").filter(
            product__category=progress.category, product__visibility=True, stock__gt=0)[:50]
        rewards.append({"category": progress.category.name, "available": available,
            "variants": [{"id": variant.pk, "label": f"{variant.product.name} — {variant.size}{' / ' + variant.color if variant.color else ''}"} for variant in variants]})
    return JsonResponse({"rewards": rewards})

def review_by_token(request, token):
    review = get_object_or_404(Review.objects.select_related("product"), review_token=token, used_at__isnull=True)
    form = ReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        from django.utils import timezone
        review.rating = form.cleaned_data["rating"]
        review.comment = form.cleaned_data["comment"]
        review.used_at = timezone.now()
        review.approved = False
        review.save(update_fields=["rating", "comment", "used_at", "approved"])
        messages.success(request, "Thank you. Your review is awaiting approval.")
        return redirect("home")
    return render(request, "shop/review.html", {"review": review, "form": form})


@staff_member_required
def dashboard(request):
    stats = {
        "products": Product.objects.count(),
        "orders": Order.objects.count(),
        "pending_orders": Order.objects.filter(order_status="pending").count(),
        "paid_revenue": Order.objects.filter(payment_status="paid").aggregate(total=Sum("total"))["total"] or Decimal("0.00"),
        "messages": Message.objects.filter(is_read=False).count(),
        "visitors": Visitor.objects.count(),
        "customers": Order.objects.values("phone").distinct().count(),
    }
    return render(request, "shop/dashboard.html", {"stats": stats,
        "recent_orders": Order.objects.all()[:10], "recent_messages": Message.objects.all()[:5]})


def robots(request):
    rules = "User-agent: *\nDisallow: /admin/\nDisallow: /dashboard/\nDisallow: /checkout/\n"
    return HttpResponse(rules + "Sitemap: " + site_url("/sitemap.xml") + "\n", content_type="text/plain")


def sitemap(request):
    from django.urls import reverse
    from django.utils.html import escape
    paths = [reverse("home"), reverse("catalog"), reverse("contact")]
    paths.extend(reverse("product_detail", args=[slug]) for slug in Product.objects.filter(visibility=True).values_list("slug", flat=True))
    urls = "".join(f"<url><loc>{escape(site_url(path))}</loc></url>" for path in paths)
    return HttpResponse(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', content_type="application/xml")
