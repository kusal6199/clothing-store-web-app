import csv
from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import TruncDate
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import esewa
from .forms import STORE_SETTING_GROUPS
from .management_forms import (
    CategoryForm, CollectionForm, HeroSlideForm, HomepageSectionForm, OrderStatusForm,
    ProductForm, ProductVariantFormSet, PromoBannerForm, PromoCodeForm,
    SettingsManagementForm, TagForm,
)
from .models import (
    Category, Collection, HeroSlide, HomepageSection, LoyaltyProgress, Message, Order,
    OrderItem, Product, PromoBanner, PromoCode, Review, Setting, Tag, Visitor,
)
from .loyalty import reward_selection_path
from .services import (
    InsufficientStock, InvalidOrderTransition, cancel_pending_order, confirm_order_paid,
    store_settings,
)
from .storage import save_image


def superuser_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('management:login')}?next={request.get_full_path()}")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def login_view(request):
    if request.user.is_authenticated and request.user.is_active and request.user.is_superuser:
        return redirect("management:dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        if not user.is_superuser:
            form.add_error(None, "This account cannot access store management.")
        else:
            login(request, user)
            target = request.POST.get("next", "")
            if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
                target = reverse("management:dashboard")
            return redirect(target)
    return render(request, "management/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("management:login")


def _page(request, queryset, per_page=20):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


@superuser_required
def dashboard(request):
    today = timezone.localdate()
    first_day = today - timedelta(days=13)
    rows = Order.objects.filter(created_at__date__gte=first_day).annotate(day=TruncDate("created_at")).values("day").annotate(
        count=Count("id"), revenue=Sum("total", filter=Q(payment_status="paid")),
    )
    by_day = {row["day"]: row for row in rows}
    chart = [{
        "day": first_day + timedelta(days=offset),
        "count": by_day.get(first_day + timedelta(days=offset), {}).get("count", 0),
        "revenue": by_day.get(first_day + timedelta(days=offset), {}).get("revenue") or Decimal("0"),
    } for offset in range(14)]
    maximum = max((row["count"] for row in chart), default=0)
    for row in chart:
        row["height"] = max(3, round(row["count"] * 100 / maximum)) if maximum else 3
    stats = {
        "products": Product.objects.count(),
        "orders": Order.objects.count(),
        "pending": Order.objects.filter(order_status="pending").count(),
        "revenue": Order.objects.filter(payment_status="paid").aggregate(total=Sum("total"))["total"] or Decimal("0"),
        "customers": Order.objects.values("phone").distinct().count(),
        "messages": Message.objects.filter(is_read=False).count(),
        "visitors": Visitor.objects.count(),
    }
    top_products = OrderItem.objects.filter(order__payment_status="paid", is_reward_item=False).values("product_name").annotate(
        revenue=Sum(F("price") * F("quantity"), output_field=DecimalField()), quantity=Sum("quantity"),
    ).order_by("-quantity", "product_name")[:5]
    return render(request, "management/dashboard.html", {
        "section": "dashboard", "stats": stats, "chart": chart, "top_products": top_products,
        "recent_orders": Order.objects.select_related("reward_category")[:7], "recent_messages": Message.objects.all()[:5],
    })


@superuser_required
def products(request):
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    queryset = Product.objects.select_related("category").prefetch_related("variants")
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(sku__icontains=query) | Q(slug__icontains=query))
    if category:
        queryset = queryset.filter(category_id=category)
    return render(request, "management/products.html", {
        "section": "products", "products": _page(request, queryset, 16), "categories": Category.objects.all(),
        "query": query, "selected_category": category,
    })


@superuser_required
def product_edit(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else Product()
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    variants = ProductVariantFormSet(request.POST or None, instance=product, prefix="variants")
    if request.method == "POST" and form.is_valid() and variants.is_valid():
        with transaction.atomic():
            product = form.save(commit=False)
            if form.cleaned_data.get("image_upload"):
                product.images = [*(product.images or []), save_image(form.cleaned_data["image_upload"], "products")]
            if form.cleaned_data.get("gallery_upload"):
                product.gallery_images = [*(product.gallery_images or []), save_image(form.cleaned_data["gallery_upload"], "products")]
            product.save()
            form.save_m2m()
            variants.instance = product
            variants.save()
        messages.success(request, f"{product.name} was saved.")
        return redirect("management:products")
    return render(request, "management/form.html", {
        "section": "products", "title": "Edit product" if pk else "Add product", "form": form,
        "formset": variants, "object": product if pk else None, "cancel_url": reverse("management:products"),
    })


@require_POST
@superuser_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    name = product.name
    product.delete()
    messages.success(request, f"{name} was deleted.")
    return redirect("management:products")


TAXONOMY = {
    "category": (Category, CategoryForm, "Categories", "categories"),
    "collection": (Collection, CollectionForm, "Collections", "collections"),
    "tag": (Tag, TagForm, "Tags", "tags"),
}


@superuser_required
def categories(request):
    return render(request, "management/categories.html", {
        "section": "categories", "categories": Category.objects.annotate(product_count=Count("products")),
        "collections": Collection.objects.annotate(product_count=Count("products")),
        "tags": Tag.objects.annotate(product_count=Count("products")),
        "tab": request.GET.get("tab", "categories"),
    })


def _taxonomy(kind):
    try:
        return TAXONOMY[kind]
    except KeyError as exc:
        raise Http404 from exc


@superuser_required
def taxonomy_edit(request, kind, pk=None):
    model, form_class, title, tab = _taxonomy(kind)
    obj = get_object_or_404(model, pk=pk) if pk else model()
    form = form_class(request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if hasattr(form, "cleaned_data") and form.cleaned_data.get("image_upload"):
            obj.image = save_image(form.cleaned_data["image_upload"], f"{tab}")
        obj.save()
        form.save_m2m()
        messages.success(request, f"{obj} was saved.")
        return redirect(f"{reverse('management:categories')}?tab={tab}")
    return render(request, "management/form.html", {
        "section": "categories", "title": f"{'Edit' if pk else 'Add'} {title[:-1].lower()}", "form": form,
        "object": obj if pk else None, "cancel_url": f"{reverse('management:categories')}?tab={tab}",
    })


@require_POST
@superuser_required
def taxonomy_delete(request, kind, pk):
    model, _form, _title, tab = _taxonomy(kind)
    obj = get_object_or_404(model, pk=pk)
    label = str(obj)
    obj.delete()
    messages.success(request, f"{label} was deleted.")
    return redirect(f"{reverse('management:categories')}?tab={tab}")


HOMEPAGE = {
    "slide": (HeroSlide, HeroSlideForm, "slide", "slides"),
    "section": (HomepageSection, HomepageSectionForm, "section", "sections"),
    "banner": (PromoBanner, PromoBannerForm, "promo banner", "banners"),
}


@superuser_required
def homepage(request):
    return render(request, "management/homepage.html", {
        "section": "homepage", "slides": HeroSlide.objects.all(), "sections": HomepageSection.objects.all(),
        "banners": PromoBanner.objects.all(), "reviews": Review.objects.select_related("product")[:100],
        "tab": request.GET.get("tab", "slides"),
    })


def _homepage_kind(kind):
    try:
        return HOMEPAGE[kind]
    except KeyError as exc:
        raise Http404 from exc


@superuser_required
def homepage_edit(request, kind, pk=None):
    model, form_class, label, tab = _homepage_kind(kind)
    obj = get_object_or_404(model, pk=pk) if pk else model()
    form = form_class(request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if kind == "slide" and form.cleaned_data.get("image_upload"):
            obj.image = save_image(form.cleaned_data["image_upload"], "hero")
        obj.save()
        form.save_m2m()
        messages.success(request, f"Homepage {label} was saved.")
        return redirect(f"{reverse('management:homepage')}?tab={tab}")
    return render(request, "management/form.html", {
        "section": "homepage", "title": f"{'Edit' if pk else 'Add'} {label}", "form": form,
        "object": obj if pk else None, "cancel_url": f"{reverse('management:homepage')}?tab={tab}",
    })


@require_POST
@superuser_required
def homepage_toggle(request, kind, pk):
    if kind == "review":
        obj = get_object_or_404(Review, pk=pk)
        obj.approved = not obj.approved
        obj.save(update_fields=["approved"])
        tab = "reviews"
    else:
        model, _form, _label, tab = _homepage_kind(kind)
        obj = get_object_or_404(model, pk=pk)
        obj.visible = not obj.visible
        obj.save(update_fields=["visible", "updated_at"])
    messages.success(request, "Visibility was updated.")
    return redirect(f"{reverse('management:homepage')}?tab={tab}")


@require_POST
@superuser_required
def homepage_delete(request, kind, pk):
    if kind == "review":
        obj = get_object_or_404(Review, pk=pk)
        tab = "reviews"
    else:
        model, _form, _label, tab = _homepage_kind(kind)
        obj = get_object_or_404(model, pk=pk)
    obj.delete()
    messages.success(request, "Homepage item was deleted.")
    return redirect(f"{reverse('management:homepage')}?tab={tab}")


def _filtered_orders(request):
    queryset = Order.objects.select_related("reward_category", "promo_code", "milestone_reward_item")
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(Q(order_number__icontains=query) | Q(customer_name__icontains=query) | Q(phone__icontains=query))
    if request.GET.get("status"):
        queryset = queryset.filter(order_status=request.GET["status"])
    if request.GET.get("payment"):
        queryset = queryset.filter(payment_status=request.GET["payment"])
    if request.GET.get("method"):
        queryset = queryset.filter(payment_method=request.GET["method"])
    return queryset


@superuser_required
def orders(request):
    return render(request, "management/orders.html", {
        "section": "orders", "orders": _page(request, _filtered_orders(request), 25), "order_statuses": Order.STATUS,
        "payment_statuses": Order.PAYMENT, "payment_methods": Order.PAYMENT_METHOD,
    })


@superuser_required
def orders_export(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="orders.csv"'
    writer = csv.writer(response)
    writer.writerow(["Order number", "Customer", "Phone", "Email", "Total", "Payment method", "Payment", "Status", "Created"])
    for order in _filtered_orders(request).iterator():
        writer.writerow([order.order_number, order.customer_name, order.phone, order.email, order.total,
                         order.payment_method, order.payment_status, order.order_status, order.created_at.isoformat()])
    return response


@superuser_required
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.select_related(
        "reward_category", "promo_code", "milestone_reward_item", "milestone_reward_item__product",
    ).prefetch_related("items"), pk=pk)
    reward_progress = None
    if order.reward_category_id:
        reward_progress = LoyaltyProgress.objects.filter(
            phone=order.phone, category_id=order.reward_category_id,
        ).first()
    selection_url = ""
    if order.payment_status == "paid" and order.reward_category_id and not order.reward_fulfilled:
        selection_url = request.build_absolute_uri(reward_selection_path(order))
    return render(request, "management/order_detail.html", {
        "section": "orders", "order": order, "status_form": OrderStatusForm(instance=order),
        "reward_progress": reward_progress, "reward_selection_url": selection_url,
    })


@require_POST
@superuser_required
def order_status(request, pk):
    order = get_object_or_404(Order, pk=pk)
    form = OrderStatusForm(request.POST, instance=order)
    if form.is_valid():
        form.save()
        messages.success(request, "Order status was updated.")
    else:
        messages.error(request, "; ".join(error for errors in form.errors.values() for error in errors))
    return redirect("management:order_detail", pk=pk)


@require_POST
@superuser_required
def order_confirm_payment(request, pk):
    order = get_object_or_404(Order, pk=pk)
    try:
        confirm_order_paid(order.pk)
    except (InsufficientStock, InvalidOrderTransition) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Payment was confirmed and stock and loyalty were updated.")
    return redirect("management:order_detail", pk=pk)


@require_POST
@superuser_required
def order_cancel(request, pk):
    order = get_object_or_404(Order, pk=pk)
    try:
        cancel_pending_order(order.pk)
    except InvalidOrderTransition as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "The unpaid order was cancelled.")
    return redirect("management:order_detail", pk=pk)


@require_POST
@superuser_required
def order_check_esewa(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if order.payment_method != "esewa":
        messages.error(request, "This is not an eSewa order.")
    else:
        try:
            result = esewa.reconcile(order)
        except esewa.EsewaVerificationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"eSewa status: {result}.")
    return redirect("management:order_detail", pk=pk)


@superuser_required
def loyalty(request):
    query = request.GET.get("q", "").strip()
    queryset = LoyaltyProgress.objects.select_related("category").order_by("phone", "category__name")
    if query:
        queryset = queryset.filter(Q(phone__icontains=query) | Q(category__name__icontains=query))
    page = _page(request, queryset, 25)
    rows = []
    for progress in page:
        reserved = Order.objects.filter(phone=progress.phone, reward_category=progress.category).filter(
            Q(payment_status="pending") & ~Q(order_status="cancelled") |
            Q(payment_status="paid", reward_fulfilled=False)
        ).count()
        rows.append({"progress": progress, "reserved": reserved, "available": max(0, progress.rewards_available - reserved)})
    return render(request, "management/loyalty.html", {
        "section": "loyalty", "page": page, "rows": rows, "query": query,
    })


@superuser_required
def promo_codes(request):
    query = request.GET.get("q", "").strip()
    queryset = PromoCode.objects.annotate(
        paid_order_count=Count("orders", filter=Q(orders__payment_status="paid"), distinct=True),
        paid_total=Sum("orders__total", filter=Q(orders__payment_status="paid")),
    ).order_by("-created_at")
    if query:
        queryset = queryset.filter(Q(code__icontains=query) | Q(influencer_name__icontains=query))
    page = _page(request, queryset, 25)
    for promo in page:
        promo.commission_owed = ((promo.paid_total or Decimal("0")) * promo.commission_percent / Decimal("100")).quantize(Decimal("0.01"))
    return render(request, "management/promo_codes.html", {
        "section": "promo_codes", "promos": page, "query": query,
    })


@superuser_required
def promo_edit(request, pk=None):
    promo = get_object_or_404(PromoCode, pk=pk) if pk else PromoCode()
    form = PromoCodeForm(request.POST or None, instance=promo)
    if request.method == "POST" and form.is_valid():
        promo = form.save()
        messages.success(request, f"Promo code {promo.code} was saved.")
        return redirect("management:promo_codes")
    return render(request, "management/form.html", {
        "section": "promo_codes", "title": "Edit promo code" if pk else "Add promo code", "form": form,
        "object": promo if pk else None, "cancel_url": reverse("management:promo_codes"),
    })


@require_POST
@superuser_required
def promo_toggle(request, pk):
    promo = get_object_or_404(PromoCode, pk=pk)
    promo.active = not promo.active
    promo.save(update_fields=["active", "updated_at"])
    messages.success(request, f"{promo.code} is now {'active' if promo.active else 'inactive'}.")
    return redirect("management:promo_codes")


@require_POST
@superuser_required
def promo_delete(request, pk):
    promo = get_object_or_404(PromoCode, pk=pk)
    code = promo.code
    promo.delete()
    messages.success(request, f"Promo code {code} was deleted.")
    return redirect("management:promo_codes")


@superuser_required
def message_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    queryset = Message.objects.all()
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(email__icontains=query) | Q(phone__icontains=query) | Q(message__icontains=query))
    if status == "read":
        queryset = queryset.filter(is_read=True)
    elif status == "unread":
        queryset = queryset.filter(is_read=False)
    return render(request, "management/messages.html", {
        "section": "messages", "inbox": _page(request, queryset, 20), "query": query, "status": status,
    })


@require_POST
@superuser_required
def message_toggle(request, pk):
    item = get_object_or_404(Message, pk=pk)
    item.is_read = not item.is_read
    item.save(update_fields=["is_read"])
    return redirect("management:messages")


@require_POST
@superuser_required
def message_delete(request, pk):
    get_object_or_404(Message, pk=pk).delete()
    messages.success(request, "Message was deleted.")
    return redirect("management:messages")


@superuser_required
def settings_view(request):
    initial = store_settings()
    form = SettingsManagementForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        values = dict(form.cleaned_data)
        upload = values.pop("qr_upload", None)
        if upload:
            values["qr_image"] = save_image(upload, "settings")
        with transaction.atomic():
            for key, value in values.items():
                Setting.objects.update_or_create(key=key, defaults={"value": str(value if value is not None else "")})
        messages.success(request, "Store settings were saved.")
        return redirect("management:settings")
    groups = [{"title": title, "fields": [form[key] for key in keys]} for title, keys in STORE_SETTING_GROUPS]
    groups[-2]["fields"].append(form["qr_upload"])
    return render(request, "management/settings.html", {"section": "settings", "form": form, "groups": groups})
