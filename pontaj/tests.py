import datetime as dt
import hashlib
import json

from django.contrib.auth.models import User
from django.test import TestCase

from .models import AuditLog, Employee, Entry, Section, SummerBonus


class PontajTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sec = Section.objects.create(code='CALD', label='Cald')
        cls.emp = Employee.objects.create(name='ION', section=cls.sec, shift=1, start_from=dt.date(2026, 1, 1))
        cls.superadmin = User.objects.create_user('superadmin', password='test-super-pass', is_staff=True, is_superuser=True)
        cls.admin = User.objects.create_user('admin', password='parola123', is_staff=True)
        cls.viewer = User.objects.create_user('angajat', password='parola123')

    def post_cell(self, action, day='2026-10-05', mode='month'):
        return self.client.post('/pontaj/celula/', {'emp': self.emp.id, 'day': day, 'mode': mode, 'action': action})

    def test_login_required(self):
        self.assertRedirects(self.client.get('/lunar/'), '/login/?next=/lunar/')

    def test_viewer_can_see_but_not_edit(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get('/lunar/?luna=2026-10').status_code, 200)
        self.assertEqual(self.client.get('/saptamanal/').status_code, 200)
        self.assertEqual(self.post_cell('code:OFF').status_code, 403)
        for url in ('/statistici/', '/istoric/', '/angajati/nou/', '/lunar/export/'):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_admin_edit_is_logged_with_user(self):
        self.client.force_login(self.admin)
        r = self.post_cell('interval:10:23')
        self.assertEqual(r.status_code, 200)
        self.assertIn('data-emp', json.loads(r.content)['row'])
        self.post_cell('code:CO:1')
        self.post_cell('clear')
        logs = list(AuditLog.objects.filter(target='pontaj').order_by('when', 'id'))
        self.assertEqual([(l.action, l.before, l.after, l.username) for l in logs], [
            ('create', '', '10–23 (13h)', 'admin'),
            ('update', '10–23 (13h)', 'CO (aprobat)', 'admin'),
            ('delete', 'CO (aprobat)', '', 'admin'),
        ])
        self.assertFalse(Entry.objects.exists())

    def test_invalid_actions_rejected(self):
        self.client.force_login(self.admin)
        for action in ('code:CO', 'code:XX', 'interval:10', 'interval:a:b', 'interval:10:10', 'nimic'):
            self.assertEqual(self.post_cell(action).status_code, 400, action)
        self.assertEqual(self.post_cell('code:OFF', day='2025-12-31').status_code, 400)  # inainte de start

    def test_history_only_for_superadmin(self):
        self.client.force_login(self.admin)
        self.post_cell('code:SP')
        self.assertEqual(self.client.get('/istoric/').status_code, 403)
        self.client.force_login(self.superadmin)
        r = self.client.get('/istoric/?user=admin')
        self.assertContains(r, 'ION · 05.10.2026')

    def test_admin_cannot_create_admins(self):
        self.client.force_login(self.admin)
        self.client.post('/conturi/nou/', {'username': 'x', 'role': 'superadmin', 'password': 'abcdef', 'is_active': 'on'})
        self.assertFalse(User.objects.filter(username='x').exists())
        self.assertEqual(self.client.get(f'/conturi/{self.superadmin.id}/').status_code, 404)

    def test_superadmin_creates_admin(self):
        self.client.force_login(self.superadmin)
        r = self.client.post('/conturi/nou/', {'username': 'maria', 'first_name': 'Maria', 'role': 'admin',
                                               'password': 'secret12', 'is_active': 'on'})
        self.assertRedirects(r, '/conturi/')
        maria = User.objects.get(username='maria')
        self.assertTrue(maria.is_staff and not maria.is_superuser and maria.check_password('secret12'))

    def test_legacy_password_upgraded_on_login(self):
        u = User.objects.create(username='vechi', password='legacy_sha256$$' + hashlib.sha256(b'parola-veche-test').hexdigest())
        self.assertTrue(self.client.login(username='vechi', password='parola-veche-test'))
        u.refresh_from_db()
        self.assertTrue(u.password.startswith('pbkdf2_sha256$'))
        self.assertFalse(self.client.login(username='vechi', password='gresit'))

    def test_bonus_and_month_totals(self):
        self.client.force_login(self.admin)
        self.post_cell('code:SP+')
        self.client.post('/pontaj/bonus/', {'luna': '2026-10', 'emp': self.emp.id, 'code': 'SP'})
        self.assertEqual(SummerBonus.objects.get().code, 'SP')
        r = self.client.get('/lunar/?luna=2026-10')
        self.assertEqual(r.context['grid'].totals.sp, 2.5)

    def test_employee_edit_logs_diff(self):
        self.client.force_login(self.admin)
        self.client.post(f'/angajati/{self.emp.id}/', {
            'name': 'ion  popescu', 'section': self.sec.id, 'shift': 2, 'start_from': '2026-01-01',
            'active': 'on'})
        self.emp.refresh_from_db()
        self.assertEqual((self.emp.name, self.emp.shift), ('ION POPESCU', 2))
        log = AuditLog.objects.get(target='angajat')
        self.assertEqual(log.before, 'nume: ION, tura: 1')
        self.assertEqual(log.after, 'nume: ION POPESCU, tura: 2')

    def test_pages_render(self):
        self.client.force_login(self.superadmin)
        self.post_cell('interval:10:18')
        for url in ('/lunar/', '/saptamanal/?sapt=2026-10-05', '/angajati/', '/sectii/', '/conturi/',
                    '/statistici/?luna=2026-10', '/istoric/', '/cont/parola/',
                    f'/pontaj/celula/?emp={self.emp.id}&day=2026-10-05&mode=month',
                    f'/pontaj/bonus/?luna=2026-10&emp={self.emp.id}'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        for url in ('/lunar/export/?luna=2026-10', '/saptamanal/export/?sapt=2026-10-05'):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.content.startswith(b'PK'))
