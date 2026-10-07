"""Statistici, istoricul modificarilor, exporturi si backup."""

import datetime as dt
import json
from collections import Counter, defaultdict

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from .. import exports, store
from .. import grid as g
from ..audit import log
from ..roles import admin_required, superadmin_required
from ..store import Code, LogEntry
from .schedule import parse_month, shift_month

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _delta(cur, prev):
    if not prev:
        return None
    return round((cur - prev) / prev * 100)


@admin_required
def stats(request):
    first = parse_month(request)
    data = store.load()
    rows, grid = g.month_stats(data, first.year, first.month)
    prev = shift_month(first, -1)
    _, prev_grid = g.month_stats(data, prev.year, prev.month)
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
        by_section[r.employee.section.id] += r.stats.hours
    sections = [(s, by_section[s.id]) for s in data.sections + [store.FALLBACK_SECTION] if s.id in by_section]
    max_sec = max((h for _, h in sections), default=0) or 1

    trend = []
    for i in range(5, -1, -1):
        m = shift_month(first, -i)
        _, mg = g.month_stats(data, m.year, m.month)
        trend.append((g.MONTHS[m.month - 1][:3], mg.totals.hours, mg.totals.sp, m == first))
    max_trend = max((h for _, h, _, _ in trend), default=0) or 1

    sort = request.GET.get('sort', 'hours')
    keys = {'hours': lambda r: -r.stats.hours, 'name': lambda r: r.employee.name,
            'sp': lambda r: -r.stats.sp, 'co': lambda r: -r.stats.co, 'worked': lambda r: -r.stats.worked}
    table = sorted(rows.values(), key=keys.get(sort, keys['hours']))
    max_emp = max((r.stats.hours for r in table), default=0) or 1

    # Ce cere atentie: concedii neaprobate si zile trecute fara pontaj.
    today = g.today()
    pending_co = sorted(
        ((data.employee(e.employee_id), e.day) for e in data.entries.values()
         if e.code == Code.CO and e.approved is False and e.day >= today - dt.timedelta(days=7)),
        key=lambda x: x[1])
    pending_co = [(emp, day) for emp, day in pending_co if emp][:20]
    last_day = min(grid.days[-1], today)
    gaps = []
    if last_day >= grid.days[0]:
        for r in table:
            missing = [c.day for c in r.cells if c.active and not c.entry and c.day <= last_day]
            if missing:
                gaps.append((r.employee, len(missing), missing[-1]))
        gaps.sort(key=lambda x: -x[1])

    return render(request, 'pontaj/stats.html', {
        'month': first, 'title': f'{g.MONTHS[first.month - 1]} {first.year}',
        'prev': prev, 'next': shift_month(first, 1),
        'kpis': kpis, 'sections': sections, 'max_sec': max_sec,
        'trend': trend, 'max_trend': max_trend,
        'table': table, 'max_emp': max_emp, 'sort': sort,
        'pending_co': pending_co, 'gaps': gaps[:10],
    })


@superadmin_required
def history(request):
    logs = store.recent_logs()
    f = {k: request.GET.get(k, '').strip() for k in ('user', 'target', 'action', 'emp', 'from', 'to', 'q')}
    since = timezone.now() - dt.timedelta(days=30)
    activity = Counter(l.username for l in logs if l.when >= since and l.action != 'login').most_common()
    usernames = sorted({l.username for l in logs})
    employees = sorted({(l.employee_id, l.employee_name) for l in logs if l.employee_id}, key=lambda x: x[1] or '')

    def keep(l):
        if f['user'] and l.username != f['user']:
            return False
        if f['target'] and l.target != f['target']:
            return False
        if f['action'] and l.action != f['action']:
            return False
        if f['emp'] and l.employee_id != f['emp']:
            return False
        if f['q'] and f['q'].lower() not in l.summary.lower():
            return False
        if not request.GET.get('logins') and not f['action'] and l.action == 'login':
            return False
        for key, cmp in (('from', lambda d: l.when.date() < d), ('to', lambda d: l.when.date() > d)):
            try:
                if f[key] and cmp(dt.date.fromisoformat(f[key])):
                    return False
            except ValueError:
                pass
        return True

    page = Paginator([l for l in logs if keep(l)], 50).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'pontaj/history.html', {
        'page': page, 'f': f, 'activity': activity, 'query': params.urlencode(),
        'usernames': usernames, 'targets': ['pontaj', 'angajat', 'sectie', 'bonus', 'cont'],
        'actions': list(LogEntry.ACTIONS.items()), 'employees': employees,
        'show_logins': bool(request.GET.get('logins')),
    })


def _download(content, filename, content_type):
    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@admin_required
def export_month(request):
    first = parse_month(request)
    content, filename = exports.month_xlsx(store.load(), first.year, first.month)
    log(request, 'export', 'pontaj', f'Export XLSX {filename}')
    return _download(content, filename, XLSX)


@admin_required
def export_week(request):
    try:
        monday = g.monday_of(dt.date.fromisoformat(request.GET.get('sapt', '')))
    except ValueError:
        monday = g.monday_of(g.today())
    content, filename = exports.week_xlsx(store.load(), monday)
    log(request, 'export', 'pontaj', f'Export XLSX {filename}')
    return _download(content, filename, XLSX)


@superadmin_required
def backup(request):
    """Copie completa a bazei Firebase (JSON), care poate fi reimportata din consola Firebase."""
    content = json.dumps(store.export_all(), ensure_ascii=False, indent=1)
    filename = f'pontaj_backup_{timezone.localtime():%Y-%m-%d_%H%M}.json'
    log(request, 'export', 'cont', f'Backup complet {filename}')
    return _download(content, filename, 'application/json')
