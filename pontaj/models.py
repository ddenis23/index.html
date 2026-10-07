from django.conf import settings
from django.db import models


class Section(models.Model):
    code = models.CharField(max_length=20, unique=True)
    label = models.CharField(max_length=40)
    bg = models.CharField(max_length=9, default='#f0ece3')
    color = models.CharField(max_length=9, default='#5a5040')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'label']

    def __str__(self):
        return self.label


class Employee(models.Model):
    name = models.CharField(max_length=80)
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name='employees')
    shift = models.PositiveSmallIntegerField(choices=[(1, 'Tura 1'), (2, 'Tura 2')], default=1)
    start_from = models.DateField()
    inactive_from = models.DateField(null=True, blank=True)
    legacy_id = models.CharField(max_length=40, blank=True, db_index=True)

    class Meta:
        ordering = ['section__order', 'name']

    def __str__(self):
        return self.name

    def is_active_on(self, day):
        if day < self.start_from:
            return False
        return not (self.inactive_from and day >= self.inactive_from)

    def is_active_in(self, first, last):
        if self.start_from > last:
            return False
        return not (self.inactive_from and self.inactive_from <= first)

    def lock_reason(self, day):
        if day < self.start_from:
            return f'Angajatul incepe din {self.start_from:%d.%m.%Y}'
        if self.inactive_from and day >= self.inactive_from:
            return f'Angajatul este inactiv din {self.inactive_from:%d.%m.%Y}'
        return ''

    @property
    def initials(self):
        return ''.join(w[0] for w in self.name.split()[:2])


class Code(models.TextChoices):
    SP = 'SP', 'SP — 1 tura'
    SP05 = 'SP0.5', 'SP½ — ½ tura'
    SPP = 'SP+', 'SP+ — 1.5 ture'
    CO = 'CO', 'CO — Concediu'
    CM = 'CM', 'CM — Medical'
    OFF = 'OFF', 'OFF — Liber'
    LP = 'LP', 'LP — Liber cu plata'
    LFP = 'LFP', 'LFP — Liber fara plata'


SP_VALUE = {Code.SP: 1, Code.SP05: 0.5, Code.SPP: 1.5}


class Entry(models.Model):
    """O zi de pontaj: fie un interval orar, fie un cod."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='entries')
    day = models.DateField()
    start_h = models.PositiveSmallIntegerField(null=True, blank=True)
    end_h = models.PositiveSmallIntegerField(null=True, blank=True)
    code = models.CharField(max_length=6, choices=Code.choices, blank=True)
    approved = models.BooleanField(null=True, blank=True)  # doar pentru CO

    class Meta:
        constraints = [models.UniqueConstraint(fields=['employee', 'day'], name='one_entry_per_day')]
        indexes = [models.Index(fields=['day'])]

    @property
    def is_interval(self):
        return not self.code

    @property
    def hours(self):
        if self.code:
            return 0
        end = self.end_h if self.end_h > self.start_h else self.end_h + 24
        return end - self.start_h

    def describe(self):
        if not self.code:
            return f'{self.start_h:02d}–{self.end_h:02d} ({self.hours}h)'
        if self.code == Code.CO and self.approved is not None:
            return f'CO ({"aprobat" if self.approved else "neaprobat"})'
        return 'SP½' if self.code == Code.SP05 else self.code


class SummerBonus(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='bonuses')
    month = models.DateField(help_text='Prima zi a lunii')
    code = models.CharField(max_length=6, choices=[(c, c) for c in SP_VALUE])

    class Meta:
        constraints = [models.UniqueConstraint(fields=['employee', 'month'], name='one_bonus_per_month')]


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = 'create', 'Adaugare'
        UPDATE = 'update', 'Modificare'
        DELETE = 'delete', 'Stergere'
        LOGIN = 'login', 'Autentificare'
        EXPORT = 'export', 'Export'

    when = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    username = models.CharField(max_length=150)  # pastrat si daca utilizatorul e sters
    action = models.CharField(max_length=10, choices=Action.choices)
    target = models.CharField(max_length=20)  # pontaj, angajat, sectie, bonus, cont
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL)
    summary = models.CharField(max_length=300)
    before = models.CharField(max_length=200, blank=True)
    after = models.CharField(max_length=200, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-when']
