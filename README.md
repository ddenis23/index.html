# Unda · Pontaj bucătărie

Aplicație Django pentru pontajul bucătăriei: program lunar și săptămânal, angajați, secții, statistici, export XLSX și istoric al modificărilor.

**Datele stau în Firebase Realtime Database**, în aceeași structură ca vechea aplicație (`index.html`). Cele două pot rula în paralel pe aceleași date. Django nu are bază de date proprie. Sesiunile sunt cookie-uri semnate.

## Roluri

| Rol | Ce poate face |
|---|---|
| **Angajat** | vede programul (fără editare) |
| **Admin** | editează pontajul, angajații, secțiile, bonusul de vară; exportă XLSX; vede statistici; gestionează conturile de angajat |
| **Superadmin** | tot ce face adminul + **Istoric** (cine a modificat ce și când), **Backup complet**, conturi de admin/superadmin |

Recomandare: fiecare om care modifică programul primește **cont propriu** (din *Conturi*). Așa istoricul arată exact cine a făcut fiecare modificare.

Conturile `admin` și `angajat` sunt create automat la prima pornire, cu **parolele actuale** din vechea aplicație.

## Deploy pe Render

### 1. Cheia Firebase (service account)

1. [Consola Firebase](https://console.firebase.google.com) → proiectul **pontajunda** → ⚙️ *Project settings* → *Service accounts*.
2. *Generate new private key* → se descarcă un fișier `.json`.
3. **Nu pune fișierul în repo și nu-l trimite nimănui.** Îl folosești doar la pasul următor.

### 2. Serviciul pe Render

1. [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint** → alegi repo-ul `ddenis23/index.html`.
2. Render citește `render.yaml` și cere două valori:
   - `FIREBASE_SERVICE_ACCOUNT`: **tot conținutul** fișierului JSON de la pasul 1 (copy-paste);
   - `SUPERADMIN_PASSWORD`: parola contului `superadmin`.
3. **Apply**. După 2–3 minute, aplicația e la `https://unda-pontaj.onrender.com` (sau numele ales).

Site-ul vechi de pe Render rămâne neatins și funcționează în continuare.

### 3. Trecerea pe site-ul nou

1. Testați site-ul nou câteva zile. Ambele site-uri scriu în aceeași bază.
2. Creați din *Conturi* câte un cont de admin pentru fiecare om care modifică programul.
3. Mutați domeniul (dacă aveți) pe serviciul nou și opriți site-ul vechi.
4. **Închideți accesul public la Firebase**: Firebase → *Realtime Database* → *Rules* → lipiți conținutul din [`database.rules.json`](database.rules.json) → *Publish*. Site-ul nou merge în continuare (folosește cheia de service account). Site-ul vechi **nu** mai merge după acest pas.
5. După prima autentificare reușită, variabila `SUPERADMIN_PASSWORD` poate fi ștearsă din Render.

### Backup

Superadmin → *Istoric* → **Backup complet** descarcă toată baza ca JSON. Fișierul se poate reimporta din consola Firebase (*Realtime Database* → ⋮ → *Import JSON*). Planul gratuit Firebase nu face backup automat, deci descărcați unul periodic.

### Bine de știut

Pe planul gratuit Render, serverul „adoarme” după 15 minute fără activitate. Prima deschidere după aceea durează 30–50 de secunde.

## Dezvoltare locală

Local se lucrează pe o **copie** a datelor (fișier JSON), nu pe Firebase-ul real:

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

# o copie a datelor: export JSON din consola Firebase sau Backup complet din aplicație
set FIREBASE_LOCAL_FILE=backups\copie.json        # PowerShell: $env:FIREBASE_LOCAL_FILE="backups\copie.json"
python manage.py bootstrap_accounts
python manage.py create_superadmin
python manage.py runserver
```

Pentru a lucra pe baza reală local: `FIREBASE_SERVICE_ACCOUNT_FILE=cale\catre\cheie.json` în loc de `FIREBASE_LOCAL_FILE`.

Teste: `python manage.py test pontaj` (rulează pe o bază în memorie).

## Structură

```
config/              setări Django + URL-uri
render.yaml          configurarea serviciului pe Render
database.rules.json  regulile Firebase care închid accesul public
pontaj/
  firebase.py        acces la Firebase (REST + service account; copie locală; memorie pentru teste)
  store.py           structura datelor în Firebase + citire/scriere
  auth.py            autentificare cu conturile din Firebase
  grid.py            calculul grilei și al statisticilor
  views/             câte un modul: pontaj, oameni/conturi, rapoarte
  exports.py         generare XLSX
  audit.py           scrierea în istoric
  templates/pontaj/  câte un template per pagină
  static/pontaj/     app.css, app.js
```
