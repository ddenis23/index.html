"""Roluri: superadmin (is_superuser) > admin (is_staff) > angajat (vizualizare)."""

from functools import wraps

from django.core.exceptions import PermissionDenied

SUPERADMIN, ADMIN, VIEWER = 'superadmin', 'admin', 'angajat'
ROLE_LABELS = {SUPERADMIN: 'Superadmin', ADMIN: 'Admin', VIEWER: 'Angajat'}


def role_of(user):
    if user.is_superuser:
        return SUPERADMIN
    if user.is_staff:
        return ADMIN
    return VIEWER


def can_edit(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def _require(check):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


admin_required = _require(can_edit)
superadmin_required = _require(lambda u: u.is_superuser)
