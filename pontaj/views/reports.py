"""Statistici, istoricul modificarilor si exporturi."""

import datetime as dt
from collections import defaultdict

from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import render

from .. import exports
from .. import grid as g
from ..audit import log
from ..models import AuditLog, Code, Employee, Entry, Section
from ..roles import admin_required, superadmin_required
from .schedule import _shift_month, parse_month

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _delta(cur, prev):
    if not prev:
        return None
    return round((cur - prev) / prev * 100)


@admin_required
def stats(request):
    first = parse_month(request)
    rows, grid = g.month_stats(first.year, first.month)
    prev = _shift_month(first, -1)
    _, prev_grid = g.month_stats(prev.year, prev.month)
    t, pt = grid.totals, prev_grid.totals
    n = len(rows) or 1

    kpis = [
        ('Ore lucrate', t.hours, _delta(t.hours, pt.hours), f'{t.hours / n:.0f} h / angajat'),
        ('Ture SP', g.fmt_num(t.sp) or 0, _delta(t.sp, pt.sp), 'inclusiv bonus vara'),
        ('Zile concediu', t.co, _delta(t.co, pt.co), 'CO'),
        ('Zile medical', t.cm, _delta(t.cm, pt.cm), 'CM'),
        ('Fara plata', t.lfp, _delta(t.lfp, pt.lfp), 'LFP'),
    ]

    by_section = defaultdict(int)
    for r in rows.values():
        by_section[r.employee.section_id] += r.stats.hours
    sections = [(s, by_section[s.id]) for s in Section.objects.all() if s.id in by_section]
    max_sec = max((h for _, h in sections), default=0) or 1

    trend = []
    for i in range(5, -1, -1):
        m = _shift_month(first, -i)
        _, mg = g.month_stats(m.year, m.month)
        trend.append((g.MONTHS[m.month - 1][:3], mg.totals.hours, mg.totals.sp, m == first))
    max_trend = max((h for _, h, _, _ in trend), default=0) or 1

    sort = request.GET.get('sort', 'hours')
    keys = {'hours': lambda r: -r.stats.hours, 'name': lambda r: r.employee.name,
            'sp': lambda r: -r.stats.sp, 'co': lambda r: -r.stats.co, 'worked': lambda r: -r.stats.worked}
    table = sorted(rows.values(), key=keys.get(sort, keys['hours']))
    max_emp = max((r.stats.hours for r in table), default=0) or 1

    # Ce cere atentie: concedii neaprobate si zile trecute fara pontaj.
    last_day = min(grid.days[-1], g.today())
    pending_co = Entry.objects.select_related('employee').filter(
        code=Code.CO, approved=False, day__gte=g.today() - dt.timedelta(days=7)).order_by('day')[:20]
    gaps = []
    if last_day >= grid.days[0]:
        for r in table:
            missing = [c.day for c in r.cells if c.active and not c.entry and c.day <= last_day]
            if missing:
                gaps.append((r.employee, len(missing), missing[-1]))
        gaps.sort(key=lambda x: -x[1])

    return render(request, 'pontaj/stats.html', {
        'month': first, 'title': f'{g.MONTHS[first.month - 1]} {first.year}',
        'prev': prev, 'next': _shift_month(first, 1),
        'kpis': kpis, 'sections': sections, 'max_sec': max_sec,
        'trend': trend, 'max_trend': max_trend,
        'table': table, 'max_emp': max_emp, 'sort': sort,
        'pending_co': pending_co, 'gaps': gaps[:10],
    })


@superadmin_required
def history(request):
    qs = AuditLog.objects.select_related('employee')
    f = {k: request.GET.get(k, '').strip() for k in ('user', 'target', 'action', 'emp', 'from', 'to', 'q')}
    if f['user']:
        qs = qs.filter(username=f['user'])
    if f['target']:
        qs = qs.filter(target=f['target'])
    if f['action']:
        qs = qs.filter(action=f['action'])
    if f['emp'].isdigit():
        qs = qs.filter(employee_id=f['emp'])
    for key, lookup in (('from', 'when__date__gte'), ('to', 'when__date__lte')):
        try:
            qs = qs.filter(**{lookup: dt.date.fromisoformat(f[key])})
        except ValueError:
            pass
    if f['q']:
        qs = qs.filter(summary__icontains=f['q'])
    if not request.GET.get('logins') and not f['action']:
        qs = qs.exclude(action=AuditLog.Action.LOGIN)

    page = Paginator(qs, 50).get_page(request.GET.get('page'))
    since = g.today() - dt.timedelta(days=30)
    activity = (AuditLog.objects.filter(when__date__gte=since).exclude(action=AuditLog.Action.LOGIN)
                .values('username').annotate(n=Count('id')).order_by('-n'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'pontaj/history.html', {
        'page': page, 'f': f, 'activity': activity, 'query': params.urlencode(),
        'usernames': AuditLog.objects.values_list('username', flat=True).distinct().order_by('username'),
        'targets': ['pontaj', 'angajat', 'sectie', 'bonus', 'cont'],
        'actions': AuditLog.Action.choices,
        'employees': Employee.objects.order_by('name'),
        'show_logins': bool(request.GET.get('logins')),
    })


def _download(data, filename):
    response = HttpResponse(data, content_type=XLSX)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@admin_required
def export_month(request):
    first = parse_month(request)
    data, filename = exports.month_xlsx(first.year, first.month)
    log(request, AuditLog.Action.EXPORT, 'pontaj', f'Export XLSX {filename}')
    return _download(data, filename)


@admin_required
def export_week(request):
    try:
        monday = g.monday_of(dt.date.fromisoformat(request.GET.get('sapt', '')))
    except ValueError:
        monday = g.monday_of(g.today())
    data, filename = exports.week_xlsx(monday)
    log(request, AuditLog.Action.EXPORT, 'pontaj', f'Export XLSX {filename}')
    return _download(data, filename)
