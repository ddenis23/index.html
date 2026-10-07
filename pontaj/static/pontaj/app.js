// Pontaj · Unda — interactiuni mici peste pagini randate pe server.
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const csrf = () => document.cookie.match(/csrftoken=([^;]+)/)?.[1] || $('meta[name=csrf]')?.content || '';

  // ── Toast ──
  let toastTimer;
  function toast(msg, isError = false) {
    const el = $('#toast');
    el.textContent = msg;
    el.classList.toggle('error', isError);
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 2400);
  }
  window.toast = toast;

  // ── Meniu mobil ──
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-menu]')) document.body.classList.toggle('menu-open');
    else if (e.target.closest('.scrim')) document.body.classList.remove('menu-open');
  });

  // ── Dialog ──
  const dlg = $('#dlg');
  async function openDialog(url) {
    const res = await fetch(url, { headers: { 'X-Requested-With': 'fetch' } });
    if (!res.ok) { toast('Nu s-a putut deschide', true); return; }
    $('#dlg-content').innerHTML = await res.text();
    if (!dlg.open) dlg.showModal();
  }
  function closeDialog() { if (dlg.open) dlg.close(); }
  dlg?.addEventListener('click', (e) => {
    if (e.target === dlg || e.target.closest('[data-close]')) closeDialog();
  });
  document.addEventListener('click', (e) => {
    const link = e.target.closest('[data-dialog]');
    if (link) { e.preventDefault(); openDialog(link.dataset.dialog || link.href); }
  });

  // ── Grila de pontaj ──
  const table = $('#grid');
  if (!table) return;
  const { mode, tura, cellUrl, editable } = table.dataset;
  let brush = null;
  let painting = false;

  function cellQuery(btn) {
    return new URLSearchParams({ emp: btn.dataset.emp, day: btn.dataset.day, mode, tura });
  }

  async function save(btn, action) {
    const body = cellQuery(btn);
    body.set('action', action);
    btn.classList.add('saving');
    try {
      const res = await fetch(cellUrl, {
        method: 'POST', body,
        headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'fetch' },
      });
      const data = await res.json();
      if (!res.ok) { toast(data.error || 'Eroare la salvare', true); btn.classList.remove('saving'); return false; }
      const row = table.querySelector(`tr[data-emp="${data.emp}"]`);
      if (row && data.row) {
        row.outerHTML = data.row;
        table.querySelector(`tr[data-emp="${data.emp}"] .c[data-day="${btn.dataset.day}"]`)?.classList.add('flash');
      }
      table.tFoot.innerHTML = data.totals;
      return true;
    } catch {
      toast('Fara conexiune — modificarea nu s-a salvat', true);
      btn.classList.remove('saving');
      return false;
    }
  }

  // Pensula: alegi un cod, apoi atingi celulele.
  function setBrush(btn) {
    document.querySelectorAll('.brush.on').forEach((b) => b.classList.remove('on'));
    brush = btn && brush !== btn.dataset.action ? btn.dataset.action : null;
    if (brush) btn.classList.add('on');
    document.body.classList.toggle('painting', !!brush);
  }
  document.addEventListener('click', (e) => {
    const b = e.target.closest('.brush');
    if (b) setBrush(b);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && brush && !dlg.open) setBrush(null);
  });

  table.addEventListener('click', (e) => {
    const btn = e.target.closest('.c[data-emp]');
    if (!btn || btn.classList.contains('c-in')) return;
    if (brush && editable) { save(btn, brush); return; }
    openDialog(`${cellUrl}?${cellQuery(btn)}`);
  });

  // Pe desktop: tine apasat si trage peste celule ca sa completezi mai multe zile deodata.
  table.addEventListener('mousedown', (e) => {
    if (brush && e.target.closest('.c[data-emp]')) { painting = true; e.preventDefault(); }
  });
  table.addEventListener('mouseover', (e) => {
    const btn = e.target.closest('.c[data-emp]');
    if (painting && brush && btn && !btn.classList.contains('c-in') && !btn.classList.contains('saving')) save(btn, brush);
  });
  document.addEventListener('mouseup', () => { painting = false; });

  // Butoanele din dialogul celulei.
  dlg.addEventListener('click', async (e) => {
    const pick = e.target.closest('[data-action]');
    if (!pick) return;
    const form = pick.closest('[data-cell]');
    let action = pick.dataset.action;
    if (action === 'custom') action = `interval:${$('[name=start_h]', form).value}:${$('[name=end_h]', form).value}`;
    const btn = table.querySelector(`.c[data-emp="${form.dataset.emp}"][data-day="${form.dataset.day}"]`);
    pick.disabled = true;
    if (btn && await save(btn, action)) closeDialog();
    pick.disabled = false;
  });
  dlg.addEventListener('change', (e) => {
    const form = e.target.closest('[data-cell]');
    if (!form) return;
    const s = +$('[name=start_h]', form).value, en = +$('[name=end_h]', form).value;
    $('[data-hours]', form).textContent = (en <= s ? en + 24 : en) - s;
  });
})();
