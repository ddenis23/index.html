import datetime as dt

from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods

from .. import grid as g
from .. import store
from ..audit import log
from ..roles import admin_required, can_edit
from ..store import SP_VALUE, Code, Entry

BRUSHES = [
    ('interval:10:23', '10–23', 'c-hrs'), ('interval:10:18', '10–18', 'c-hrs'),
    ('code:OFF', 'OFF', 'c-off'), ('code:SP', 'SP', 'c-sp'), ('code:SP0.5', 'SP½', 'c-sp05'),
    ('code:SP+', 'SP+', 'c-spp'), ('code:CO:1', 'CO ✓', 'c-co'), ('code:CO:0', 'CO ✗', 'c-con'),
    ('code:CM', 'CM', 'c-cm'), ('code:LP', 'LP', 'c-lp'), ('code:LFP', 'LFP', 'c-lfp'),
]
LEGEND = [
    ('c-hrs', 'ore'), ('c-sp', 'SP'), ('c-sp05', 'SP½'), ('c-spp', 'SP+'), ('c-co', 'CO aprobat'),
    ('c-con', 'CO neaprobat'), ('c-cm', 'CM'), ('c-off', 'OFF'), ('c-lp', 'LP'), ('c-lfp', 'LFP'),
    ('c-in', 'inactiv'),
]


def parse_month(request):
    try:
        y, m = map(int, request.GET.get('luna', '').split('-'))
        return dt.date(y, m, 1)
    except (ValueError, TypeError):
        return g.today().replace(day=1)


def parse_shift(request):
    value = request.GET.get('tura') or request.POST.get('tura') or '0'
    return int(value) if value in ('1', '2') else 0


