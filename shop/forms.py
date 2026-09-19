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
    comment = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}))
