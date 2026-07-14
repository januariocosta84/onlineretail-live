"""Central role registry.

Roles are implemented as Django auth Groups (for permission checks) plus
profile models (which carry role-specific data such as address/mobile).
To add a new role: add a constant, a choice, and a ROLE_DEFINITIONS entry —
nothing else in the codebase needs to change.
"""

from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from olretail.models import Buyer, Courier, Seller

BUYER_GROUP = "Buyer"
SELLER_GROUP = "Seller"
COURIER_GROUP = "Courier"

ROLE_BUYER = "buyer"
ROLE_SELLER = "seller"
ROLE_BUYER_SELLER = "buyer_seller"
ROLE_COURIER = "courier"

ACCOUNT_TYPE_CHOICES = [
    (ROLE_BUYER, _("Buyer — browse products, contact sellers and post comments")),
    (ROLE_SELLER, _("Seller — list and manage products for sale")),
    (ROLE_BUYER_SELLER, _("Buyer & Seller — everything in one account")),
]
# Courier is intentionally NOT self-registerable — an admin grants it from
# the dashboard, since it carries the ability to confirm deliveries.

ROLE_DEFINITIONS = {
    ROLE_BUYER: {"groups": (BUYER_GROUP,), "profiles": (Buyer,)},
    ROLE_SELLER: {"groups": (SELLER_GROUP,), "profiles": (Seller,)},
    ROLE_BUYER_SELLER: {
        "groups": (BUYER_GROUP, SELLER_GROUP),
        "profiles": (Buyer, Seller),
    },
    ROLE_COURIER: {"groups": (COURIER_GROUP,), "profiles": (Courier,)},
}


def assign_role(user, role, *, address, mobile):
    """Attach the groups and profiles for `role` to `user` (idempotent)."""
    definition = ROLE_DEFINITIONS[role]
    for group_name in definition["groups"]:
        group, _created = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
    for profile_model in definition["profiles"]:
        profile_model.objects.get_or_create(
            user=user, defaults={"address": address, "mobile": mobile}
        )


def is_buyer(user):
    """Buyer capability. Staff accounts administer the platform and never
    act as buyers, even if an old profile/group is attached to them."""
    if not user.is_authenticated or user.is_staff:
        return False
    return hasattr(user, "buyer") or user.groups.filter(name=BUYER_GROUP).exists()


def is_seller(user):
    """Seller capability. Staff accounts are excluded (see is_buyer)."""
    if not user.is_authenticated or user.is_staff:
        return False
    return hasattr(user, "seller")


def is_courier(user):
    """Courier capability. Staff accounts are excluded (see is_buyer)."""
    if not user.is_authenticated or user.is_staff:
        return False
    return hasattr(user, "courier")
