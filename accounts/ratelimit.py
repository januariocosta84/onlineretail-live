"""Lightweight per-IP request throttle for auth-adjacent views (login,
registration, password reset) — no external dependency, backed by Django's
cache framework (LocMemCache by default; point CACHES at something shared
like Redis for a multi-process deployment so the limit applies across
workers)."""

from functools import wraps

from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils.translation import gettext as _


def rate_limit(key, limit=10, window_seconds=300):
    """Allow at most `limit` POSTs per `window_seconds` per client IP.
    Only POST is throttled — GETs (viewing the form) always pass through."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if request.method == "POST":
                ip = request.META.get("REMOTE_ADDR", "unknown")
                cache_key = f"ratelimit:{key}:{ip}"
                attempts = cache.get(cache_key, 0)
                if attempts >= limit:
                    messages.error(
                        request,
                        _("Too many attempts. Please wait a few minutes and try again."),
                    )
                    return redirect(request.path)
                cache.set(cache_key, attempts + 1, window_seconds)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
