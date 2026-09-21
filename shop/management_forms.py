from django import forms
from django.forms import inlineformset_factory
from django.utils.text import slugify

from .forms import StoreSettingsForm
from .models import (
    Category, Collection, HeroSlide, HomepageSection, Order, Product,
    ProductVariant, PromoBanner, PromoCode, Tag,
)


class StyledModelForm(forms.ModelForm):
    """Shared form behavior for the custom management interface."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "control"
            if isinstance(field.widget, forms.CheckboxInput):
                css = "checkbox-control"
            field.widget.attrs.setdefault("class", css)


class SlugFormMixin:
    def clean_slug(self):
        slug = self.cleaned_data.get("slug") or slugify(self.cleaned_data.get("name", ""))
        if not slug:
            raise forms.ValidationError("Enter a name or slug.")
        return slug


class ProductForm(SlugFormMixin, StyledModelForm):
    colors = forms.CharField(required=False, help_text="Comma-separated colors")
    image_upload = forms.ImageField(required=False, help_text="Adds a main product image (JPEG, PNG, WebP or AVIF; max 8 MB).")
    gallery_upload = forms.ImageField(required=False, help_text="Adds one gallery image.")

    class Meta:
        model = Product
        fields = (
            "name", "slug", "sku", "category", "description", "price", "discount_price",
            "colors", "material", "care_instructions", "tags", "collections", "featured",
            "best_seller", "new_arrival", "visibility",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "care_instructions": forms.Textarea(attrs={"rows": 3}),
            "tags": forms.CheckboxSelectMultiple,
            "collections": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.initial["colors"] = ", ".join(self.instance.colors or [])

    def clean_colors(self):
        raw = self.cleaned_data.get("colors", "")
        return [value.strip() for value in raw.split(",") if value.strip()]


ProductVariantFormSet = inlineformset_factory(
    Product,
    ProductVariant,
    fields=("size", "color", "stock", "additional_price"),
    extra=1,
    can_delete=True,
    widgets={
        "size": forms.TextInput(attrs={"class": "control", "placeholder": "Size"}),
        "color": forms.TextInput(attrs={"class": "control", "placeholder": "Color (optional)"}),
        "stock": forms.NumberInput(attrs={"class": "control", "min": 0}),
        "additional_price": forms.NumberInput(attrs={"class": "control", "step": "0.01"}),
    },
)


class CategoryForm(SlugFormMixin, StyledModelForm):
    image_upload = forms.ImageField(required=False)

    class Meta:
        model = Category
        fields = ("name", "slug", "description", "order", "visible")
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class CollectionForm(SlugFormMixin, StyledModelForm):
    image_upload = forms.ImageField(required=False)

    class Meta:
        model = Collection
        fields = ("name", "slug", "description", "order", "visible")
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class TagForm(SlugFormMixin, StyledModelForm):
    class Meta:
        model = Tag
        fields = ("name", "slug")


class HeroSlideForm(StyledModelForm):
    image_upload = forms.ImageField(required=False)

    class Meta:
        model = HeroSlide
        fields = ("title", "subtitle", "image", "link", "button_text", "order", "visible")
        widgets = {"subtitle": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        data = super().clean()
        if not data.get("image") and not data.get("image_upload") and not self.instance.image:
            self.add_error("image", "Provide an image URL or upload an image.")
        return data


class HomepageSectionForm(StyledModelForm):
    class Meta:
        model = HomepageSection
        fields = ("key", "title", "subtitle", "order", "visible", "content")
        widgets = {
            "subtitle": forms.Textarea(attrs={"rows": 3}),
            "content": forms.Textarea(attrs={"rows": 6}),
        }


class PromoBannerForm(StyledModelForm):
    class Meta:
        model = PromoBanner
        fields = ("text", "link", "order", "visible")


class PromoCodeForm(StyledModelForm):
    class Meta:
        model = PromoCode
        fields = (
            "code", "influencer_name", "discount_percent", "commission_percent",
            "max_uses", "expires_at", "active",
        )
        widgets = {"expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expires_at"].input_formats = ["%Y-%m-%dT%H:%M"]


class OrderStatusForm(StyledModelForm):
    class Meta:
        model = Order
        fields = ("order_status",)

    def clean_order_status(self):
        status = self.cleaned_data["order_status"]
        if status == "cancelled" and self.instance.order_status != "cancelled":
            raise forms.ValidationError("Use the cancellation action so reservations are released safely.")
        if (status in {"shipped", "delivered"} and self.instance.payment_status == "paid"
                and self.instance.reward_category_id and not self.instance.reward_fulfilled):
            raise forms.ValidationError("Awaiting customer reward selection. Select the reward before shipping this order.")
        return status


class SettingsManagementForm(StoreSettingsForm):
    qr_upload = forms.ImageField(required=False, label="Upload a payment QR image")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "control")
