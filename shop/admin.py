from django.contrib import admin, messages
from django.contrib.auth.models import Group, User
from django.contrib.admin.sites import NotRegistered
from django.db.models import Q
import csv
from django.http import HttpResponse
from django.utils.html import format_html
from .admin_forms import ProductAdminForm, CategoryAdminForm, HeroSlideAdminForm, OrderAdminForm
from .storage import save_image
from .models import (
    Category, Collection, HeroSlide, HomepageSection, LoyaltyProgress,
    Message, NewsletterSubscriber, Order, OrderItem, Product, ProductVariant, PromoBanner,
    PromoCode, Review, Setting, Tag, Visitor,
)

admin.site.site_header = "Clothing Shop Management"
admin.site.site_title = "Clothing Shop"
admin.site.index_title = "Store administration"


def superuser_has_permission(request):
    return request.user.is_active and request.user.is_superuser


admin.site.has_permission = superuser_has_permission

# The built-in admin is an unlinked emergency fallback at /internal-admin/.
# Identity and permission management stay outside every web management surface.
for identity_model in (User, Group):
    try:
        admin.site.unregister(identity_model)
    except NotRegistered:
        pass


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm

    def save_model(self, request, obj, form, change):
        uploaded = form.cleaned_data.get("image_upload")
        if uploaded:
            obj.images = [*(obj.images or []), save_image(uploaded, "products")]
        gallery_upload = form.cleaned_data.get("gallery_upload")
        if gallery_upload:
            obj.gallery_images = [*(obj.gallery_images or []), save_image(gallery_upload, "products")]
        super().save_model(request, obj, form, change)

    list_display = ("name", "category", "price", "discount_price", "featured", "visibility", "updated_at")
    list_filter = ("category", "featured", "best_seller", "new_arrival", "visibility")
    search_fields = ("name", "sku", "slug")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("tags", "collections")
    inlines = [ProductVariantInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    form = CategoryAdminForm

    def save_model(self, request, obj, form, change):
        uploaded = form.cleaned_data.get("image_upload")
        if uploaded:
            obj.image = save_image(uploaded, "categories")
        super().save_model(request, obj, form, change)

    list_display = ("name", "order", "visible")
    list_editable = ("order", "visible")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "visible")
    list_editable = ("order", "visible")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "product_name", "product_image", "size", "color", "price", "quantity", "is_reward_item")

    def has_add_permission(self, request, obj=None):
        return False


@admin.action(description="Mark selected orders paid and update stock")
def mark_paid(modeladmin, request, queryset):
    from .services import confirm_order_paid, InsufficientStock, InvalidOrderTransition
    success = 0
    for order in queryset:
        try:
            confirm_order_paid(order.pk)
            success += 1
        except (InsufficientStock, InvalidOrderTransition) as exc:
            modeladmin.message_user(request, f"{order.order_number}: {exc}", level=messages.ERROR)
    if success:
        modeladmin.message_user(request, f"Confirmed {success} order(s).", level=messages.SUCCESS)


@admin.action(description="Export selected orders as CSV")
def export_orders(modeladmin, request, queryset):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="orders.csv"'
    writer = csv.writer(response)
    writer.writerow(["Order number", "Customer", "Phone", "Email", "Total", "Payment", "Status", "Created"])
    for order in queryset.iterator():
        writer.writerow([order.order_number, order.customer_name, order.phone,
                         order.email, order.total, order.payment_status, order.order_status, order.created_at.isoformat()])
    return response


@admin.action(description="Cancel selected unpaid orders and release promo uses")
def cancel_unpaid(modeladmin, request, queryset):
    from .services import cancel_pending_order, InvalidOrderTransition
    success = 0
    for order in queryset:
        try:
            already_cancelled = order.order_status == "cancelled"
            cancel_pending_order(order.pk)
            if not already_cancelled:
                success += 1
        except InvalidOrderTransition as exc:
            modeladmin.message_user(request, f"{order.order_number}: {exc}", level=messages.ERROR)
    if success:
        modeladmin.message_user(request, f"Cancelled {success} order(s).", level=messages.SUCCESS)


