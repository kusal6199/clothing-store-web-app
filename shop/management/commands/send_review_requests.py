"""Send one review request per eligible paid order. Schedule once daily."""
from datetime import timedelta
from html import escape
from secrets import token_urlsafe
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from shop.models import Order, Review


class Command(BaseCommand):
    help = "Send review requests for paid orders placed 2–3 days ago."

    def handle(self, *args, **options):
        now = timezone.now()
        orders = Order.objects.filter(
            payment_status="paid", email__isnull=False,
            review_email_sent_at__isnull=True,
            created_at__gte=now - timedelta(days=3),
            created_at__lte=now - timedelta(days=2),
        ).exclude(email="").exclude(order_status="cancelled").prefetch_related("items")
        sent = 0
        for order in orders:
            items = {item.product_id: item for item in order.items.all() if item.product_id}
            if not items:
                continue
            links = []
            for product_id, item in items.items():
                review = Review.objects.filter(order=order, product_id=product_id).first()
                if review is None:
                    review = Review.objects.create(
                        order=order, product_id=product_id, review_token=token_urlsafe(32),
                        customer_email=order.email, name=order.customer_name,
                        comment="", approved=False,
                    )
                elif not review.review_token:
                    review.review_token = token_urlsafe(32)
                    review.save(update_fields=["review_token"])
                links.append((item.product_name, f"{settings.SITE_URL}/review/{review.review_token}/"))
            plain = "\n".join(f"{name}: {url}" for name, url in links)
            html_links = "".join(f'<li><a href="{escape(url)}">Review {escape(name)}</a></li>' for name, url in links)
            email = EmailMultiAlternatives(
                subject=f"How was your order {order.order_number}?",
                body=f"Hi {order.customer_name},\n\nThanks for your order. Leave a review for your items:\n{plain}\n",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[order.email],
            )
            email.attach_alternative(f"<p>Hi {escape(order.customer_name)}, thanks for your order.</p><ul>{html_links}</ul>", "text/html")
            email.send(fail_silently=False)
            Order.objects.filter(pk=order.pk, review_email_sent_at__isnull=True).update(review_email_sent_at=timezone.now())
            sent += 1
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} review request(s)."))
