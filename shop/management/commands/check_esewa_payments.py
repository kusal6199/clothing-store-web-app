"""Recheck eSewa UAT orders whose browser callback did not settle them."""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from shop.esewa import configured, reconcile
from shop.models import Order


class Command(BaseCommand):
    help = "Check eSewa UAT orders that have been pending for at least five minutes."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if not configured():
            raise CommandError("Set ESEWA_SECRET_KEY to enable eSewa UAT status checks.")
        if options["limit"] < 1:
            raise CommandError("--limit must be positive.")
        cutoff = timezone.now() - timedelta(minutes=5)
        orders = Order.objects.filter(payment_method="esewa", payment_status="pending",
                                      created_at__lte=cutoff).exclude(order_status="cancelled").order_by("created_at")[:options["limit"]]
        for order in orders:
            self.stdout.write(f"{order.order_number}: {reconcile(order)}")
