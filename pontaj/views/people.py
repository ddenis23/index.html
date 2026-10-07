"""Login, angajati, sectii si conturi de utilizator."""

from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .. import auth, store
from .. import grid as g
from ..audit import log
from ..forms import EmployeeForm, PasswordChangeForm, SectionForm, UserForm
from ..roles import ADMIN, SUPERADMIN, VIEWER, admin_required
from ..store import Employee, Section

EMP_FIELDS = {'name': 'nume', 'section': 'sectie', 'shift': 'tura',
              'start_from': 'inceput', 'inactive_from': 'inactiv din'}


# ── Autentificare ──

def _safe_next(url):
    parts = urlsplit(url or '')
    return url if url and not parts.netloc and not parts.scheme and url.startswith('/') else '/lunar/'


def login_view(request):
    nxt = _safe_next(request.POST.get('next') or request.GET.get('next'))
    if request.user.is_authenticated:
        return redirect(nxt)
    error, username = False, ''
    if request.method == 'POST':
        username = request.POST.get('username', '')
        user = auth.authenticate(username, request.POST.get('password', ''))
        if user:
            auth.login(request, user)
            return redirect(nxt)
        error = True
    return render(request, 'pontaj/login.html', {'error': error, 'username': username, 'next': nxt})


@require_POST
def logout_view(request):
    auth.logout(request)
    return redirect('login')


def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = request.user
        user.password = make_password(form.cleaned_data['new_password1'])
        store.save_user(user)
        auth.refresh_session(request, user)
        log(request, 'update', 'cont', f'{user.username} si-a schimbat parola')
        messages.success(request, 'Parola a fost schimbata.')
        return redirect('lunar')
    return render(request, 'pontaj/password_change.html', {'form': form})


# ── Angajati ──

def _fmt(v):
    if v is None or v == '':
        return '—'
    return f'{v:%d.%m.%Y}' if hasattr(v, 'strftime') else str(v)


def _snapshot(emp):
    return {f: _fmt(getattr(emp, f)) for f in EMP_FIELDS}


def _describe(values, fields=EMP_FIELDS):
    return ', '.join(f'{EMP_FIELDS[f]}: {values[f]}' for f in fields)


def employee_list(request):
    today = g.today()
    data = store.load()
    rows, _ = g.month_stats(data, today.year, today.month)
    shift = request.GET.get('tura', '')
    active, inactive = [], []
    for e in data.employees:
        if shift in ('1', '2') and str(e.shift) != shift:
            continue
        (inactive if e.inactive_from and e.inactive_from <= today else active).append(e)
    sections = []
    for sec in data.sections + [store.FALLBACK_SECTION]:
        emps = [(e, rows.get(e.id)) for e in active if e.section.id == sec.id]
        if emps:
            sections.append((sec, emps))
    return render(request, 'pontaj/employees.html', {
        'sections': sections, 'inactive': inactive, 'shift': shift,
        'month_name': g.MONTHS[today.month - 1], 'today': today, 'count': len(active),
    })


@admin_required
def employee_form(request, pk=None):
    data = store.load()
    employee = data.employee(pk) if pk else None
    if pk and not employee:
        raise Http404
    if employee:
        initial = {'name': employee.name, 'section': employee.section.id, 'shift': employee.shift,
                   'start_from': employee.start_from, 'active': not employee.inactive_from,
                   'inactive_from': employee.inactive_from}
    else:
        initial = {'start_from': g.today(), 'shift': 1}
    form = EmployeeForm(request.POST or None, initial=initial, sections=data.sections, editing=bool(employee))
    if request.method == 'POST' and form.is_valid():
        c = form.cleaned_data
        before = _snapshot(employee) if employee else {}
        emp = Employee(employee.id if employee else store.new_id(), c['name'], data.section(c['section']),
                       c['shift'], c['start_from'], c.get('inactive_from'))
        store.save_employee(emp)
        after = _snapshot(emp)
        if not employee:
            log(request, 'create', 'angajat', f'Angajat nou: {emp.name}', employee=emp, after=_describe(after))
        elif changed := [f for f in EMP_FIELDS if before[f] != after[f]]:
            log(request, 'update', 'angajat', f'Angajat modificat: {emp.name}', employee=emp,
                before=_describe(before, changed), after=_describe(after, changed))
        messages.success(request, 'Angajat salvat.')
        return redirect('employees')
    return render(request, 'pontaj/employee_form.html', {'form': form, 'employee': employee})


