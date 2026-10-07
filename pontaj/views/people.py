"""Angajati, sectii si conturi de utilizator."""

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse_lazy
from django.db.models import Count, ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import grid as g
from ..audit import log
from ..forms import EmployeeForm, SectionForm, UserForm
from ..models import AuditLog, Employee, Section
from ..roles import ADMIN, SUPERADMIN, VIEWER, admin_required, role_of

EMP_FIELDS = {'name': 'nume', 'section': 'sectie', 'shift': 'tura',
              'start_from': 'inceput', 'inactive_from': 'inactiv din'}


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
    rows, _ = g.month_stats(today.year, today.month)
    shift = request.GET.get('tura')
    active, inactive = [], []
    for e in Employee.objects.select_related('section'):
        if shift in ('1', '2') and str(e.shift) != shift:
            continue
        (inactive if e.inactive_from and e.inactive_from <= today else active).append(e)
    sections = []
    for sec in Section.objects.all():
        emps = [(e, rows.get(e.id)) for e in active if e.section_id == sec.id]
        if emps:
            sections.append((sec, emps))
    return render(request, 'pontaj/employees.html', {
        'sections': sections, 'inactive': inactive, 'shift': shift or '',
        'month_name': g.MONTHS[today.month - 1], 'today': today,
        'count': len(active),
    })


@admin_required
def employee_form(request, pk=None):
    employee = get_object_or_404(Employee, pk=pk) if pk else None
    before = _snapshot(employee) if employee else {}
    form = EmployeeForm(request.POST or None, instance=employee,
                        initial=None if employee else {'start_from': g.today(), 'shift': 1})
    if request.method == 'POST' and form.is_valid():
        emp = form.save()
        after = _snapshot(emp)
        if not employee:
            log(request, AuditLog.Action.CREATE, 'angajat', f'Angajat nou: {emp.name}',
                employee=emp, after=_describe(after))
        elif changed := [f for f in EMP_FIELDS if before[f] != after[f]]:
            log(request, AuditLog.Action.UPDATE, 'angajat', f'Angajat modificat: {emp.name}', employee=emp,
                before=_describe(before, changed), after=_describe(after, changed))
        messages.success(request, 'Angajat salvat.')
        return redirect('employees')
    return render(request, 'pontaj/employee_form.html', {'form': form, 'employee': employee})


@admin_required
def employee_delete(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        name, entries = employee.name, employee.entries.count()
        log(request, AuditLog.Action.DELETE, 'angajat', f'Angajat sters: {name} ({entries} zile de pontaj)',
            before=_describe(_snapshot(employee)))
        employee.delete()
        messages.success(request, f'{name} a fost sters.')
        return redirect('employees')
    return render(request, 'pontaj/confirm_delete.html', {
        'title': f'Stergi {employee.name}?',
        'text': f'Se sterg si cele {employee.entries.count()} zile de pontaj. '
                'Daca doar a plecat, mai bine marcheaza-l ca inactiv: istoricul ramane.',
        'back': 'employees',
    })


@admin_required
def section_list(request, pk=None):
    section = get_object_or_404(Section, pk=pk) if pk else None
    form = SectionForm(request.POST or None, instance=section)
    if request.method == 'POST' and form.is_valid():
        old = f'{section.label} {section.color}' if section else ''
        sec = form.save()
        log(request, AuditLog.Action.UPDATE if section else AuditLog.Action.CREATE, 'sectie',
            f'Sectie {"modificata" if section else "noua"}: {sec.label}',
            before=old, after=f'{sec.label} {sec.color}')
        messages.success(request, 'Sectie salvata.')
        return redirect('sections')
    return render(request, 'pontaj/sections.html', {
        'form': form, 'editing': section,
        'sections': Section.objects.annotate(n=Count('employees')),
    })


@admin_required
@require_POST
def section_delete(request, pk):
    section = get_object_or_404(Section, pk=pk)
    try:
        section.delete()
    except ProtectedError:
        messages.error(request, 'Muta angajatii din sectie inainte s-o stergi.')
    else:
        log(request, AuditLog.Action.DELETE, 'sectie', f'Sectie stearsa: {section.label}')
        messages.success(request, 'Sectie stearsa.')
    return redirect('sections')


class PasswordChange(PasswordChangeView):
    template_name = 'pontaj/password_change.html'
    success_url = reverse_lazy('lunar')

    def form_valid(self, form):
        response = super().form_valid(form)
        log(self.request, AuditLog.Action.UPDATE, 'cont', f'{self.request.user.username} si-a schimbat parola')
        messages.success(self.request, 'Parola a fost schimbata.')
        return response


def _allowed_roles(user):
    return [SUPERADMIN, ADMIN, VIEWER] if user.is_superuser else [VIEWER]


def _manageable(request):
    qs = User.objects.order_by('-is_superuser', '-is_staff', 'username')
    return qs if request.user.is_superuser else qs.filter(is_staff=False, is_superuser=False)


@admin_required
def user_list(request):
    users = [(u, role_of(u)) for u in _manageable(request)]
    return render(request, 'pontaj/users.html', {'users': users})


@admin_required
def user_form(request, pk=None):
    user = get_object_or_404(_manageable(request), pk=pk) if pk else None
    old_role = role_of(user) if user else ''
    form = UserForm(request.POST or None, instance=user, allowed_roles=_allowed_roles(request.user))
    if request.method == 'POST' and form.is_valid():
        if user == request.user and (form.cleaned_data['role'] != SUPERADMIN or not form.cleaned_data['is_active']):
            form.add_error('role', 'Nu iti poti scoate singur rolul de superadmin sau dezactiva contul.')
        else:
            saved = form.save()
            parts = []
            if not user:
                parts.append(f'rol {form.cleaned_data["role"]}')
            elif old_role != form.cleaned_data['role']:
                parts.append(f'rol {old_role} → {form.cleaned_data["role"]}')
            if form.cleaned_data.get('password') and user:
                parts.append('parola schimbata')
            if user and 'is_active' in form.changed_data:
                parts.append('activ' if saved.is_active else 'dezactivat')
            log(request, AuditLog.Action.UPDATE if user else AuditLog.Action.CREATE, 'cont',
                f'Cont {"modificat" if user else "nou"}: {saved.username}', after=', '.join(parts))
            messages.success(request, 'Cont salvat.')
            return redirect('users')
    return render(request, 'pontaj/user_form.html', {'form': form, 'edited': user})
