from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from . import esewa
from .forms import CheckoutForm, ContactForm, NewsletterForm, ReviewForm
from .loyalty import read_reward_selection_token, reward_catalog, reward_selection_path
from .models import (
    Category, Collection, HeroSlide, HomepageSection, Message, NewsletterSubscriber, Order,
    Product, ProductVariant, PromoBanner, Review, Tag, Visitor, LoyaltyProgress,
)
from .services import (
    InsufficientStock, InvalidOrderTransition, InvalidPromo, cart_rows, create_order,
    fulfill_order_reward, promo_for, store_settings,
)
from .phones import normalize_phone
from .seo import asset_url, json_ld, site_url


CHECKOUT_DRAFT_FIELDS = (
    "customer_name", "phone", "email", "delivery_address", "city", "additional_notes",
    "delivery_zone", "promo_code", "reward_variant_id", "payment_method",
)


def save_checkout_draft(request, cleaned_data):
    request.session["checkout_draft"] = {
        field: cleaned_data.get(field, "") for field in CHECKOUT_DRAFT_FIELDS
    }


def remember_customer_order(request, order):
    order_ids = list(request.session.get("customer_order_ids", []))
    if order.pk not in order_ids:
        order_ids.append(order.pk)
    request.session["customer_order_ids"] = order_ids[-10:]


def customer_reward_path(request, order):
    if (order.pk in request.session.get("customer_order_ids", [])
            and order.payment_status == "paid" and order.reward_category_id
            and not order.reward_fulfilled):
        return reward_selection_path(order)
    return ""


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
    pending_uuid = request.session.get("pending_esewa_transaction_uuid")
    if pending_uuid:
        previous = Order.objects.filter(esewa_transaction_uuid=pending_uuid, payment_method="esewa").first()
        pending_cart = request.session.get("pending_esewa_cart", {})
        current_cart = request.session.get("cart", {})
        if (previous and previous.order_status != "cancelled"
                and previous.payment_status != "paid" and current_cart != pending_cart):
            try:
                esewa.reconcile(previous)
            except esewa.EsewaVerificationError:
                esewa.set_state(previous.pk, "uncertain")
            previous.refresh_from_db()
        if previous and previous.order_status != "cancelled" and previous.payment_status != "paid":
            return redirect("esewa_result", transaction_uuid=pending_uuid)
        if previous and previous.payment_status == "paid":
            return redirect("esewa_result", transaction_uuid=pending_uuid)
        request.session.pop("pending_esewa_transaction_uuid", None)
        request.session.pop("pending_esewa_cart", None)
    rows = cart_rows(request.session.get("cart", {}))
    if not rows:
        messages.info(request, "Add something to your cart first.")
        return redirect("catalog")
    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if not esewa.configured():
            form.fields["payment_method"].choices = [("manual", "Manual / QR")]
        if form.is_valid():
            save_checkout_draft(request, form.cleaned_data)
            try:
                data = dict(form.cleaned_data)
                if data["payment_method"] == "esewa":
                    data["esewa_product_code"] = settings.ESEWA_MERCHANT_CODE
                order = create_order(data, request.session.get("cart", {}))
            except (InsufficientStock, InvalidPromo) as exc:
                form.add_error(None, str(exc))
            else:
                remember_customer_order(request, order)
                if order.payment_method == "esewa":
                    request.session["pending_esewa_transaction_uuid"] = order.esewa_transaction_uuid
                    request.session["pending_esewa_cart"] = request.session.get("cart", {}).copy()
                    return render(request, "shop/esewa_submit.html", {
                        "order": order, "payment_url": esewa.PAYMENT_URL,
                        "payment_fields": esewa.payment_fields(order),
                    })
                request.session["cart"] = {}
                request.session.pop("checkout_draft", None)
                return redirect("order_success", order_number=order.order_number)
    else:
        initial = {"delivery_zone": "inside"}
        initial.update(request.session.get("checkout_draft", {}))
        form = CheckoutForm(initial=initial)
        if not esewa.configured():
            form.fields["payment_method"].choices = [("manual", "Manual / QR")]
    subtotal = sum((row["line_total"] for row in rows), Decimal("0.00"))
    shop_settings = store_settings()
    inside_charge = shop_settings.get("delivery_inside_valley", "100")
    outside_charge = shop_settings.get("delivery_outside_valley", "200")
    selected_zone = "outside" if form["delivery_zone"].value() == "outside" else "inside"
    initial_delivery = Decimal(outside_charge if selected_zone == "outside" else inside_charge)
    return render(request, "shop/checkout.html", {"form": form, "rows": rows, "subtotal": subtotal,
        "inside_charge": inside_charge, "outside_charge": outside_charge,
        "selected_zone": selected_zone, "initial_delivery": initial_delivery,
        "initial_total": subtotal + initial_delivery,
        "qr_image": shop_settings.get("qr_image", ""),
        "payment_instructions": shop_settings.get("payment_instructions", "Place your order and follow the shop's payment instructions.")})


