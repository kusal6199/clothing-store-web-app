from django import forms
from django.core.exceptions import ValidationError
from .models import Category, HeroSlide, Order, Product, ProductVariant


class ProductAdminForm(forms.ModelForm):
    image_upload = forms.ImageField(required=False, help_text="Optional. Add a main product image.")
    gallery_upload = forms.ImageField(required=False, help_text="Optional. Add a detail gallery image.")

    class Meta:
        model = Product
        fields = "__all__"

    def clean(self):
        data = super().clean()
        for field in ("images", "gallery_images", "colors"):
            if field in data and data[field] is None:
                data[field] = []
        return data


class CategoryAdminForm(forms.ModelForm):
    image_upload = forms.ImageField(required=False, help_text="Optional. Upload a category image.")

    class Meta:
        model = Category
        fields = "__all__"


class HeroSlideAdminForm(forms.ModelForm):
    image = forms.CharField(required=False, help_text="An existing URL, or use the image upload field below.")
    image_upload = forms.ImageField(required=False, help_text="Optional. Upload a hero image.")

    class Meta:
        model = HeroSlide
        fields = "__all__"

    def clean(self):
        data = super().clean()
        if not data.get("image") and not data.get("image_upload"):
            raise ValidationError("Provide an image URL or upload a new image.")
        return data


class OrderAdminForm(forms.ModelForm):
    reward_variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.none(), required=False,
        label="Fulfil pending loyalty reward with",
        help_text="Choose an in-stock variant from the earned category, then save the order.",
    )

    class Meta:
        model = Order
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        order = self.instance
        if order and order.pk and order.payment_status == "paid" and order.reward_category_id and not order.reward_fulfilled:
            self.fields["reward_variant"].queryset = ProductVariant.objects.select_related("product").filter(
                product__category_id=order.reward_category_id, product__visibility=True, stock__gt=0,
            ).order_by("product__name", "size", "color")
        else:
            self.fields.pop("reward_variant")

    def clean_reward_variant(self):
        variant = self.cleaned_data.get("reward_variant")
        if not variant:
            return None
        order = self.instance
        if (not order.pk or order.payment_status != "paid" or order.reward_fulfilled
                or variant.product.category_id != order.reward_category_id or variant.stock < 1):
            raise ValidationError("Choose an in-stock variant from this order's earned category.")
        return variant

    def clean_order_status(self):
        status = self.cleaned_data["order_status"]
        if self.instance.pk and status == "cancelled" and self.instance.order_status != "cancelled":
            raise ValidationError("Use the Cancel selected unpaid orders action to release reservations.")
        return status
