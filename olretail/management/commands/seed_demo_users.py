"""Seed 100 demo users (90 sellers + 10 buyers) with realistic products,
carts, and orders for testing.

Usage:
    python manage.py seed_demo_users
    python manage.py seed_demo_users --reset   # wipe previously seeded test_* data first
"""

import io
import random
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.roles import ROLE_BUYER, ROLE_SELLER, assign_role
from olretail.models import (
    Buyer, Cart, Category, City, Country, Product, ProductStatus, Seller,
)
from olretail.payment_models import (
    Order, OrderStatus, Payment, PaymentMethod, PaymentStatus, SellerBalance,
    Transaction, TransactionType,
)

PASSWORD = "C0001395"
TOTAL_USERS = 100
SELLER_COUNT = 90
BUYER_COUNT = 10

FIRST_NAMES = [
    "Domingos", "Abilio", "Francisco", "Joaquim", "Mateus", "Alfredo", "Marcelino",
    "Adao", "Cristovao", "Egidio", "Filomeno", "Gil", "Horacio", "Ivo", "Jacinto",
    "Leandro", "Marito", "Natalino", "Osorio", "Paulino", "Rogerio", "Sebastiao",
    "Tomas", "Valente", "Zeferino", "Aderito", "Benjamim", "Celestino", "Domingas",
    "Angelina", "Bendita", "Cesaltina", "Dulce", "Ermelinda", "Fatima", "Graciana",
    "Herminia", "Ilda", "Julieta", "Laurentina", "Madalena", "Natercia", "Odete",
    "Perpetua", "Rosa", "Salustiana", "Teodora", "Umbelina", "Veronica", "Xanana",
]
LAST_NAMES = [
    "da Costa", "Soares", "Guterres", "Ximenes", "Fernandes", "Amaral", "Belo",
    "Pinto", "Freitas", "Martins", "Sarmento", "Ruak", "Gusmao", "Alves", "Carvalho",
    "Barros", "Correia", "Dias", "Lopes", "Moreira", "Nunes", "Pereira", "Ribeiro",
    "Salsinha", "Tilman", "Vasconcelos",
]

DILI_AREAS = [
    "Comoro, Dili", "Bidau, Dili", "Colmera, Dili", "Audian, Dili", "Farol, Dili",
    "Fatuhada, Dili", "Kaikoli, Dili", "Lahane, Dili", "Bairro Pite, Dili",
    "Becora, Dili", "Taibesi, Dili", "Vila Verde, Dili", "Metiaut, Dili",
]

