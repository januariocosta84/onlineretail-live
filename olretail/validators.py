import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB

# 4 letters (bank code) + 2 letters (country) + 2 alphanumeric (location) +
# optional 3 alphanumeric (branch) — the standard SWIFT/BIC shape.
_SWIFT_RE = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")
# 2 letters (country) + 2 digits (check digits) + up to 30 alphanumeric —
# general IBAN shape. Not a per-country length/checksum check (Timor-Leste
# isn't in the IBAN registry, so any IBAN here is for a foreign account and
# there's no single length to validate against).
_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")


def validate_image_size(image):
    """Reject uploads past a sane size cap — nothing else in the codebase
    limits product/delivery-photo upload size, which otherwise bounds only
    by available disk space."""
    if image and image.size > MAX_IMAGE_SIZE_BYTES:
        raise ValidationError(
            _("Image files must be smaller than %(max)sMB.") % {"max": MAX_IMAGE_SIZE_BYTES // (1024 * 1024)}
        )


def validate_swift_code(value):
    if value and not _SWIFT_RE.match(value.upper()):
        raise ValidationError(_("Enter a valid SWIFT/BIC code (e.g. BNUTTLDL or BNUTTLDLXXX)."))


def validate_iban(value):
    if value and not _IBAN_RE.match(value.upper().replace(" ", "")):
        raise ValidationError(_("Enter a valid IBAN (country code + digits + account identifier, no spaces)."))
