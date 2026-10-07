from .roles import ROLE_LABELS, can_edit, role_of


def roles(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    return {
        'can_edit': can_edit(user),
        'is_superadmin': user.is_superuser,
        'role_label': ROLE_LABELS[role_of(user)],
    }
