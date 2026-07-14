from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Immutable trail of administrative actions taken in the dashboard."""

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    action = models.CharField(max_length=60)
    target = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.admin} {self.action} {self.target}"
