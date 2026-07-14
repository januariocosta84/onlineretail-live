from .models import AuditLog


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_action(request, action, target, detail=""):
    AuditLog.objects.create(
        admin=request.user,
        action=action,
        target=str(target)[:255],
        detail=detail,
        ip_address=client_ip(request),
    )
