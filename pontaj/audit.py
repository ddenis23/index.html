from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import AuditLog


def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    return forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')


def log(request, action, target, summary, employee=None, before='', after='', user=None):
    if user is None:
        user = getattr(request, 'user', None)
    if user is not None and not user.is_authenticated:
        user = None
    AuditLog.objects.create(
        user=user,
        username=user.username if user else 'anonim',
        action=action,
        target=target,
        employee=employee,
        summary=summary[:300],
        before=str(before or '')[:200],
        after=str(after or '')[:200],
        ip=client_ip(request),
    )


@receiver(user_logged_in)
def _log_login(sender, request, user, **kwargs):
    log(request, AuditLog.Action.LOGIN, 'cont', f'{user.username} s-a autentificat', user=user)
