"""Store domain models. IDs accept legacy Prisma cuid values during import."""
from decimal import Decimal
from uuid import uuid4
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify


def new_id():
    return uuid4().hex


class Timestamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Category(Timestamped):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True)
    description = models.TextField(blank=True)
    image = models.CharField(max_length=500, blank=True)
    order = models.PositiveIntegerField(default=0)
    visible = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Collection(Timestamped):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True)
    description = models.TextField(blank=True)
    image = models.CharField(max_length=500, blank=True)
    visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Tag(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    def __str__(self):
        return self.name


class Product(Timestamped):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    name = models.CharField(max_length=240)
    slug = models.SlugField(max_length=260, unique=True)
    sku = models.CharField(max_length=100, unique=True, null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    images = models.JSONField(default=list, blank=True)
    gallery_images = models.JSONField(default=list, blank=True)
    colors = models.JSONField(default=list, blank=True)
    material = models.CharField(max_length=200, blank=True)
    care_instructions = models.TextField(blank=True)
    featured = models.BooleanField(default=False)
    best_seller = models.BooleanField(default=False)
    new_arrival = models.BooleanField(default=True)
    visibility = models.BooleanField(default=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")
    collections = models.ManyToManyField(Collection, blank=True, related_name="products")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["visibility", "created_at"])]

    def __str__(self):
        return self.name

    @property
    def current_price(self):
        return self.discount_price if self.discount_price is not None else self.price

    @property
    def primary_image(self):
        return self.images[0] if self.images else ""

    @property
    def in_stock(self):
        return self.variants.filter(stock__gt=0).exists()

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class ProductVariant(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    size = models.CharField(max_length=40)
    color = models.CharField(max_length=100, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    additional_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["size", "color"]
        constraints = [models.UniqueConstraint(fields=["product", "size", "color"], name="unique_product_size_color")]

    def __str__(self):
        return f"{self.product.name} — {self.size} {self.color or ''}"


class PromoCode(Timestamped):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    code = models.CharField(max_length=80, unique=True)
    influencer_name = models.CharField(max_length=160)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("100.00"))])
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))])
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    current_uses = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


class Order(Timestamped):
    STATUS = [(value, value.replace("_", " ").title()) for value in ("pending", "confirmed", "processing", "shipped", "delivered", "cancelled")]
    PAYMENT = [(value, value.title()) for value in ("pending", "paid", "failed", "refunded")]
    PAYMENT_METHOD = [("manual", "Manual / QR"), ("esewa", "eSewa UAT")]
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    order_number = models.CharField(max_length=50, unique=True)
    customer_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, db_index=True)
    email = models.EmailField(blank=True)
    delivery_address = models.TextField()
    city = models.CharField(max_length=160, blank=True)
    additional_notes = models.TextField(blank=True)
    delivery_zone = models.CharField(max_length=20, default="inside")
    delivery_charge = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    payment_screenshot = models.CharField(max_length=500, blank=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT, default="pending")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD, default="manual")
    order_status = models.CharField(max_length=30, choices=STATUS, default="pending")
    esewa_transaction_uuid = models.CharField(max_length=100, null=True, blank=True, unique=True)
    esewa_product_code = models.CharField(max_length=100, blank=True)
    esewa_status = models.CharField(max_length=30, blank=True)
    esewa_ref_id = models.CharField(max_length=100, blank=True)
    reward_category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="reward_orders")
    reward_fulfilled = models.BooleanField(default=False)
    promo_code = models.ForeignKey(PromoCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    review_email_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="order_items")
    product_name = models.CharField(max_length=240)
    product_image = models.CharField(max_length=500, blank=True)
    size = models.CharField(max_length=40)
    color = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()
    is_reward_item = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.quantity} × {self.product_name}"


class LoyaltyProgress(Timestamped):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    phone = models.CharField(max_length=40, db_index=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="loyalty_progress")
    purchase_count = models.PositiveIntegerField(default=0)
    free_items_redeemed = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["phone", "category"], name="unique_phone_category_loyalty")]
        verbose_name_plural = "Loyalty progress"

    def __str__(self):
        return f"{self.phone}: {self.category.name}"


class Message(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} — {self.created_at:%Y-%m-%d}"


class Review(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviews")
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviews")
    review_token = models.CharField(max_length=100, unique=True, null=True, blank=True)
    customer_email = models.EmailField(blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    name = models.CharField(max_length=160)
    rating = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    avatar = models.CharField(max_length=500, blank=True)
    approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.rating}/5)"


class HeroSlide(Timestamped):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    title = models.CharField(max_length=240)
    subtitle = models.TextField(blank=True)
    image = models.CharField(max_length=500, blank=True)
    link = models.CharField(max_length=500, blank=True)
    button_text = models.CharField(max_length=100, blank=True)
    order = models.PositiveIntegerField(default=0)
    visible = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.title


class HomepageSection(Timestamped):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    key = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=240)
    subtitle = models.TextField(blank=True)
    visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    content = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.title


class PromoBanner(Timestamped):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    text = models.CharField(max_length=500)
    link = models.CharField(max_length=500, blank=True)
    visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.text[:80]


class Setting(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


class NewsletterSubscriber(Timestamped):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)


class Visitor(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_id, editable=False)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    path = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.path
