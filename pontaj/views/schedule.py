import datetime as dt
import json

from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .. import audit, store
from .. import grid as g
from ..audit import log
from ..roles import admin_required, can_edit
from ..store import SP_VALUE, Code, Entry

# Bara de actiuni pentru zilele selectate: (actiune, eticheta, tasta, clasa).
# Tastele sunt interpretate in app.js.
ACTIONS = [
    ('interval:10:23', '10–23', '1', 'c-hrs'), ('interval:10:18', '10–18', '2', 'c-hrs'),
    ('code:OFF', 'OFF', 'O', 'c-off'), ('code:SP', 'SP', 'S', 'c-sp'), ('code:SP0.5', 'SP½', 'H', 'c-sp05'),
    ('code:SP+', 'SP+', 'P', 'c-spp'), ('code:CO:1', 'CO', 'C', 'c-co'), ('code:CO:0', 'CO neaprobat', 'N', 'c-con'),
    ('code:CM', 'CM', 'M', 'c-cm'), ('code:LP', 'LP', 'L', 'c-lp'), ('code:LFP', 'LFP', 'F', 'c-lfp'),
]
LEGEND = [
    ('c-co', 'CO concediu'), ('c-con', 'CO neaprobat'), ('c-cm', 'CM medical'), ('c-lp', 'LP liber plătit'),
    ('c-lfp', 'LFP fără plată'), ('c-in', 'inactiv'),
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
    return {'shift': shift, 'actions': ACTIONS, 'legend': LEGEND, 'can_edit': can_edit(request.user),
            'start_hours': g.START_HOURS, 'end_hours': g.END_HOURS}


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


def apply_action(employee, day, action):
    """Interpreteaza `action` ('clear' | 'interval:10:23' | 'code:SP' | 'code:CO:1').

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


MAX_BATCH = 500


@admin_required
@require_POST
def save_cells(request):
    """Salveaza mai multe zile deodata: {"items": [{"emp", "day", "action"}, ...]}.

    Totul se valideaza inainte; daca o zi e invalida nu se salveaza nimic.
    Pontajul si istoricul se scriu intr-o singura operatie atomica in Firebase.
    """
    try:
        raw_items = json.loads(request.body)['items']
        if not isinstance(raw_items, list) or not 0 < len(raw_items) <= MAX_BATCH:
            raise ValueError
        items = [(str(i['emp']), dt.date.fromisoformat(i['day']), str(i['action'])) for i in raw_items]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'error': 'Cerere invalida'}, status=400)

    people = store.load_people()
    employees = {e.id: e for e in people.employees}
    parsed = {}
    for emp_id, day, action in items:
        employee = employees.get(emp_id)
        if not employee:
            return JsonResponse({'error': 'Angajat inexistent'}, status=400)
        if reason := employee.lock_reason(day):
            return JsonResponse({'error': f'{employee.name}: {reason}'}, status=400)
        try:
            parsed[(emp_id, day)] = (employee, apply_action(employee, day, action))
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=400)

    current = store.load_entries({emp_id for emp_id, _ in parsed})
    updates, logs = {}, []
    for (emp_id, day), (employee, new) in parsed.items():
        old = current.get((emp_id, day))
        before = old.describe() if old else ''
        after = new.describe() if new else ''
        if (old.to_firebase() if old else None) == (new.to_firebase() if new else None):
            continue
        updates[store.entry_path(emp_id, day)] = new.to_firebase() if new else None
        action = 'delete' if not new else 'create' if not old else 'update'
        logs.append(audit.row(request, action, 'pontaj', f'{employee.name} · {day:%d.%m.%Y}',
                              employee=employee, before=before, after=after))
    for row in logs:
        updates[f'istoric/{store.log_key()}'] = row
    store.commit(updates)
    return JsonResponse({'saved': len(logs)})


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
