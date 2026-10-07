# Unda · Pontaj bucătărie

Aplicație Django pentru pontajul bucătăriei: program lunar și săptămânal, angajați, secții, statistici, export XLSX și istoric al modificărilor.

## Roluri

| Rol | Ce poate face |
|---|---|
| **Angajat** | vede programul (fără editare) |
| **Admin** | editează pontajul, angajații, secțiile, bonusul de vară; exportă XLSX; vede statistici; gestionează conturile de angajat |
| **Superadmin** | tot ce face adminul + **Istoric** (cine a modificat ce și când) + creează conturi de admin/superadmin |

Recomandare: fiecare om care modifică programul primește **cont propriu** (din *Conturi*). Așa istoricul arată exact cine a făcut fiecare modificare.

## Pornire locală

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py import_firebase --url https://pontajunda-default-rtdb.europe-west1.firebasedatabase.app
python manage.py create_superadmin          # cere parola interactiv
python manage.py runserver
```

`import_firebase` aduce secțiile, angajații, pontajul și bonusurile. Conturile `admin` și `angajat` își păstrează **parolele actuale** din vechea aplicație (sunt convertite automat la primul login). Pentru a reimporta peste date existente: `--replace`.

## Producție

Variabile de mediu:

```
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<șir lung aleator>
DJANGO_ALLOWED_HOSTS=pontaj.exemplu.ro
DJANGO_CSRF_ORIGINS=https://pontaj.exemplu.ro
DJANGO_DB_PATH=/cale/persistentă/db.sqlite3   # opțional
```

```bash
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn config.wsgi
```

Merge pe orice gazdă Python (PythonAnywhere, Render, Railway, un VPS). SQLite e suficient pentru o echipă de bucătărie; baza trebuie să stea pe un disc persistent și să aibă backup.

## Structură

```
config/              setări Django + URL-uri
pontaj/
  models.py          Section, Employee, Entry (o zi), SummerBonus, AuditLog
  grid.py            calculul grilei și al statisticilor (folosit de pagini, export, statistici)
  views/schedule.py  lunar, săptămânal, editare celulă, bonus vară
  views/people.py    angajați, secții, conturi, schimbare parolă
  views/reports.py   statistici, istoric, export XLSX
  exports.py         generare XLSX (openpyxl)
  audit.py           scrierea în istoric
  templates/pontaj/  câte un template per pagină
  static/pontaj/     app.css, app.js (singurul JS, ~150 linii)
```

Teste: `python manage.py test pontaj`

`index.html` este vechea aplicație Firebase, păstrată până la mutarea pe noul server.
