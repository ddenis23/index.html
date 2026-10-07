import datetime as dt
import hashlib
import json

from django.contrib.auth.hashers import make_password
from django.test import SimpleTestCase

from . import store
from .firebase import MemoryBackend, use_backend

PASS = 'parola-test'
_HASH = None


def _hash():
    global _HASH
    _HASH = _HASH or make_password(PASS)
    return _HASH


def _seed():
    return {
        'sectii': {'CALD': {'label': 'Cald', 'bg': '#fef3e2', 'c': '#7a4800', 'order': 0}},
        'angajati': {
            '1': {'name': 'ION', 'section': 'CALD', 'tura': 1, 'active': True, 'startFrom': '2026-01-01'},
            '2': {'name': 'VECHI', 'section': 'CALD', 'tura': 2, 'active': False},
        },
        'pontaj': {'1': {'2026-10-01': {'type': 'interval', 's': 10, 'e': 23}}},
        # Firebase transforma cheile numerice in liste
        'bonusuri': {'2026-10': [None, 'SP+']},
        'setari': {'admin_pass': hashlib.sha256(b'parola-veche').hexdigest()},
        'utilizatori': {
            u: {'password': _hash(), 'role': r, 'name': u.title(), 'active': True}
            for u, r in (('superadmin', 'superadmin'), ('admin', 'admin'), ('angajat', 'angajat'))
        },
    }


