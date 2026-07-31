def finance_flags(request):
    """Whether the current user is a finance-only staff account (see
    FINANCE_GROUP_NAME / _is_finance_only in .decorators) — lets
    dashboard/base.html hide sidebar links to sections that account can't
    reach anyway, instead of showing a link that just bounces them back."""
    from .decorators import _is_finance_only  # local import: avoid app-load cycle

    if not request.user.is_authenticated:
        return {"is_finance_only": False}
    return {"is_finance_only": _is_finance_only(request.user)}
