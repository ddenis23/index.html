// Unda · pontaj — interactiuni peste paginile randate pe server.
//
// Orarul functioneaza ca un tabel de calcul: selectezi zile (click, tras, Shift/Ctrl+click,
// sageti), apoi aplici o valoare din bara de jos sau cu o tasta. Celulele se schimba imediat;
// salvarea pleaca in fundal, intr-o singura cerere. Ctrl+Z anuleaza, Ctrl+C / Ctrl+V copiaza.
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const csrf = () => document.cookie.match(/csrftoken=([^;]+)/)?.[1] || $('meta[name=csrf]')?.content || '';

  // ── Toast (cu buton optional "Anuleaza") ──
  const toastEl = $('#toast');
  let toastTimer;
  function toast(msg, { error = false, undo = null } = {}) {
    if (!toastEl) return;
    $('span', toastEl).textContent = msg;
    const btn = $('button', toastEl);
    btn.hidden = !undo;
    btn.onclick = undo ? () => { toastEl.classList.remove('show'); undo(); } : null;
    toastEl.classList.toggle('error', error);
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), undo ? 5000 : 2600);
  }

  // ── Meniul de cont: se inchide la click in afara ──
  document.addEventListener('click', (e) => {
    $$('details.menu[open]').forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });

  // ── Dialog (bonus vara) ──
  const dlg = $('#dlg');
  async function openDialog(url) {
    const res = await fetch(url, { headers: { 'X-Requested-With': 'fetch' } });
    if (!res.ok) { toast('Nu s-a putut deschide', { error: true }); return; }
    $('#dlg-content').innerHTML = await res.text();
    if (!dlg.open) dlg.showModal();
  }
  dlg?.addEventListener('click', (e) => {
    if (e.target === dlg || e.target.closest('[data-close]')) dlg.close();
  });
  document.addEventListener('click', (e) => {
    const link = e.target.closest('[data-dialog]');
    if (link) { e.preventDefault(); openDialog(link.dataset.dialog || link.href); }
  });

  // ══ Orarul ══════════════════════════════════════════════
  const table = $('#grid');
  if (!table) return;
  const editable = !!table.dataset.editable;
  const saveUrl = table.dataset.saveUrl;
  const mode = table.dataset.mode;
  const heads = $$('thead th', table).slice(1);  // un th pe zi (+ coloanele de total)

  // Matricea de celule: rows[r] = <tr>, cells[r][c] = <button>
  const rows = $$('tbody tr[data-emp]', table);
  const cells = rows.map((tr) => $$('.c', tr));
  cells.forEach((list, r) => list.forEach((btn, c) => { btn.dataset.r = r; btn.dataset.c = c; }));
  const at = (r, c) => cells[r]?.[c];
  const pos = (btn) => [+btn.dataset.r, +btn.dataset.c];
  const usable = (btn) => btn && !btn.disabled;

  // ── Cum arata o valoare (identic cu grid.Cell pe server) ──
  const CODES = {
    SP: ['c-sp', 'SP'], 'SP0.5': ['c-sp05', 'SP½'], 'SP+': ['c-spp', 'SP+'], CM: ['c-cm', 'CM'],
    OFF: ['c-off', 'OFF'], LP: ['c-lp', 'LP'], LFP: ['c-lfp', 'LFP'],
  };
  const NAMES = {
    SP: 'Supliment · 1 tură', 'SP0.5': 'Supliment · ½ tură', 'SP+': 'Supliment · 1,5 ture', CM: 'Concediu medical',
    OFF: 'Liber', LP: 'Liber cu plată', LFP: 'Liber fără plată',
  };
  const pad = (n) => String(n).padStart(2, '0');
  const hoursOf = (s, e) => (e <= s ? e + 24 : e) - s;

  function look(v) {
    if (!v) return { css: 'c-empty', label: '', sub: '' };
    const [kind, a, b] = v.split(':');
    if (kind === 'interval') return { css: 'c-hrs', label: String(hoursOf(+a, +b)), sub: `${pad(a)}–${pad(b)}` };
    if (a === 'CO') {
      if (b === '0') return { css: 'c-con', label: 'CO', sub: 'neaprobat' };
      return { css: 'c-co', label: 'CO', sub: b === '1' ? 'aprobat' : '' };
    }
    const [css, label] = CODES[a] || ['', a];
    return { css, label, sub: '' };
  }

  function describe(v) {
    if (!v) return { value: '—', note: 'Nimic completat' };
    const [kind, a, b] = v.split(':');
    if (kind === 'interval') return { value: `${pad(a)}:00 – ${pad(b)}:00`, note: `${hoursOf(+a, +b)} ore lucrate` };
    if (a === 'CO') return { value: 'CO', note: b === '0' ? 'Concediu — neaprobat' : b === '1' ? 'Concediu — aprobat' : 'Concediu' };
    return { value: look(v).label, note: NAMES[a] || '' };
  }

  function paint(btn, v) {
    const { css, label, sub } = look(v);
    btn.dataset.v = v;
    const keep = ['sel', 'act', 'pending'].filter((k) => btn.classList.contains(k));
    btn.className = ['c', css, !v && btn.dataset.past ? 'miss' : '', ...keep].filter(Boolean).join(' ');
    btn.innerHTML = label ? `${label}${sub ? `<small>${sub}</small>` : ''}` : '';
  }

  // ── Totaluri (aceeasi logica ca grid.Stats) ──
  const SPV = { SP: 1, 'SP0.5': 0.5, 'SP+': 1.5 };
  const fmt = (n) => (n ? String(Math.round(n * 100) / 100) : '—');

  function rowStats(r) {
    const s = { hours: 0, sp: SPV[rows[r].dataset.bonus] || 0, co: 0, cm: 0, lfp: 0 };
    for (const btn of cells[r]) {
      const v = btn.dataset.v;
      if (!v) continue;
      const [kind, a, b] = v.split(':');
      if (kind === 'interval') s.hours += hoursOf(+a, +b);
      else if (SPV[a]) s.sp += SPV[a];
      else if (a === 'CO') s.co += 1;
      else if (a === 'CM') s.cm += 1;
      else if (a === 'LFP') s.lfp += 1;
    }
    return s;
  }

  function refreshTotals(changedRows = rows.map((_, i) => i)) {
    for (const r of new Set(changedRows)) {
      const s = rowStats(r);
      $$('td[data-k]', rows[r]).forEach((td) => {
        td.textContent = fmt(s[td.dataset.k]);
        td.classList.toggle('zero', !s[td.dataset.k]);
      });
    }
    const totals = { hours: 0, sp: 0, co: 0, cm: 0, lfp: 0 };
    rows.forEach((_, r) => { const s = rowStats(r); for (const k in totals) totals[k] += s[k]; });
    $$('tfoot td[data-t]', table).forEach((td) => { td.textContent = fmt(totals[td.dataset.t]); });
  }
  refreshTotals();

  // ── Hover: evidentiaza ziua in antet ──
  let hoverTh = null;
  table.addEventListener('pointerover', (e) => {
    const btn = e.target.closest('.c');
    const th = btn ? heads[+btn.dataset.c] : null;
    if (th === hoverTh) return;
    hoverTh?.classList.remove('hover');
    th?.classList.add('hover');
    hoverTh = th;
  });
  table.addEventListener('pointerleave', () => { hoverTh?.classList.remove('hover'); hoverTh = null; });

  // ── Popover-uri ──
  function placePop(pop, btn) {
    pop.hidden = false;
    const rect = btn.getBoundingClientRect();
    const w = pop.offsetWidth, h = pop.offsetHeight;
    let left = Math.min(rect.left, window.innerWidth - w - 12);
    let top = rect.bottom + 8;
    if (top + h > window.innerHeight - 12) top = rect.top - h - 8;
    pop.style.left = `${Math.max(12, left)}px`;
    pop.style.top = `${Math.max(12, top)}px`;
  }
  const closePops = () => $$('.pop').forEach((p) => { p.hidden = true; });
  document.addEventListener('pointerdown', (e) => {
    if (!e.target.closest('.pop') && !e.target.closest('.actionbar') && !e.target.closest('.c')) closePops();
  });

  function dayLabel(btn) {
    const [r, c] = pos(btn);
    const d = new Date(`${btn.dataset.day}T12:00:00`);
    return `${rows[r].dataset.name} · ${heads[c].dataset.long} ${d.getDate()}.${pad(d.getMonth() + 1)}`;
  }

  // Angajatii (fara drept de editare) vad doar detaliile zilei.
  if (!editable) {
    const pop = $('#pop-info');
    table.addEventListener('click', (e) => {
      const btn = e.target.closest('.c');
      if (!usable(btn)) return;
      const { value, note } = describe(btn.dataset.v);
      $('#info-title', pop).textContent = rows[+btn.dataset.r].dataset.name;
      $('#info-sub', pop).textContent = dayLabel(btn).split(' · ')[1];
      $('#info-value', pop).textContent = value;
      $('#info-note', pop).textContent = note;
      placePop(pop, btn);
    });
    return;
  }

  // ══ Editare ════════════════════════════════════════════
  const bar = $('#actionbar');
  const selected = new Set();
  let anchor = null;   // inceputul unei selectii dreptunghiulare
  let active = null;   // celula curenta (conturul negru)

  function setActive(btn) {
    active?.classList.remove('act');
    active = btn;
    active?.classList.add('act');
  }

  function clearSelection() {
    selected.forEach((b) => b.classList.remove('sel'));
    selected.clear();
  }

  function addToSelection(btns) {
    btns.filter(usable).forEach((b) => { selected.add(b); b.classList.add('sel'); });
  }

  function rect(a, b) {
    const [r1, c1] = pos(a), [r2, c2] = pos(b);
    const out = [];
    for (let r = Math.min(r1, r2); r <= Math.max(r1, r2); r++)
      for (let c = Math.min(c1, c2); c <= Math.max(c1, c2); c++) out.push(at(r, c));
    return out.filter(Boolean);
  }

  function selectOnly(btns, { keepAnchor = false } = {}) {
    clearSelection();
    addToSelection(btns);
    if (!keepAnchor) anchor = btns[0] || null;
    updateBar();
  }

  function updateBar() {
    const n = selected.size;
    bar.hidden = n === 0;
    $('#ab-n').textContent = n;
    $('#ab-unit').textContent = n === 1 ? 'zi' : 'zile';
    if (!n) closePops();
  }

  // ── Mouse: click, Shift/Ctrl+click, tras ──
  let dragging = false;
  let lastPointer = 'mouse';
  table.addEventListener('pointerdown', (e) => {
    lastPointer = e.pointerType;
    const btn = e.target.closest('.c');
    if (!usable(btn) || e.button !== 0) return;
    closePops();
    if (e.pointerType !== 'mouse') return;  // pe telefon / stylus, atingerea e tratata la "click"
    e.preventDefault();
    $('.sheet-wrap').focus({ preventScroll: true });
    if (e.shiftKey && anchor) {
      selectOnly(rect(anchor, btn), { keepAnchor: true });
    } else if (e.ctrlKey || e.metaKey) {
      if (selected.has(btn)) { selected.delete(btn); btn.classList.remove('sel'); }
      else addToSelection([btn]);
      anchor = btn;
      updateBar();
    } else {
      selectOnly([btn]);
      dragging = true;
    }
    setActive(btn);
  });
  table.addEventListener('pointerover', (e) => {
    if (!dragging) return;
    const btn = e.target.closest('.c');
    if (btn && anchor) selectOnly(rect(anchor, btn), { keepAnchor: true });
  });
  document.addEventListener('pointerup', () => { dragging = false; });
  table.addEventListener('dblclick', (e) => {
    const btn = e.target.closest('.c');
    if (usable(btn)) openInterval();
  });

  // Pe telefon: fiecare atingere adauga / scoate ziua din selectie.
  table.addEventListener('click', (e) => {
    const btn = e.target.closest('.c');
    if (!usable(btn) || lastPointer === 'mouse') return;
    if (selected.has(btn)) { selected.delete(btn); btn.classList.remove('sel'); }
    else addToSelection([btn]);
    anchor = btn;
    setActive(selected.has(btn) ? btn : null);
    updateBar();
  });

  // ── Salvare: imediat in pagina, apoi in fundal pe server ──
  const undoStack = [];
  let queue = Promise.resolve();

  function apply(changes, { record = true, message = null } = {}) {
    // changes: [{ btn, v }]
    const real = changes.filter(({ btn, v }) => usable(btn) && btn.dataset.v !== v);
    if (!real.length) return;
    const before = real.map(({ btn }) => ({ btn, v: btn.dataset.v }));
    real.forEach(({ btn, v }) => { paint(btn, v); btn.classList.add('pending'); });
    refreshTotals(real.map(({ btn }) => +btn.dataset.r));
    if (record) {
      undoStack.push(before);
      if (undoStack.length > 50) undoStack.shift();
    }
    const items = real.map(({ btn, v }) => ({ emp: rows[+btn.dataset.r].dataset.emp, day: btn.dataset.day, action: v || 'clear' }));
    const n = real.length;
    queue = queue.then(async () => {
      try {
        const res = await fetch(saveUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf(), 'X-Requested-With': 'fetch' },
          body: JSON.stringify({ items }),
        });
        if (res.status === 302 || res.redirected) throw new Error('Sesiunea a expirat — reîncarcă pagina');
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || 'Eroare la salvare');
        real.forEach(({ btn }) => btn.classList.remove('pending'));
        toast(message || (n === 1 ? 'Salvat' : `Salvat · ${n} zile`), { undo: record ? undo : null });
      } catch (err) {
        // Revine la valorile de dinainte doar unde nu s-a schimbat intre timp altceva.
        real.forEach(({ btn, v }, i) => {
          btn.classList.remove('pending');
          if (btn.dataset.v === v) paint(btn, before[i].v);
        });
        refreshTotals(real.map(({ btn }) => +btn.dataset.r));
        if (record) undoStack.pop();
        toast(err.message === 'Failed to fetch' ? 'Fără conexiune — nu s-a salvat' : err.message, { error: true });
      }
    });
  }

  function undo() {
    const last = undoStack.pop();
    if (!last) { toast('Nimic de anulat'); return; }
    apply(last, { record: false, message: 'Modificare anulată' });
  }

  const applyToSelection = (v) => apply([...selected].map((btn) => ({ btn, v })));

  // ── Interval personalizat ──
  const pop = $('#pop-interval');
  const piStart = $('#pi-start'), piEnd = $('#pi-end');
  const syncHours = () => { $('#pi-hours').textContent = hoursOf(+piStart.value, +piEnd.value); };
  piStart.addEventListener('change', syncHours);
  piEnd.addEventListener('change', syncHours);
  function openInterval() {
    if (!selected.size) return;
    const ref = active && selected.has(active) ? active : [...selected][0];
    const [kind, a, b] = (ref.dataset.v || '').split(':');
    piStart.value = kind === 'interval' ? a : '10';
    piEnd.value = kind === 'interval' ? b : '23';
    syncHours();
    $('#pop-interval-sub').textContent = selected.size === 1 ? dayLabel(ref) : `${selected.size} zile selectate`;
    placePop(pop, ref);
    piStart.focus();
  }
  $('#pi-apply').addEventListener('click', () => {
    if (piStart.value === piEnd.value) { toast('Intervalul nu poate avea 0 ore', { error: true }); return; }
    applyToSelection(`interval:${piStart.value}:${piEnd.value}`);
    pop.hidden = true;
  });
  pop.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); $('#pi-apply').click(); }
    if (e.key === 'Escape') { pop.hidden = true; }
  });

  // ── Bara de actiuni ──
  bar.addEventListener('click', (e) => {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    const act = b.dataset.act;
    if (act === 'deselect') { clearSelection(); setActive(null); updateBar(); }
    else if (act === 'custom') openInterval();
    else if (act === 'clear') applyToSelection('');
    else applyToSelection(act);
  });
  const KEYS = Object.fromEntries($$('[data-key]', bar).map((b) => [b.dataset.key, b.dataset.act]));

  // ── Copiere / lipire (in interiorul paginii) ──
  let clip = null;
  function copySelection() {
    if (!selected.size) return;
    const list = [...selected].map(pos);
    const r0 = Math.min(...list.map((p) => p[0])), c0 = Math.min(...list.map((p) => p[1]));
    clip = list.map(([r, c]) => ({ dr: r - r0, dc: c - c0, v: at(r, c).dataset.v }));
    toast(`Copiat · ${clip.length} ${clip.length === 1 ? 'zi' : 'zile'}`);
  }
  function paste() {
    if (!clip || !active) return;
    const [r0, c0] = pos(active);
    const changes = clip.map(({ dr, dc, v }) => ({ btn: at(r0 + dr, c0 + dc), v })).filter(({ btn }) => usable(btn));
    apply(changes);
    selectOnly(changes.map((ch) => ch.btn));
    setActive(active);
  }

  // ── Tastatura ──
  function move(dr, dc, extend) {
    if (!active) { const first = cells.flat().find(usable); if (first) { setActive(first); selectOnly([first]); } return; }
    let [r, c] = pos(active);
    let next = null;
    for (let i = 0; i < 40 && !next; i++) {
      r += dr; c += dc;
      const cand = at(r, c);
      if (!cand && (r < 0 || r >= cells.length || c < 0 || c >= (cells[0]?.length || 0))) break;
      if (usable(cand)) next = cand;
    }
    if (!next) return;
    setActive(next);
    if (extend && anchor) selectOnly(rect(anchor, next), { keepAnchor: true });
    else selectOnly([next]);
    next.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input, select, textarea') || dlg?.open) return;
    const mod = e.ctrlKey || e.metaKey;
    const k = e.key.toLowerCase();
    if (mod && k === 'z') { e.preventDefault(); undo(); return; }
    if (mod && k === 'c') { if (selected.size) { e.preventDefault(); copySelection(); } return; }
    if (mod && k === 'v') { if (clip) { e.preventDefault(); paste(); } return; }
    if (mod || e.altKey) return;
    const arrows = { arrowup: [-1, 0], arrowdown: [1, 0], arrowleft: [0, -1], arrowright: [0, 1] };
    if (arrows[k]) { e.preventDefault(); move(...arrows[k], e.shiftKey); return; }
    if (k === 'escape') { closePops(); clearSelection(); setActive(null); updateBar(); return; }
    if (!selected.size) return;
    if (k === 'enter') { e.preventDefault(); openInterval(); return; }
    if (k === 'delete' || k === 'backspace') { e.preventDefault(); applyToSelection(''); return; }
    if (KEYS[k]) { e.preventDefault(); applyToSelection(KEYS[k]); }
  });

  // Nu pleca din pagina cu modificari nesalvate.
  window.addEventListener('beforeunload', (e) => {
    if ($('.c.pending', table)) { e.preventDefault(); e.returnValue = ''; }
  });
})();