@require_GET
def esewa_return(request, outcome, transaction_uuid):
    order = get_object_or_404(Order, esewa_transaction_uuid=transaction_uuid, payment_method="esewa")
    encoded = request.GET.get("data")
    try:
        if outcome == "success" and not encoded:
            raise esewa.EsewaVerificationError("Missing signed success response")
        signed = esewa.verify_return_data(encoded, order) if encoded else None
        esewa.reconcile(order, signed_return=signed)
    except esewa.EsewaVerificationError:
        esewa.set_state(order.pk, "uncertain")
    return redirect("esewa_result", transaction_uuid=transaction_uuid)


@require_GET
def esewa_result(request, transaction_uuid):
    order = get_object_or_404(
        Order.objects.select_related("reward_category", "milestone_reward_item"),
        esewa_transaction_uuid=transaction_uuid, payment_method="esewa",
    )
    if request.session.get("pending_esewa_transaction_uuid") == transaction_uuid:
        if order.payment_status == "paid":
            if request.session.get("cart", {}) == request.session.get("pending_esewa_cart", {}):
                request.session["cart"] = {}
            request.session.pop("pending_esewa_transaction_uuid", None)
            request.session.pop("pending_esewa_cart", None)
            request.session.pop("checkout_draft", None)
        elif order.order_status == "cancelled":
            request.session.pop("pending_esewa_transaction_uuid", None)
            request.session.pop("pending_esewa_cart", None)
    order.refresh_from_db()
    return render(request, "shop/esewa_result.html", {
        "order": order, "reward_selection_path": customer_reward_path(request, order),
    })


@require_POST
def esewa_check(request, transaction_uuid):
    order = get_object_or_404(Order, esewa_transaction_uuid=transaction_uuid, payment_method="esewa")
    try:
        esewa.reconcile(order)
    except esewa.EsewaVerificationError:
        esewa.set_state(order.pk, "uncertain")
    return redirect("esewa_result", transaction_uuid=transaction_uuid)


@require_POST
def esewa_return_to_checkout(request, transaction_uuid):
    if request.session.get("pending_esewa_transaction_uuid") != transaction_uuid:
        raise Http404
    order = get_object_or_404(Order, esewa_transaction_uuid=transaction_uuid, payment_method="esewa")
    try:
        result = esewa.reconcile(order)
    except esewa.EsewaVerificationError:
        result = "uncertain"
        esewa.set_state(order.pk, result)
    order.refresh_from_db()
    if result == "cancelled" or order.order_status == "cancelled":
        request.session.pop("pending_esewa_transaction_uuid", None)
        request.session.pop("pending_esewa_cart", None)
        messages.info(request, "The unfinished eSewa attempt was cancelled. You can update and place your order again.")
        return redirect("checkout")
    if result == "paid" or order.payment_status == "paid":
        return redirect("esewa_result", transaction_uuid=transaction_uuid)
    messages.info(request, "eSewa still reports this payment as pending or uncertain. Please check again shortly.")
    return redirect("esewa_result", transaction_uuid=transaction_uuid)


