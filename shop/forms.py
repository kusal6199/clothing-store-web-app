from django import forms
from .models import Message


class ContactForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ("name", "email", "phone", "message")
        widgets = {"message": forms.Textarea(attrs={"rows": 5})}

    def clean(self):
        data = super().clean()
        if not data.get("email") and not data.get("phone"):
            raise forms.ValidationError("Please provide an email or phone number.")
        return data


class NewsletterForm(forms.Form):
    email = forms.EmailField(max_length=254)

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


STORE_SETTING_GROUPS = (
    ("Brand and footer", ("site_name", "site_tagline", "currency", "footer_about", "footer_copyright")),
    ("Contact and social", ("phone", "email", "address", "instagram", "facebook")),
    ("Delivery", ("delivery_inside_valley", "delivery_outside_valley")),
    ("Test payment instructions", ("payment_instructions", "qr_image")),
    ("Newsletter", ("newsletter_title", "newsletter_subtitle")),
)


class StoreSettingsForm(forms.Form):
    site_name = forms.CharField(max_length=160, initial="Clothing Shop")
    site_tagline = forms.CharField(max_length=300, required=False)
    currency = forms.CharField(max_length=12, initial="Rs")
    footer_about = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    footer_copyright = forms.CharField(max_length=300, required=False)
    phone = forms.CharField(max_length=40, required=False)
    email = forms.EmailField(required=False)
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    instagram = forms.URLField(required=False)
    facebook = forms.URLField(required=False)
    delivery_inside_valley = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0, initial=100)
    delivery_outside_valley = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0, initial=200)
    payment_instructions = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    qr_image = forms.CharField(max_length=500, required=False, label="Payment QR image URL")
    newsletter_title = forms.CharField(max_length=160, required=False)
    newsletter_subtitle = forms.CharField(max_length=300, required=False)


class CheckoutForm(forms.Form):
    customer_name = forms.CharField(max_length=160, label="Full name")
    phone = forms.CharField(max_length=40)
    email = forms.EmailField(required=False)
    delivery_address = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    city = forms.CharField(max_length=160, required=False)
    additional_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    delivery_zone = forms.ChoiceField(choices=(("inside", "Inside valley"), ("outside", "Outside valley")), widget=forms.RadioSelect)
    promo_code = forms.CharField(max_length=80, required=False)
    reward_variant_id = forms.CharField(max_length=32, required=False, label="Loyalty reward", widget=forms.Select(choices=[("", "No reward selected")]))


class ReviewForm(forms.Form):
    rating = forms.IntegerField(min_value=1, max_value=5, widget=forms.Select(choices=[(n, f"{n} stars") for n in range(5, 0, -1)]))
    comment = forms.CharField(min_length=10, max_length=2000, widget=forms.Textarea(attrs={"rows": 4}))
    name = forms.CharField(max_length=80, required=False, label="Display name")