def shift_month(first, delta):
    month = first.month - 1 + delta
    return dt.date(first.year + month // 12, month % 12 + 1, 1)


def _schedule_ctx(request, shift):
    return {'shift': shift, 'brushes': BRUSHES, 'legend': LEGEND, 'can_edit': can_edit(request.user)}


def month_view(request):
    first = parse_month(request)
    shift = parse_shift(request)
    grid = g.build_grid(store.load(), g.month_days(first.year, first.month), shift, with_bonus=True)
    return render(request, 'pontaj/month.html', {
        **_schedule_ctx(request, shift),
        'grid': grid,
        'mode': 'month',
        'title': f'{g.MONTHS[first.month - 1]} {first.year}',
        'month': first,
        'prev': shift_month(first, -1),
        'next': shift_month(first, 1),
        'is_current': first == g.today().replace(day=1),
    })


def week_view(request):
    try:
        anchor = dt.date.fromisoformat(request.GET.get('sapt', ''))
    except ValueError:
        anchor = g.today()
    monday = g.monday_of(anchor)
    shift = parse_shift(request)
    days = g.week_days(monday)
    return render(request, 'pontaj/week.html', {
        **_schedule_ctx(request, shift),
        'grid': g.build_grid(store.load(), days, shift),
        'mode': 'week',
        'title': g.week_label(days),
        'monday': monday,
        'prev': monday - dt.timedelta(days=7),
        'next': monday + dt.timedelta(days=7),
        'is_current': monday == g.monday_of(g.today()),
    })


def _view_days(mode, day):
    if mode == 'week':
        return g.week_days(g.monday_of(day))
    return g.month_days(day.year, day.month)


def _cell_payload(request, data, employee, day, mode, shift):
    """HTML-ul nou pentru randul angajatului si pentru randul de total."""
    grid = g.build_grid(data, _view_days(mode, day), shift, with_bonus=(mode == 'month'))
    row = next((r for r in grid.rows if r.employee.id == employee.id), None)
    ctx = {'grid': grid, 'mode': mode, 'can_edit': True, 'shift': shift}
    return {
        'row': render_to_string('pontaj/_row.html', {**ctx, 'row': row}, request) if row else '',
        'totals': render_to_string('pontaj/_totals.html', ctx, request),
        'emp': employee.id,
    }


def apply_action(entry, employee, day, action):
    """Aplica `action` ('clear' | 'interval:10:23' | 'code:SP' | 'code:CO:1').

    Intoarce intrarea noua sau None pentru stergere; ValueError daca e invalida.
    """
    kind, *args = action.split(':')
    if kind == 'clear':
        return None
    if kind == 'interval' and len(args) == 2:
        try:
            s, e = map(int, args)
        except ValueError:
            raise ValueError('Interval invalid') from None
        if s not in g.START_HOURS or e not in g.END_HOURS or s == e:
            raise ValueError('Interval invalid')
        return Entry(employee.id, day, start_h=s, end_h=e)
    if kind == 'code' and args:
        code = args[0]
        if code not in Code.values:
            raise ValueError('Cod invalid')
        approved = None
        if code == Code.CO:
            if len(args) < 2 or args[1] not in ('1', '0'):
                raise ValueError('Alege daca concediul e aprobat')
            approved = args[1] == '1'
        return Entry(employee.id, day, code=code, approved=approved)
    raise ValueError('Actiune necunoscuta')


@require_http_methods(['GET', 'POST'])
def cell(request):
    params = request.POST if request.method == 'POST' else request.GET
    data = store.load()
    employee = data.employee(params.get('emp', ''))
    if not employee:
        raise Http404
    try:
        day = dt.date.fromisoformat(params.get('day', ''))
    except ValueError:
        return HttpResponseBadRequest('Data invalida')
    mode = 'week' if params.get('mode') == 'week' else 'month'
    entry = data.entries.get((employee.id, day))

    if request.method == 'GET':
        return render(request, 'pontaj/_cell_dialog.html', {
            'employee': employee, 'day': day, 'entry': entry, 'mode': mode,
            'day_name': g.DAY_LONG[day.weekday()], 'month_name': g.MONTHS[day.month - 1],
            'locked': employee.lock_reason(day),
            'presets': g.PRESETS, 'start_hours': g.START_HOURS, 'end_hours': g.END_HOURS,
            'can_edit': can_edit(request.user),
        })

    if not can_edit(request.user):
        return JsonResponse({'error': 'Nu ai drept de editare'}, status=403)
    if reason := employee.lock_reason(day):
        return JsonResponse({'error': reason}, status=400)
    try:
        new = apply_action(entry, employee, day, params.get('action', ''))
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    before = entry.describe() if entry else ''
    after = new.describe() if new else ''
    if before != after or (new and entry and new.to_firebase() != entry.to_firebase()):
        store.save_entry(employee.id, day, new)
        if new:
            data.entries[(employee.id, day)] = new
        else:
            data.entries.pop((employee.id, day), None)
        action = 'delete' if not after else 'create' if not before else 'update'
        log(request, action, 'pontaj', f'{employee.name} · {day:%d.%m.%Y}',
            employee=employee, before=before, after=after)
    return JsonResponse(_cell_payload(request, data, employee, day, mode, parse_shift(request)))


@admin_required
@require_http_methods(['GET', 'POST'])
def bonus(request):
    params = request.POST if request.method == 'POST' else request.GET
    try:
        month = dt.date.fromisoformat(params.get('luna', '') + '-01')
    except ValueError:
        return HttpResponseBadRequest('Luna invalida')
    month_key = f'{month:%Y-%m}'
    month_label = f'{g.MONTHS[month.month - 1]} {month.year}'
    data = store.load()
    employee = data.employee(params['emp']) if params.get('emp') else None
    if params.get('emp') and not employee:
        raise Http404
    current = data.bonuses.get((employee.id, month_key), '') if employee else ''

    if request.method == 'GET':
        return render(request, 'pontaj/_bonus_dialog.html', {
            'employee': employee, 'month': month, 'month_label': month_label, 'current': current,
            'codes': [(c, 'SP½' if c == Code.SP05 else c) for c in SP_VALUE],
            'has_any': any(k[1] == month_key for k in data.bonuses),
            'shift': parse_shift(request),
        })

    code = params.get('code', '')
    if code and code not in SP_VALUE:
        return HttpResponseBadRequest('Cod invalid')
    days = g.month_days(month.year, month.month)
    if employee:
        targets = [employee]
    else:
        targets = [e for e in data.employees if e.is_active_in(days[0], days[-1])]
        if not code:  # "sterge de la toti" include si angajatii care nu mai sunt activi
            targets = [e for e in data.employees if (e.id, month_key) in data.bonuses]
    store.save_bonuses(month_key, {e.id: code or None for e in targets})

    if employee:
        if current != code:
            log(request, 'update' if code else 'delete', 'bonus', f'Bonus vara {employee.name} · {month_label}',
                employee=employee, before=current, after=code)
    else:
        log(request, 'update' if code else 'delete', 'bonus',
            f'Bonus vara pentru toti ({len(targets)} angajati) · {month_label}', after=code)

    url = f'/lunar/?luna={month_key}'
    if shift := parse_shift(request):
        url += f'&tura={shift}'
    return redirect(url)