# name -> ((price_min, price_max), (qty_min, qty_max))
CATEGORY_PRODUCTS = {
    "Agriculture": [
        ("Organic Rice 25kg Bag", (15, 25), (20, 100)),
        ("Fresh Coffee Beans Arabica 1kg", (6, 14), (15, 80)),
        ("Hybrid Corn Seeds Pack", (3, 8), (30, 150)),
        ("Water Buffalo (Adult)", (400, 900), (1, 3)),
        ("Chicken Feed 50kg", (18, 30), (10, 60)),
        ("Garden Hoe - Steel", (5, 12), (10, 50)),
        ("Irrigation Water Pump", (60, 180), (2, 15)),
        ("Vanilla Beans Premium 100g", (10, 20), (10, 40)),
        ("Cassava Tubers 10kg", (4, 9), (20, 100)),
        ("Fertilizer NPK 25kg", (12, 22), (15, 70)),
    ],
    "Electronics": [
        ("Samsung Galaxy A14 Smartphone", (140, 220), (3, 20)),
        ("Sony Bluetooth Speaker", (25, 60), (5, 30)),
        ("LED TV 43-inch Smart", (220, 380), (2, 10)),
        ("JBL Wireless Earbuds", (20, 45), (5, 40)),
        ("Power Bank 20000mAh", (12, 25), (10, 60)),
        ("Digital Camera Canon EOS", (300, 650), (1, 6)),
        ("Rice Cooker 1.8L", (18, 35), (5, 30)),
        ("Electric Fan Stand 16-inch", (15, 30), (5, 25)),
        ("Home Theater System", (80, 200), (2, 10)),
        ("USB Flash Drive 64GB", (5, 12), (20, 100)),
    ],
    "Food": [
        ("Timor-Leste Arabica Coffee 500g", (4, 9), (20, 100)),
        ("Local Honey 250ml", (5, 10), (15, 60)),
        ("Dried Fish Pack 1kg", (6, 12), (10, 50)),
        ("Instant Noodles Box (30pcs)", (8, 14), (10, 60)),
        ("Coconut Oil 1L", (4, 8), (15, 70)),
        ("Roasted Peanuts 500g", (2, 5), (20, 90)),
        ("Palm Sugar Block", (2, 4), (20, 100)),
        ("Bottled Water 12-pack", (3, 6), (30, 150)),
        ("Chili Sauce Homemade", (2, 4), (20, 80)),
        ("Banana Chips 200g", (2, 4), (20, 90)),
    ],
    "Healthcare items": [
        ("Digital Thermometer", (4, 10), (10, 60)),
        ("Blood Pressure Monitor", (18, 40), (5, 25)),
        ("First Aid Kit", (8, 20), (10, 40)),
        ("Face Masks (Box of 50)", (5, 10), (20, 100)),
        ("Hand Sanitizer 500ml", (3, 7), (20, 100)),
        ("Vitamin C Tablets", (4, 9), (20, 80)),
        ("Wheelchair - Foldable", (80, 180), (1, 8)),
        ("Nebulizer Machine", (25, 55), (2, 15)),
        ("Glucose Test Strips", (10, 20), (10, 50)),
        ("Reading Glasses +2.0", (3, 8), (15, 60)),
    ],
    "Housing": [
        ("2-Bedroom House for Rent - Dili", (150, 350), (1, 1)),
        ("Studio Apartment - Comoro", (80, 150), (1, 1)),
        ("Land Plot 500m2 - Baucau", (5000, 15000), (1, 1)),
        ("3-Bedroom Family House", (250, 500), (1, 1)),
        ("Office Space for Rent", (120, 400), (1, 2)),
        ("Boarding Room - Bidau", (40, 90), (1, 3)),
        ("Warehouse for Rent", (200, 600), (1, 1)),
        ("Furnished Apartment", (150, 300), (1, 1)),
        ("Guesthouse Room Monthly", (60, 120), (1, 4)),
        ("Commercial Shop Space", (150, 450), (1, 1)),
    ],
    "Informatics": [
        ("Dell Laptop Inspiron 15", (280, 550), (2, 15)),
        ("HP Wireless Mouse", (6, 15), (10, 60)),
        ("Mechanical Keyboard RGB", (20, 45), (5, 30)),
        ("27-inch Monitor Full HD", (90, 180), (3, 15)),
        ("External Hard Drive 1TB", (35, 60), (5, 30)),
        ("Wi-Fi Router Dual Band", (18, 40), (5, 30)),
        ("Laptop Cooling Pad", (8, 18), (10, 40)),
        ("Webcam HD 1080p", (10, 25), (10, 40)),
        ("Printer All-in-One", (60, 130), (3, 15)),
        ("Laptop Bag 15.6-inch", (8, 20), (10, 50)),
    ],
    "Motorcycles": [
        ("Honda Beat 2022", (1200, 1800), (1, 4)),
        ("Yamaha Mio 125", (1000, 1600), (1, 4)),
        ("Motorcycle Helmet - Full Face", (15, 40), (10, 50)),
        ("Motorcycle Tire 80/90-17", (12, 25), (10, 60)),
        ("Scooter Kymco Like", (1300, 1900), (1, 3)),
        ("Motorcycle Battery 12V", (15, 30), (10, 40)),
        ("Chain and Sprocket Kit", (10, 25), (10, 40)),
        ("Motorcycle Rain Cover", (5, 12), (15, 60)),
        ("LED Headlight Bulb", (4, 10), (20, 80)),
        ("Motorcycle Side Mirror Pair", (5, 12), (15, 60)),
    ],
    "Services": [
        ("Home Cleaning Service", (10, 30), (5, 40)),
        ("Motorcycle Repair Service", (5, 20), (5, 40)),
        ("Private Tutoring - English", (5, 15), (5, 30)),
        ("Photography for Events", (50, 150), (2, 15)),
        ("Plumbing Service", (10, 30), (5, 30)),
        ("Electrical Installation", (15, 40), (5, 30)),
        ("Catering for Events", (80, 250), (2, 15)),
        ("Graphic Design Service", (10, 40), (5, 30)),
        ("Computer Repair Service", (8, 25), (5, 30)),
        ("Airport Transfer Service", (8, 20), (5, 40)),
    ],
    "Vehicles": [
        ("Toyota Hilux 2019", (18000, 26000), (1, 2)),
        ("Mitsubishi Pajero 2018", (16000, 24000), (1, 2)),
        ("Toyota Avanza 2020", (12000, 18000), (1, 2)),
        ("Car Battery 12V 70Ah", (60, 120), (5, 25)),
        ("Car Tire 195/65R15", (40, 80), (10, 40)),
        ("Dashboard Camera", (25, 60), (5, 30)),
        ("Car Seat Covers Set", (20, 45), (10, 40)),
        ("Roof Rack Universal", (40, 90), (5, 20)),
        ("Car Air Freshener Pack", (2, 5), (30, 100)),
        ("Towing Rope Heavy Duty", (8, 18), (10, 40)),
    ],
}

