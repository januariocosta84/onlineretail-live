from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB


def validate_image_size(image):
    """Reject uploads past a sane size cap — nothing else in the codebase
    limits product/delivery-photo upload size, which otherwise bounds only
    by available disk space."""
    if image and image.size > MAX_IMAGE_SIZE_BYTES:
        raise ValidationError(
            _("Image files must be smaller than %(max)sMB.") % {"max": MAX_IMAGE_SIZE_BYTES // (1024 * 1024)}
        )
