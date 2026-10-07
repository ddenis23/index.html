import re

from django import forms
from django.contrib.auth.hashers import check_password

from . import store
from .roles import ROLE_LABELS, SUPERADMIN

SECTION_COLORS = [
    ('#fbe3e1', '#9b2c24'), ('#dfebfb', '#1d4f91'), ('#ece3fa', '#5b2a9e'), ('#e3f4e8', '#1b6b3a'),
    ('#fdebd7', '#9a4a00'), ('#efe8df', '#5a4632'), ('#f8e1ee', '#8e2a5e'), ('#ddf2f5', '#0d6573'),
    ('#fff4cc', '#7a5a00'), ('#eeeeec', '#3c4043'),
]
DATE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class EmployeeForm(forms.Form):
    name = forms.CharField(label='Nume', max_length=80)
    section = forms.ChoiceField(label='Sectie')
    shift = forms.TypedChoiceField(label='Tura', choices=[(1, 'Tura 1'), (2, 'Tura 2')], coerce=int,
                                   widget=forms.RadioSelect)
    start_from = forms.DateField(label='Incepe din', widget=DATE)
    active = forms.BooleanField(label='Activ', required=False)
    inactive_from = forms.DateField(label='Inactiv din', required=False, widget=DATE)

    def __init__(self, *args, sections, editing, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['section'].choices = [(s.id, s.label) for s in sections]
        if not editing:
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


class SectionForm(forms.Form):
    label = forms.CharField(label='Nume sectie', max_length=40)
    palette = forms.ChoiceField(label='Culoare', widget=forms.RadioSelect,
                                choices=[(f'{bg}|{c}', c) for bg, c in SECTION_COLORS])

    def __init__(self, *args, section=None, **kwargs):
        super().__init__(*args, **kwargs)
        if section:
            current = f'{section.bg}|{section.color}'
            if current not in dict(self.fields['palette'].choices):
                self.fields['palette'].choices.append((current, section.color))
            self.initial.setdefault('label', section.label)
            self.initial.setdefault('palette', current)
        else:
            self.initial.setdefault('palette', self.fields['palette'].choices[0][0])

    @staticmethod
    def make_id(label, existing):
        base = re.sub(r'[^A-Z0-9_]', '', label.upper().replace(' ', '_'))[:20] or 'SECTIE'
        code, n = base, 2
        while code in existing:
            code, n = f'{base[:17]}_{n}', n + 1
        return code


class UserForm(forms.Form):
    username = forms.CharField(label='Utilizator', max_length=40, help_text='Folosit la autentificare. Fara spatii.')
    name = forms.CharField(label='Nume afisat', max_length=80, required=False)
    role = forms.ChoiceField(label='Rol')
    password = forms.CharField(label='Parola', widget=forms.PasswordInput, required=False, min_length=6,
                               help_text='Minim 6 caractere. Lasa gol ca sa pastrezi parola actuala.')
    active = forms.BooleanField(label='Cont activ', required=False, initial=True)

    def __init__(self, *args, allowed_roles, editing=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editing = editing
        self.fields['role'].choices = [(r, ROLE_LABELS[r]) for r in allowed_roles]
        if editing:
            self.fields['username'].disabled = True
            self.initial.update(username=editing.username, name=editing.name, role=editing.role,
                                active=editing.active)
        else:
            self.fields['password'].required = True
            self.fields['password'].help_text = 'Minim 6 caractere.'

    def clean_username(self):
        username = self.cleaned_data['username'].strip().lower()
        if not store.valid_username(username):
            raise forms.ValidationError('Doar litere, cifre, punct, minus si underscore.')
        if not self.editing and store.get_user(username):
            raise forms.ValidationError('Exista deja un cont cu acest nume.')
        return username


class PasswordChangeForm(forms.Form):
    old_password = forms.CharField(label='Parola curenta', widget=forms.PasswordInput)
    new_password1 = forms.CharField(label='Parola noua', widget=forms.PasswordInput, min_length=6,
                                    help_text='Minim 6 caractere.')
    new_password2 = forms.CharField(label='Confirma parola noua', widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        if not check_password(self.cleaned_data['old_password'], self.user.password):
            raise forms.ValidationError('Parola curenta e gresita.')
        return self.cleaned_data['old_password']

    def clean(self):
        data = super().clean()
        if data.get('new_password1') and data.get('new_password1') != data.get('new_password2'):
            self.add_error('new_password2', 'Parolele nu coincid.')
        return data


__all__ = ['EmployeeForm', 'SectionForm', 'UserForm', 'PasswordChangeForm', 'SUPERADMIN']
