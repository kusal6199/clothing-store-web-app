"""Deployment checks for settings that would make eSewa UAT reject requests."""
from django.conf import settings
from django.core.checks import Error, register


@register()
def esewa_uat_configuration(app_configs, **kwargs):
    if (settings.ESEWA_MERCHANT_CODE == "EPAYTEST"
            and settings.ESEWA_SECRET_KEY.endswith("(")):
        return [Error(
            "The configured eSewa UAT key contains the trailing-parenthesis typo from the ePay page.",
            hint="Use the UAT key from eSewa's official Test Credentials page (without the trailing parenthesis).",
            id="shop.E001",
        )]
    return []