@admin_required
def employee_delete(request, pk):
    data = store.load()
    employee = data.employee(pk)
    if not employee:
        raise Http404
    days = sum(1 for (eid, _) in data.entries if eid == pk)
    if request.method == 'POST':
        log(request, 'delete', 'angajat', f'Angajat sters: {employee.name} ({days} zile de pontaj)',
            employee=employee, before=_describe(_snapshot(employee)))
        store.delete_employee(pk)
        messages.success(request, f'{employee.name} a fost sters.')
        return redirect('employees')
    return render(request, 'pontaj/confirm_delete.html', {
        'title': f'Stergi {employee.name}?',
        'text': f'Se sterg si cele {days} zile de pontaj. '
                'Daca doar a plecat, mai bine marcheaza-l ca inactiv: istoricul ramane.',
        'back': 'employees',
    })


# ── Sectii ──

@admin_required
def section_list(request, pk=None):
    data = store.load()
    section = data.section(pk) if pk else None
    if pk and not section:
        raise Http404
    form = SectionForm(request.POST or None, section=section)
    if request.method == 'POST' and form.is_valid():
        label = form.cleaned_data['label'].strip()
        bg, color = form.cleaned_data['palette'].split('|')
        if section:
            old = f'{section.label} {section.color}'
            section.label, section.bg, section.color = label, bg, color
            sec = section
        else:
            old = ''
            sec = Section(SectionForm.make_id(label, {s.id for s in data.sections}), label, bg, color,
                          len(data.sections))
        store.save_section(sec)
        log(request, 'update' if old else 'create', 'sectie',
            f'Sectie {"modificata" if old else "noua"}: {sec.label}', before=old, after=f'{sec.label} {sec.color}')
        messages.success(request, 'Sectie salvata.')
        return redirect('sections')
    counts = {s.id: sum(1 for e in data.employees if e.section.id == s.id) for s in data.sections}
    return render(request, 'pontaj/sections.html', {
        'form': form, 'editing': section, 'sections': [(s, counts[s.id]) for s in data.sections],
    })


@admin_required
@require_POST
def section_delete(request, pk):
    data = store.load()
    section = data.section(pk)
    if not section:
        raise Http404
    if any(e.section.id == pk for e in data.employees):
        messages.error(request, 'Muta angajatii din sectie inainte s-o stergi.')
    else:
        store.delete_section(pk)
        log(request, 'delete', 'sectie', f'Sectie stearsa: {section.label}')
        messages.success(request, 'Sectie stearsa.')
    return redirect('sections')


# ── Conturi ──

def _allowed_roles(user):
    return [SUPERADMIN, ADMIN, VIEWER] if user.is_superuser else [VIEWER]


def _manageable(request):
    order = {SUPERADMIN: 0, ADMIN: 1, VIEWER: 2}
    users = sorted(store.list_users(), key=lambda u: (order[u.role], u.username))
    return users if request.user.is_superuser else [u for u in users if u.role == VIEWER]


@admin_required
def user_list(request):
    return render(request, 'pontaj/users.html', {'users': [(u, u.role) for u in _manageable(request)]})


@admin_required
def user_form(request, pk=None):
    user = next((u for u in _manageable(request) if u.username == pk), None) if pk else None
    if pk and not user:
        raise Http404
    form = UserForm(request.POST or None, allowed_roles=_allowed_roles(request.user), editing=user,
                    initial=None if user else {'role': VIEWER, 'active': True})
    if request.method == 'POST' and form.is_valid():
        c = form.cleaned_data
        if user and user.username == request.user.username and (c['role'] != SUPERADMIN or not c['active']):
            form.add_error('role', 'Nu iti poti scoate singur rolul de superadmin sau dezactiva contul.')
        else:
            target = user or store.User(c['username'])
            parts = []
            if not user:
                parts.append(f'rol {c["role"]}')
            elif user.role != c['role']:
                parts.append(f'rol {user.role} → {c["role"]}')
            if user and c['password']:
                parts.append('parola schimbata')
            if user and user.active != c['active']:
                parts.append('activ' if c['active'] else 'dezactivat')
            target.name, target.role, target.active = c['name'].strip(), c['role'], c['active']
            if c['password']:
                target.password = make_password(c['password'])
            store.save_user(target)
            log(request, 'update' if user else 'create', 'cont',
                f'Cont {"modificat" if user else "nou"}: {target.username}', after=', '.join(parts))
            messages.success(request, 'Cont salvat.')
            return redirect('users')
    return render(request, 'pontaj/user_form.html', {'form': form, 'edited': user})