class PontajTests(SimpleTestCase):
    def setUp(self):
        store._user_cache.clear()
        self.db = MemoryBackend(_seed())
        use_backend(self.db)

    def tearDown(self):
        use_backend(None)

    def login(self, username):
        self.client.post('/logout/')
        r = self.client.post('/login/', {'username': username, 'password': PASS})
        self.assertEqual(r.status_code, 302, f'login {username} esuat')

    def save(self, *items):
        return self.client.post('/pontaj/salveaza/', json.dumps({'items': [
            {'emp': emp, 'day': day, 'action': action} for emp, day, action in items]}), content_type='application/json')

    def post_cell(self, action, day='2026-10-05', emp='1'):
        return self.save((emp, day, action))

    def logs(self, target):
        return [l for l in reversed(store.recent_logs()) if l.target == target]

    def test_login_required(self):
        self.assertRedirects(self.client.get('/lunar/'), '/login/?next=/lunar/', fetch_redirect_response=False)

    def test_wrong_password(self):
        r = self.client.post('/login/', {'username': 'admin', 'password': 'gresit'})
        self.assertContains(r, 'Utilizator sau parol')

    def test_reads_legacy_firebase_format(self):
        data = store.load()
        self.assertEqual(data.bonuses[('1', '2026-10')], 'SP+')
        vechi = data.employee('2')
        self.assertFalse(vechi.is_active_on(dt.date(2026, 10, 1)))  # active: false fara data = inactiv
        self.assertEqual(data.entries[('1', dt.date(2026, 10, 1))].hours, 13)

    def test_viewer_can_see_but_not_edit(self):
        self.login('angajat')
        self.assertEqual(self.client.get('/lunar/?luna=2026-10').status_code, 200)
        self.assertEqual(self.client.get('/saptamanal/').status_code, 200)
        self.assertEqual(self.post_cell('code:OFF').status_code, 403)
        for url in ('/statistici/', '/istoric/', '/angajati/nou/', '/lunar/export/', '/istoric/backup/'):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_admin_edit_writes_firebase_format_and_is_logged(self):
        self.login('admin')
        r = self.post_cell('interval:10:23')
        self.assertEqual(json.loads(r.content), {'saved': 1})
        self.assertEqual(self.db.get('pontaj/1/2026-10-05'), {'type': 'interval', 's': 10, 'e': 23})
        self.post_cell('code:CO:1')
        self.assertEqual(self.db.get('pontaj/1/2026-10-05'), {'type': 'code', 'code': 'CO', 'approved': True})
        self.post_cell('clear')
        self.assertIsNone(self.db.get('pontaj/1/2026-10-05'))
        self.assertEqual([(l.action, l.before, l.after, l.username) for l in self.logs('pontaj')], [
            ('create', '', '10–23 (13h)', 'admin'),
            ('update', '10–23 (13h)', 'CO (aprobat)', 'admin'),
            ('delete', 'CO (aprobat)', '', 'admin'),
        ])

    def test_invalid_actions_rejected(self):
        self.login('admin')
        for action in ('code:CO', 'code:XX', 'interval:10', 'interval:a:b', 'interval:10:10', 'nimic'):
            self.assertEqual(self.post_cell(action).status_code, 400, action)
        self.assertEqual(self.post_cell('code:OFF', day='2025-12-31').status_code, 400)  # inainte de start
        self.assertEqual(self.post_cell('code:OFF', emp='nu-exista').status_code, 400)

    def test_batch_is_all_or_nothing_and_skips_unchanged(self):
        self.login('admin')
        r = self.save(('1', '2026-10-06', 'code:OFF'), ('1', '2025-01-01', 'code:OFF'))  # a doua e blocata
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.db.get('pontaj/1/2026-10-06'))
        r = self.save(('1', '2026-10-01', 'interval:10:23'), ('1', '2026-10-06', 'code:OFF'), ('1', '2026-10-07', 'code:OFF'))
        self.assertEqual(json.loads(r.content), {'saved': 2})  # 01.10 era deja 10-23
        self.assertEqual(len(self.logs('pontaj')), 2)
        self.assertEqual(self.save(*[('1', f'2026-11-{d:02d}', 'code:OFF') for d in range(1, 31)] * 20).status_code, 400)

    def test_page_has_cell_values_for_editor(self):
        self.login('admin')
        html = self.client.get('/lunar/?luna=2026-10').content.decode()
        self.assertIn('data-day="2026-10-01" data-v="interval:10:23"', html)

    def test_history_only_for_superadmin(self):
        self.login('admin')
        self.post_cell('code:SP')
        self.assertEqual(self.client.get('/istoric/').status_code, 403)
        self.login('superadmin')
        self.assertContains(self.client.get('/istoric/?user=admin'), 'ION · 05.10.2026')
        backup = self.client.get('/istoric/backup/')
        self.assertEqual(json.loads(backup.content)['pontaj']['1']['2026-10-05'], {'type': 'code', 'code': 'SP'})

    def test_admin_cannot_create_admins(self):
        self.login('admin')
        self.client.post('/conturi/nou/', {'username': 'x', 'role': 'superadmin', 'password': 'abcdef', 'active': 'on'})
        self.assertIsNone(store.get_user('x'))
        self.assertEqual(self.client.get('/conturi/superadmin/').status_code, 404)

    def test_superadmin_creates_admin_who_can_login(self):
        self.login('superadmin')
        r = self.client.post('/conturi/nou/', {'username': 'Maria', 'name': 'Maria', 'role': 'admin',
                                               'password': 'secret12', 'active': 'on'})
        self.assertRedirects(r, '/conturi/', fetch_redirect_response=False)
        self.assertEqual(store.get_user('maria').role, 'admin')
        self.client.post('/logout/')
        self.assertEqual(self.client.post('/login/', {'username': 'maria', 'password': 'secret12'}).status_code, 302)

    def test_deactivated_user_is_logged_out(self):
        self.login('angajat')
        user = store.get_user('angajat')
        user.active = False
        store.save_user(user)
        self.assertEqual(self.client.get('/lunar/').status_code, 302)

    def test_bootstrap_keeps_legacy_admin_password_and_upgrades_it(self):
        from django.core.management import call_command
        self.db.set('utilizatori', None)
        call_command('bootstrap_accounts', stdout=open('nul' if __import__('os').name == 'nt' else '/dev/null', 'w'))
        r = self.client.post('/login/', {'username': 'admin', 'password': 'parola-veche'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(store.get_user('admin').password.startswith('pbkdf2_sha256$'))

    def test_bonus_and_month_totals(self):
        self.login('admin')
        self.post_cell('code:SP+')
        self.client.post('/pontaj/bonus/', {'luna': '2026-10', 'emp': '1', 'code': 'SP'})
        self.assertEqual(self.db.get('bonusuri/2026-10/1'), 'SP')
        r = self.client.get('/lunar/?luna=2026-10')
        self.assertEqual(r.context['grid'].totals.sp, 2.5)

    def test_employee_create_edit_delete(self):
        self.login('admin')
        self.client.post('/angajati/1/', {'name': 'ion  popescu', 'section': 'CALD', 'shift': 2,
                                          'start_from': '2026-01-01', 'active': 'on'})
        self.assertEqual(self.db.get('angajati/1')['name'], 'ION POPESCU')
        self.assertEqual(self.db.get('angajati/1')['tura'], 2)
        log = self.logs('angajat')[-1]
        self.assertEqual((log.before, log.after), ('nume: ION, tura: 1', 'nume: ION POPESCU, tura: 2'))
        self.client.post('/angajati/nou/', {'name': 'nou', 'section': 'CALD', 'shift': 1, 'start_from': '2026-10-01'})
        new_id = next(k for k, v in self.db.get('angajati').items() if v['name'] == 'NOU')
        self.client.post(f'/angajati/{new_id}/sterge/')
        self.assertNotIn(new_id, self.db.get('angajati'))

    def test_pages_render(self):
        self.login('superadmin')
        self.post_cell('interval:10:18')
        for url in ('/lunar/', '/saptamanal/?sapt=2026-10-05', '/angajati/', '/sectii/', '/sectii/CALD/',
                    '/conturi/', '/conturi/admin/', '/statistici/?luna=2026-10', '/istoric/', '/cont/parola/',
                    '/pontaj/bonus/?luna=2026-10&emp=1'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        for url in ('/lunar/export/?luna=2026-10', '/saptamanal/export/?sapt=2026-10-05'):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.content.startswith(b'PK'))
