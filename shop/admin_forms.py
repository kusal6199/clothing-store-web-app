from django import forms
from django.core.exceptions import ValidationError
from .models import Category, HeroSlide, Product


class ProductAdminForm(forms.ModelForm):
    image_upload = forms.ImageField(required=False, help_text="Optional. Add a main product image.")
    gallery_upload = forms.ImageField(required=False, help_text="Optional. Add a detail gallery image.")

    class Meta:
        model = Product
        fields = "__all__"


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