DESCRIPTION_TEMPLATES = [
    "{name} in excellent condition. Available now in {location} — message the seller for bulk pricing or delivery options.",
    "Quality {name} at a fair price. Located in {location}. Serious buyers only, fast response guaranteed.",
    "Selling {name}, well maintained and ready for immediate use. Pick up in {location} or arrange delivery.",
    "Brand new {name} available in {location}. Great value — contact for more photos or details.",
    "{name} for sale in {location}. Genuine product, price is slightly negotiable for bulk orders.",
]

CONDITIONS = ["New", "Second Hand"]

PLACEHOLDER_COLORS = {
    "Agriculture": (76, 153, 63),
    "Electronics": (52, 101, 164),
    "Food": (222, 145, 33),
    "Healthcare items": (204, 51, 63),
    "Housing": (128, 96, 56),
    "Informatics": (60, 60, 90),
    "Motorcycles": (40, 40, 40),
    "Services": (100, 90, 160),
    "Vehicles": (30, 90, 90),
}


def make_placeholder_image(category_title):
    """Small solid-color JPEG with the category name — good enough as a
    stand-in product photo without needing real product photography."""
    from PIL import Image, ImageDraw

    color = PLACEHOLDER_COLORS.get(category_title, (90, 90, 90))
    img = Image.new("RGB", (600, 450), color)
    draw = ImageDraw.Draw(img)
    text = category_title
    bbox = draw.textbbox((0, 0), text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((600 - tw) / 2, (450 - th) / 2), text, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


class Command(BaseCommand):
    help = "Seed 100 demo users (90 sellers, 10 buyers) with products, carts and orders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Delete previously seeded test_* users (and their data) before seeding.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()

        if User.objects.filter(username="test_1").exists():
            self.stderr.write(self.style.ERROR(
                "test_1 already exists. Re-run with --reset to wipe previously seeded demo data first."
            ))
            return

        country = Country.objects.get_or_create(country="Timor Leste")[0]
        city = City.objects.get_or_create(city="Dili", defaults={"country": country})[0]
        categories = list(Category.objects.all())
        if len(categories) < 9:
            self.stderr.write(self.style.ERROR(
                f"Expected 9 categories, found {len(categories)}. Aborting."
            ))
            return

        placeholder_cache = {}

        with transaction.atomic():
            sellers = self._create_sellers(country, city)
            buyers = self._create_buyers()
            self._create_products(sellers, categories, city, country, placeholder_cache)
            self._create_orders_and_carts(buyers)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {SELLER_COUNT} sellers, {BUYER_COUNT} buyers, "
            f"{Product.objects.filter(seller__user__username__startswith='test_').count()} products."
        ))

    def _reset(self):
        test_users = User.objects.filter(username__startswith="test_")
        count = test_users.count()
        if not count:
            return
        self.stdout.write(f"Removing {count} previously seeded test_* users and their data…")
        with transaction.atomic():
            test_orders = Order.objects.filter(
                Q(buyer__username__startswith="test_")
                | Q(seller__user__username__startswith="test_")
            )
            Transaction.objects.filter(order__in=test_orders).delete()
            Payment.objects.filter(orders__in=test_orders).distinct().delete()
            test_orders.delete()
            Cart.objects.filter(buyer__username__startswith="test_").delete()
            Product.objects.filter(seller__user__username__startswith="test_").delete()
            SellerBalance.objects.filter(seller__user__username__startswith="test_").delete()
            test_users.delete()

    def _random_name(self):
        return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)

    def _random_mobile(self):
        return f"7{random.randint(7,8)}{random.randint(100000, 999999)}"

    def _make_user(self, index):
        username = f"test_{index}"
        first, last = self._random_name()
        user = User.objects.create_user(
            username=username,
            email=f"{username}@timormart.test",
            password=PASSWORD,
            first_name=first,
            last_name=last,
        )
        return user

    def _create_sellers(self, country, city):
        sellers = []
        for i in range(1, SELLER_COUNT + 1):
            user = self._make_user(i)
            address = random.choice(DILI_AREAS)
            mobile = self._random_mobile()
            assign_role(user, ROLE_SELLER, address=address, mobile=mobile)
            seller = Seller.objects.get(user=user)
            seller.payment_instructions = (
                f"BNCTL Bank Transfer — Account holder: {user.get_full_name()}, "
                f"Account #: {random.randint(10**9, 10**10-1)}"
            )
            seller.save()
            sellers.append(seller)
        self.stdout.write(f"Created {len(sellers)} sellers (test_1..test_{SELLER_COUNT}).")
        return sellers

    def _create_buyers(self):
        buyers = []
        for i in range(SELLER_COUNT + 1, TOTAL_USERS + 1):
            user = self._make_user(i)
            address = random.choice(DILI_AREAS)
            mobile = self._random_mobile()
            assign_role(user, ROLE_BUYER, address=address, mobile=mobile)
            buyers.append(Buyer.objects.get(user=user))
        self.stdout.write(
            f"Created {len(buyers)} buyers (test_{SELLER_COUNT + 1}..test_{TOTAL_USERS})."
        )
        return buyers

    def _create_products(self, sellers, categories, city, country, placeholder_cache):
        created = 0
        for seller in sellers:
            for category in categories:
                catalog = CATEGORY_PRODUCTS.get(category.title)
                if not catalog:
                    continue
                name, price_range, qty_range = random.choice(catalog)
                price = Decimal(str(round(random.uniform(*price_range), 2)))
                quantity = random.randint(*qty_range)
                location_label = f"{city.city}, {country.country}"
                description = random.choice(DESCRIPTION_TEMPLATES).format(
                    name=name, location=location_label
                )
                # Roughly 85% published, rest spread across other moderation states
                # so the admin dashboard has something to moderate too.
                status_roll = random.random()
                if status_roll < 0.85:
                    status = ProductStatus.APPROVED
                elif status_roll < 0.93:
                    status = ProductStatus.PENDING
                elif status_roll < 0.97:
                    status = ProductStatus.CHANGES_REQUESTED
                else:
                    status = ProductStatus.SUSPENDED

                product = Product(
                    name=name,
                    category=category,
                    price=price,
                    description=description,
                    country=country,
                    item_location=city,
                    quantity=quantity,
                    seller=seller,
                    status=status,
                    condition=random.choice(CONDITIONS),
                    featured=(status == ProductStatus.APPROVED and random.random() < 0.02),
                )
                product.save()

                if category.title not in placeholder_cache:
                    placeholder_cache[category.title] = make_placeholder_image(category.title)
                filename = f"{product.slug}.jpg"
                product.product_image.save(
                    filename, ContentFile(placeholder_cache[category.title]), save=True
                )
                created += 1
        self.stdout.write(f"Created {created} products across {len(categories)} categories.")

    def _create_orders_and_carts(self, buyers):
        approved_products = list(
            Product.objects.filter(status=ProductStatus.APPROVED, quantity__gt=0)
        )
        if not approved_products:
            return

        status_weights = [
            (OrderStatus.DELIVERED, 4),
            (OrderStatus.PAID, 2),
            (OrderStatus.PROCESSING, 2),
            (OrderStatus.SHIPPED, 2),
            (OrderStatus.PENDING_PAYMENT, 2),
            (OrderStatus.PAYMENT_REPORTED, 1),
        ]
        statuses = [s for s, w in status_weights for _ in range(w)]

        order_count = 0
        for buyer in buyers:
            user = buyer.user

            # A few items sitting in the cart, not yet checked out.
            for product in random.sample(approved_products, k=min(3, len(approved_products))):
                Cart.objects.get_or_create(
                    buyer=user, product=product, defaults={"quantity": random.randint(1, 2)}
                )

            # A handful of historical orders across different sellers/statuses.
            order_products = random.sample(approved_products, k=min(4, len(approved_products)))
            for product in order_products:
                if product.seller.user_id == user.id:
                    continue
                quantity = random.randint(1, min(3, product.quantity))
                status = random.choice(statuses)
                payment_method = random.choice([PaymentMethod.STRIPE, PaymentMethod.BANK_TRANSFER])

                subtotal = product.price * quantity
                if payment_method == PaymentMethod.BANK_TRANSFER:
                    commission = Decimal("0")
                    payment_fee = Decimal("0")
                else:
                    commission = (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
                    fee_base_cents = int((subtotal + commission) * 100)
                    payment_fee_cents = int(fee_base_cents * 0.029) + 30
                    payment_fee = Decimal(payment_fee_cents) / Decimal("100")
                total = subtotal + commission + payment_fee

                order = Order.objects.create(
                    buyer=user,
                    seller=product.seller,
                    product=product,
                    quantity=quantity,
                    price_per_unit=product.price,
                    subtotal=subtotal,
                    commission_amount=commission,
                    payment_fee=payment_fee,
                    total=total,
                    status=status,
                    payment_method=payment_method,
                    delivery_address=buyer.address,
                    delivery_phone=buyer.mobile,
                )

                now = timezone.now()
                if status != OrderStatus.PENDING_PAYMENT:
                    order.paid_at = now
                if status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED):
                    order.shipped_at = now
                if status == OrderStatus.DELIVERED:
                    order.delivered_at = now
                if status == OrderStatus.PAYMENT_REPORTED:
                    order.payment_reported_at = now
                order.save()

                if payment_method == PaymentMethod.STRIPE and status != OrderStatus.PENDING_PAYMENT:
                    payment = Payment.objects.create(
                        stripe_payment_intent_id=f"pi_test_{order.order_number}",
                        amount_cents=int(total * 100),
                        status=PaymentStatus.SUCCEEDED,
                        payment_method_type="card",
                        succeeded_at=now,
                        webhook_received=True,
                        webhook_received_at=now,
                    )
                    order.payment = payment
                    order.save(update_fields=["payment"])

                if status != OrderStatus.PENDING_PAYMENT and commission > 0:
                    Transaction.objects.create(
                        order=order,
                        seller=product.seller,
                        amount_cents=int(commission * 100),
                        transaction_type=TransactionType.COMMISSION,
                        description=f"Commission on order {order.order_number}",
                    )
                    balance, _ = SellerBalance.objects.get_or_create(seller=product.seller)
                    balance.add_commission(int(commission * 100))

                order_count += 1

        self.stdout.write(f"Created {order_count} orders and cart items for {len(buyers)} buyers.")
