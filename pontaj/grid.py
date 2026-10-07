"""Construieste grila de pontaj (lunar / saptamanal) si statisticile pe angajat."""

import calendar
import datetime as dt
from dataclasses import dataclass, field

from django.utils import timezone

from .store import SP_VALUE, Code

MONTHS = ['Ianuarie', 'Februarie', 'Martie', 'Aprilie', 'Mai', 'Iunie', 'Iulie',
          'August', 'Septembrie', 'Octombrie', 'Noiembrie', 'Decembrie']
DAY_SHORT = ['Lu', 'Ma', 'Mi', 'Jo', 'Vi', 'Sâ', 'Du']
DAY_LONG = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică']

# Intervale folosite des, oferite ca butoane rapide la editare.
PRESETS = [(10, 23, 13), (10, 18, 8)]  # (inceput, sfarsit, ore)
START_HOURS = list(range(6, 23))
END_HOURS = list(range(8, 24)) + [0, 1, 2]

CODE_CSS = {
    Code.SP: 'c-sp', Code.SP05: 'c-sp05', Code.SPP: 'c-spp', Code.CM: 'c-cm',
    Code.OFF: 'c-off', Code.LP: 'c-lp', Code.LFP: 'c-lfp',
}


def today():
    return timezone.localdate()


def month_days(year, month):
    return [dt.date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]


def monday_of(day):
    return day - dt.timedelta(days=day.weekday())


def week_days(monday):
    return [monday + dt.timedelta(days=i) for i in range(7)]


def week_label(days):
    first, last = days[0], days[-1]
    if first.month == last.month:
        return f'{first.day}–{last.day} {MONTHS[last.month - 1]} {last.year}'
    return f'{first.day} {MONTHS[first.month - 1]} – {last.day} {MONTHS[last.month - 1]} {last.year}'


@dataclass
class Stats:
    hours: int = 0
    sp: float = 0
    co: int = 0
    cm: int = 0
    lfp: int = 0
    off: int = 0
    lp: int = 0
    worked: int = 0  # zile cu interval sau SP

    def add_entry(self, entry):
        if entry.is_interval:
            self.hours += entry.hours
            self.worked += 1
            return
        if entry.code in SP_VALUE:
            self.sp += SP_VALUE[entry.code]
            self.worked += 1
        elif entry.code == Code.CO:
            self.co += 1
        elif entry.code == Code.CM:
            self.cm += 1
        elif entry.code == Code.LFP:
            self.lfp += 1
        elif entry.code == Code.OFF:
            self.off += 1
        elif entry.code == Code.LP:
            self.lp += 1

    def __iadd__(self, other):
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        return self


def fmt_num(value):
    """2.0 -> '2', 2.5 -> '2.5', 0 -> ''."""
    if not value:
        return ''
    return str(int(value)) if float(value).is_integer() else f'{value:g}'


@dataclass
class Cell:
    day: dt.date
    entry: Entry | None
    active: bool
    is_today: bool

    @property
    def weekend(self):
        return self.day.weekday() >= 5

    @property
    def css(self):
        if not self.active:
            return 'c-in'
        e = self.entry
        if not e:
            return 'c-empty'
        if e.is_interval:
            return 'c-hrs'
        if e.code == Code.CO:
            return 'c-con' if e.approved is False else 'c-co'
        return CODE_CSS.get(e.code, '')

    @property
    def label(self):
        if not self.active:
            return ''
        e = self.entry
        if not e:
            return ''
        if e.is_interval:
            return str(e.hours)
        return 'SP½' if e.code == Code.SP05 else e.code

    @property
    def sub(self):
        e = self.entry
        if not self.active or not e:
            return ''
        if e.is_interval:
            return f'{e.start_h:02d}–{e.end_h:02d}'
        if e.code == Code.CO and e.approved is not None:
            return 'aprobat' if e.approved else 'neaprobat'
        return ''


@dataclass
class Row:
    employee: Employee
    cells: list
    stats: Stats
    bonus: str = ''

    @property
    def bonus_label(self):
        return 'SP½' if self.bonus == Code.SP05 else self.bonus


@dataclass
class Grid:
    days: list
    groups: list = field(default_factory=list)  # [(shift, [Row])]
    totals: Stats = field(default_factory=Stats)
    with_bonus: bool = False

    @property
    def rows(self):
        return [r for _, rows in self.groups for r in rows]

    @property
    def head(self):
        now = today()
        return [{'day': d, 'short': DAY_SHORT[d.weekday()], 'long': DAY_LONG[d.weekday()],
                 'we': d.weekday() >= 5, 'today': d == now} for d in self.days]


def employees_in(data, first, last, shift=0):
    return [e for e in data.employees if e.is_active_in(first, last) and (not shift or e.shift == shift)]


def build_row(employee, days, entries, bonus=''):
    now = today()
    cells, stats = [], Stats()
    for day in days:
        active = employee.is_active_on(day)
        entry = entries.get((employee.id, day)) if active else None
        if entry:
            stats.add_entry(entry)
        cells.append(Cell(day, entry, active, day == now))
    if bonus:
        stats.sp += SP_VALUE.get(bonus, 0)
    return Row(employee, cells, stats, bonus)


def build_grid(data, days, shift=0, with_bonus=False, employees=None):
    if employees is None:
        employees = employees_in(data, days[0], days[-1], shift)
    month_key = f'{days[0]:%Y-%m}'
    grid = Grid(days=days, with_bonus=with_bonus)
    for s in (1, 2):
        rows = [build_row(e, days, data.entries, data.bonuses.get((e.id, month_key), '') if with_bonus else '')
                for e in employees if e.shift == s]
        if rows:
            grid.groups.append((s, rows))
            for r in rows:
                grid.totals += r.stats
    return grid


def month_stats(data, year, month):
    """({employee_id: Row}, Grid) pentru o luna, inclusiv bonusul de vara."""
    grid = build_grid(data, month_days(year, month), with_bonus=True)
    return {r.employee.id: r for r in grid.rows}, grid