def order_success(request, order_number):
    # Private reward actions are shown only to the browser session that placed the order.
    order = get_object_or_404(
        Order.objects.select_related("reward_category", "milestone_reward_item"),
        order_number=order_number,
    )
    return render(request, "shop/success.html", {
        "order": order, "order_number": order.order_number,
        "reward_selection_path": customer_reward_path(request, order),
    })


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
    phone = normalize_phone(request.GET.get("phone", ""))
    if len(phone) < 5:
        return JsonResponse({"rewards": [], "progress": []})
    selected_categories = {row["product"].category_id for row in cart_rows(request.session.get("cart", {}))}
    rewards = []
    progress_rows = []
    for progress in LoyaltyProgress.objects.select_related("category").filter(phone=phone, category_id__in=selected_categories):
        reserved = Order.objects.filter(phone=phone, reward_category=progress.category).filter(
            Q(payment_status="pending") & ~Q(order_status="cancelled")
            | Q(payment_status="paid", reward_fulfilled=False)
        ).count()
        available = progress.purchase_count // 10 - progress.free_items_redeemed - reserved
        progress_rows.append({
            "category_id": progress.category_id,
            "category": progress.category.name,
            "qualifying_items": progress.purchase_count,
            "towards_next": progress.purchase_count % 10,
            "available": max(0, available),
        })
        if available < 1:
            continue
        rewards.append({
            "category_id": progress.category_id,
            "category": progress.category.name,
            "available": available,
            "products": reward_catalog(progress.category_id),
        })
    return JsonResponse({"rewards": rewards, "progress": progress_rows})


def reward_selection(request, token):
    try:
        order_id = read_reward_selection_token(token)
    except signing.SignatureExpired:
        return HttpResponse("This reward selection link has expired.", status=410)
    except signing.BadSignature:
        raise Http404
    order = get_object_or_404(
        Order.objects.select_related("reward_category", "milestone_reward_item", "milestone_reward_item__product"),
        pk=order_id,
    )
    if order.payment_status != "paid" or not order.reward_category_id:
        return HttpResponse("This order does not have a selectable paid reward.", status=409)
    if request.method == "POST" and not order.reward_fulfilled:
        variant_id = request.POST.get("reward_variant_id", "").strip()
        if not variant_id:
            messages.error(request, "Choose a free product, size, and color.")
        else:
            try:
                fulfill_order_reward(order.pk, variant_id, selection_source="customer")
            except (InsufficientStock, InvalidOrderTransition) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "Your free loyalty item was added to the order.")
                return redirect("reward_selection", token=token)
        order.refresh_from_db()
    catalog = {
        "category_id": order.reward_category_id,
        "category": order.reward_category.name,
        "products": reward_catalog(order.reward_category_id),
    } if not order.reward_fulfilled else None
    return render(request, "shop/reward_selection.html", {
        "order": order, "token": token, "reward_catalog": catalog,
    })

def review_by_token(request, token):
    anchor = get_object_or_404(Review.objects.select_related("order"), review_token=token, order__isnull=False)
    if anchor.order.created_at < timezone.now() - timedelta(days=30):
        return HttpResponse("This review link has expired.", status=410)
    reviews = list(Review.objects.filter(order_id=anchor.order_id, product__isnull=False).select_related("product"))
    target = None
    if request.method == "POST":
        target = next((review for review in reviews if review.product_id == request.POST.get("product_id")), None)
        if target is None:
            raise Http404
        if target.used_at:
            return HttpResponseBadRequest("This product was already reviewed.")
        form = ReviewForm(request.POST, prefix=target.pk)
        if form.is_valid():
            with transaction.atomic():
                locked = Review.objects.select_for_update().get(pk=target.pk)
                if locked.used_at:
                    return HttpResponseBadRequest("This product was already reviewed.")
                locked.rating = form.cleaned_data["rating"]
                locked.comment = form.cleaned_data["comment"]
                locked.name = form.cleaned_data["name"] or anchor.order.customer_name[:80]
                locked.used_at = timezone.now()
                locked.approved = False
                locked.save(update_fields=["rating", "comment", "name", "used_at", "approved"])
            messages.success(request, "Review submitted. It will appear after approval.")
            return redirect("review_by_token", token=token)
    cards = [{"review": review,
              "form": form if target and target.pk == review.pk else ReviewForm(prefix=review.pk, initial={"name": anchor.order.customer_name[:80]})}
             for review in reviews]
    return render(request, "shop/review.html", {"order": anchor.order, "cards": cards,
        "all_done": bool(reviews) and all(review.used_at for review in reviews)})


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