@admin.action(description="Check selected eSewa UAT payment statuses")
def check_esewa(modeladmin, request, queryset):
    from .esewa import EsewaVerificationError, reconcile
    for order in queryset.filter(payment_method="esewa"):
        try:
            result = reconcile(order)
        except EsewaVerificationError as exc:
            result = str(exc)
        modeladmin.message_user(request, f"{order.order_number}: {result}")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    form = OrderAdminForm
    list_display = ("order_number", "customer_name", "phone", "total", "payment_method", "payment_status", "reward_status", "esewa_status", "order_status", "created_at")
    list_filter = ("payment_method", "payment_status", "order_status", "created_at")
    list_select_related = ("reward_category",)
    search_fields = ("order_number", "customer_name", "phone")
    readonly_fields = ("order_number", "subtotal", "discount_amount", "delivery_charge", "total", "payment_status", "payment_method", "esewa_transaction_uuid", "esewa_product_code", "esewa_status", "esewa_ref_id", "reward_category", "reward_fulfilled", "reward_summary", "created_at", "updated_at")
    inlines = [OrderItemInline]
    actions = [mark_paid, cancel_unpaid, check_esewa, export_orders]

    @admin.display(description="Loyalty reward")
    def reward_status(self, order):
        if not order.reward_category_id:
            return "—"
        state = "Fulfilled" if order.reward_fulfilled else "Pending"
        return f"{state}: {order.reward_category}"

    @admin.display(description="Loyalty reward status")
    def reward_summary(self, order):
        if not order.reward_category_id:
            return "No milestone reward attached to this order."
        if order.reward_fulfilled:
            return format_html("<strong>Fulfilled:</strong> one free {} item was added and accounted for.", order.reward_category)
        return format_html(
            "<strong>Pending fulfilment:</strong> choose one in-stock {} variant below. "
            "Buy 10 paid items from the same category using the same phone number and receive 1 free item from that category.",
            order.reward_category,
        )

    def save_model(self, request, obj, form, change):
        reward_variant = form.cleaned_data.get("reward_variant")
        super().save_model(request, obj, form, change)
        if reward_variant:
            from .services import fulfill_order_reward, InsufficientStock, InvalidOrderTransition
            try:
                fulfill_order_reward(obj.pk, reward_variant.pk)
            except (InsufficientStock, InvalidOrderTransition) as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                self.message_user(request, "The loyalty reward was added as a free item and stock was updated.", level=messages.SUCCESS)


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "influencer_name", "discount_percent", "current_uses", "max_uses", "active", "expires_at")
    list_filter = ("active",)
    search_fields = ("code", "influencer_name")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("name", "product", "rating", "approved", "created_at")
    list_filter = ("approved", "rating")
    list_editable = ("approved",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "is_read", "created_at")
    list_filter = ("is_read",)
    list_editable = ("is_read",)


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "active", "created_at")
    list_filter = ("active", "created_at")
    list_editable = ("active",)
    search_fields = ("email",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(HeroSlide)
class HeroSlideAdmin(admin.ModelAdmin):
    form = HeroSlideAdminForm

    def save_model(self, request, obj, form, change):
        uploaded = form.cleaned_data.get("image_upload")
        if uploaded:
            obj.image = save_image(uploaded, "hero")
        super().save_model(request, obj, form, change)

    list_display = ("title", "order", "visible")
    list_editable = ("order", "visible")


@admin.register(HomepageSection)
class HomepageSectionAdmin(admin.ModelAdmin):
    list_display = ("key", "title", "order", "visible")
    list_editable = ("order", "visible")


@admin.register(PromoBanner)
class PromoBannerAdmin(admin.ModelAdmin):
    list_display = ("text", "order", "visible")
    list_editable = ("order", "visible")


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "updated_at")
    search_fields = ("key",)


@admin.register(LoyaltyProgress)
class LoyaltyProgressAdmin(admin.ModelAdmin):
    list_display = ("phone", "category", "purchase_count", "current_progress", "free_items_redeemed", "available_rewards")
    search_fields = ("phone",)
    readonly_fields = ("current_progress", "available_rewards", "loyalty_rule")

    @admin.display(description="Progress")
    def current_progress(self, progress):
        return f"{progress.progress_to_next_reward} of 10 qualifying items"

    @admin.display(description="Available")
    def available_rewards(self, progress):
        reserved = Order.objects.filter(phone=progress.phone, reward_category=progress.category).filter(
            Q(payment_status="pending") & ~Q(order_status="cancelled")
            | Q(payment_status="paid", reward_fulfilled=False)
        ).count()
        available = max(0, progress.rewards_available - reserved)
        return f"{available} reward{'s' if available != 1 else ''} available"

    @admin.display(description="How loyalty works")
    def loyalty_rule(self, progress):
        return "Buy 10 paid items from the same category using the same phone number and receive 1 free item from that category."


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = ("path", "ip", "created_at")
    list_filter = ("created_at",)
    search_fields = ("path",)
    readonly_fields = ("path", "ip", "user_agent", "created_at")
