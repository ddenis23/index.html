from django.utils import timezone

from . import store


def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    return forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')


def log(request, action, target, summary, employee=None, before='', after=''):
    """Scrie in istoric cine a facut ce. `action`: create | update | delete | login | export."""
    store.add_log(row(request, action, target, summary, employee, before, after))


def row(request, action, target, summary, employee=None, before='', after=''):
    user = getattr(request, 'user', None)
    return {
        'when': timezone.now().isoformat(timespec='seconds'),
        'user': user.username if user and user.is_authenticated else 'anonim',
        'action': action,
        'target': target,
        'emp': employee.id if employee else None,
        'emp_name': employee.name if employee else None,
        'summary': summary[:300],
        'before': str(before or '')[:200] or None,
        'after': str(after or '')[:200] or None,
        'ip': client_ip(request),
    }
