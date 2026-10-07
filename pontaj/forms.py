import re

from django import forms
from django.contrib.auth.models import User

from .models import Employee, Section
from .roles import ADMIN, ROLE_LABELS, SUPERADMIN, VIEWER

SECTION_COLORS = [
    ('#fbe3e1', '#9b2c24'), ('#dfebfb', '#1d4f91'), ('#ece3fa', '#5b2a9e'), ('#e3f4e8', '#1b6b3a'),
    ('#fdebd7', '#9a4a00'), ('#efe8df', '#5a4632'), ('#f8e1ee', '#8e2a5e'), ('#ddf2f5', '#0d6573'),
    ('#fff4cc', '#7a5a00'), ('#eeeeec', '#3c4043'),
]


class EmployeeForm(forms.ModelForm):
    active = forms.BooleanField(label='Activ', required=False, initial=True)

    class Meta:
        model = Employee
        fields = ['name', 'section', 'shift', 'start_from', 'inactive_from']
        labels = {'name': 'Nume', 'section': 'Sectie', 'shift': 'Tura',
                  'start_from': 'Incepe din', 'inactive_from': 'Inactiv din'}
        widgets = {
            'start_from': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'inactive_from': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'shift': forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['section'].empty_label = None
        if self.instance.pk:
            self.fields['active'].initial = not self.instance.inactive_from
        else:
            del self.fields['active']
            del self.fields['inactive_from']

    def clean_name(self):
        return ' '.join(self.cleaned_data['name'].split()).upper()

    def clean(self):
        data = super().clean()
        if 'active' in self.fields:
            if data.get('active'):
                data['inactive_from'] = None
            elif not data.get('inactive_from'):
                self.add_error('inactive_from', 'Alege data de la care e inactiv.')
        start, end = data.get('start_from'), data.get('inactive_from')
        if start and end and end <= start:
            self.add_error('inactive_from', 'Trebuie sa fie dupa data de inceput.')
        return data


class SectionForm(forms.ModelForm):
    palette = forms.ChoiceField(label='Culoare', widget=forms.RadioSelect,
                                choices=[(f'{bg}|{c}', c) for bg, c in SECTION_COLORS])

    class Meta:
        model = Section
        fields = ['label']
        labels = {'label': 'Nume sectie'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = f'{self.instance.bg}|{self.instance.color}'
        choices = dict(self.fields['palette'].choices)
        if self.instance.pk and current not in choices:
            self.fields['palette'].choices.append((current, self.instance.color))
        self.fields['palette'].initial = current if self.instance.pk else self.fields['palette'].choices[0][0]

    def save(self, commit=True):
        section = super().save(commit=False)
        section.bg, section.color = self.cleaned_data['palette'].split('|')
        if not section.pk:
            code = re.sub(r'[^A-Z0-9_]', '', self.cleaned_data['label'].upper().replace(' ', '_'))[:20]
            section.code = code or f'SEC{Section.objects.count() + 1}'
            while Section.objects.filter(code=section.code).exists():
                section.code = section.code[:17] + str(Section.objects.count())
            section.order = Section.objects.count()
        if commit:
            section.save()
        return section


class UserForm(forms.ModelForm):
    role = forms.ChoiceField(label='Rol')
    password = forms.CharField(label='Parola', widget=forms.PasswordInput(render_value=False),
                               required=False, min_length=6,
                               help_text='Minim 6 caractere. Lasa gol ca sa pastrezi parola actuala.')

    class Meta:
        model = User
        fields = ['username', 'first_name', 'is_active']
        labels = {'username': 'Utilizator', 'first_name': 'Nume afisat', 'is_active': 'Cont activ'}
        help_texts = {'username': 'Folosit la autentificare. Fara spatii.'}

    def __init__(self, *args, allowed_roles, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = [(r, ROLE_LABELS[r]) for r in allowed_roles]
        if self.instance.pk:
            from .roles import role_of
            self.fields['role'].initial = role_of(self.instance)
        else:
            self.fields['password'].required = True
            self.fields['password'].help_text = 'Minim 6 caractere.'

    def save(self, commit=True):
        user = super().save(commit=False)
        role = self.cleaned_data['role']
        user.is_superuser = role == SUPERADMIN
        user.is_staff = role in (SUPERADMIN, ADMIN)
        if self.cleaned_data.get('password'):
            user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


__all__ = ['EmployeeForm', 'SectionForm', 'UserForm', 'VIEWER']
