// LinkIt Fill on a page: works out which waiting job this page is, shows a small panel, fills the
// form with the app's answers, and marks the job applied once the site confirms. Runs in every
// frame (many forms sit in an iframe); only the top frame has the panel. It never clicks Next or
// Submit: the user does.

(() => {
  if (window.__lkFill) return;
  window.__lkFill = true;
  const TOP = window === window.top;
  const ask = (msg) => new Promise((res) => chrome.runtime.sendMessage(msg, (r) => res(r || { ok: false, error: 'no answer' })));
  const CONFIRM = /thank you for (applying|your application)|thanks? for applying|application (has been |was )?(successfully )?(submitted|received|sent)|we.ve received your application|we have received your application/i;
  const HINT = 'Open the application form, then press "Fill this step" or right-click it and choose "Fill with LinkIt".';
  let job = null, panel = null, heading = null, status = null, doneBtn = null, doneSent = false, filling = false, keeping = false, watching = false;
  let totals = { run: 0 };
  const watched = new Map();  // control id -> the value LinkIt left there (what the user changes is kept)

  const say = (text) => { if (status) status.textContent = text; };

  // querySelector that also looks inside shadow roots (LinkedIn's apply dialog is in one)
  function deepAll(selector, root = document, out = []) {
    out.push(...root.querySelectorAll(selector));
    for (const e of root.querySelectorAll('*')) if (e.shadowRoot) deepAll(selector, e.shadowRoot, out);
    return out;
  }
  const deep = (selector) => deepAll(selector)[0] || null;
  const inputOf = (id) => deep(`[data-lk-input="${id}"]`);

  function setValue(el, value) {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);  // React tracks the native setter
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
  }
  const norm = (t) => (t || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const labelOf = (el) => norm((el.labels && el.labels[0] && el.labels[0].innerText) || el.closest('label')?.innerText || el.getAttribute('aria-label') || el.value);

  async function putCv(input) {
    const r = await ask({ type: 'cv', jobId: job ? job.job_id : 0 });
    if (!r.ok || !r.data) return false;
    const bytes = Uint8Array.from(atob(r.data.data), (c) => c.charCodeAt(0));
    const dt = new DataTransfer();
    dt.items.add(new File([bytes], r.data.name, { type: r.data.type }));
    input.files = dt.files;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }

  async function fillOne(control, value) {
    const box = deep(`[data-lk-agent~="${control.id}"]`);
    const el = inputOf(control.id);
    if (!el) return false;
    const want = Array.isArray(value) ? value.map(norm) : [norm(String(value))];
    switch (control.kind) {
      case 'file': return putCv(el);
      case 'checkbox':
        if (!!value !== el.checked && el.getAttribute('aria-checked') !== String(!!value)) el.click();
        return true;
      case 'select': {
        const opt = [...el.options].find((o) => want.includes(norm(o.text)) || want.includes(norm(o.value)));
        if (!opt) return false;
        Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(el, opt.value);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      }
      case 'radio': case 'multi': case 'yesno': {
        const scope = box || el.parentElement;
        const choices = [...scope.querySelectorAll('input[type=radio], input[type=checkbox], [role=radio], [role=checkbox], button[aria-pressed]')];
        let hit = false;
        for (const c of choices) {
          const text = c.tagName === 'BUTTON' || c.getAttribute('role') ? norm(c.innerText) : labelOf(c);
          const on = c.checked || c.getAttribute('aria-checked') === 'true' || c.getAttribute('aria-pressed') === 'true';
          if (want.includes(text) && !on) { (c.labels && c.labels[0]) ? c.labels[0].click() : c.click(); hit = true; }
          else if (want.includes(text)) hit = true;
        }
        return hit;
      }
      case 'combobox': {
        setValue(el, String(value));
        await new Promise((r) => setTimeout(r, 600));
        const opt = deepAll('[role=option]').find((o) => norm(o.innerText) === want[0]);
        if (opt) { opt.click(); return true; }
        return false;
      }
      default:
        setValue(el, String(value));
        return true;
    }
  }

  function mark(id, why) {
    const el = deep(`[data-lk-agent~="${id}"]`) || inputOf(id);
    if (!el) return;
    el.style.outline = '3px solid #f59e0b';
    el.style.outlineOffset = '2px';
    el.title = why;
  }

  const isField = (c) => !['button', 'link', 'checkbox', 'toggle'].includes(c.kind);
  const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const SITE_CHROME = 'header, nav, footer, [role=banner], [role=navigation], [role=search], [role=contentinfo]';

  // The form on this page: the open dialog when there is one, else everything but the site's own
  // search bars. On a job board, "City, state, or zip" at the top is the site's, not the form's.
  function formControls() {
    const controls = window.lkSnapshot('');
    const els = new Map(deepAll('[data-lk-input]').map((e) => [e.getAttribute('data-lk-input'), e]));
    const dialog = deepAll('dialog[open], [role=dialog], [aria-modal=true]').filter(visible).pop();
    if (dialog) {
      const inside = controls.filter((c) => dialog.contains(els.get(c.id)));
      if (inside.some(isField)) return inside;
    }
    return controls.filter((c) => els.has(c.id) && !els.get(c.id).closest(SITE_CHROME));
  }

  // what the server accepts; a page's odd field cannot make it refuse the whole step
  const wire = (c) => ({ ...c, html_name: c.html_name.slice(0, 200), href: '', name: c.name.slice(0, 300) });

  function valueOf(c) {  // '' when the control is empty; a list for several ticks
    if (c.empty) return '';
    if (c.kind === 'multi') return c.options.filter((o) => `, ${c.value}, `.includes(`, ${o}, `));
    if (['select', 'radio', 'yesno', 'combobox'].includes(c.kind)) return c.value.trim();
    return (inputOf(c.id)?.value || '').trim();  // not c.value: it is cut short
  }

  function keepTyped() {
    if (filling || !watched.size) return;
    for (const c of window.lkSnapshot('')) {
      if (!watched.has(c.id)) continue;
      const value = valueOf(c), seen = JSON.stringify(value);
      if (!value.length || seen === watched.get(c.id)) continue;
      watched.set(c.id, seen);
      ask({ type: 'typed', body: { job_id: job ? job.job_id : null, control: wire(c), value } }).then((r) => {
        if (r.ok && r.data && r.data.saved) ask({ type: 'say', text: `Saved your answer for next time: ${c.name}` });
      });
    }
  }

  function startKeeping() {
    if (keeping) return;
    keeping = true;
    document.addEventListener('change', keepTyped, true);
    document.addEventListener('focusout', keepTyped, true);  // before Next can take the field away
    document.addEventListener('click', () => setTimeout(keepTyped, 150), true);  // styled choices update after the click
  }

  // One frame's part of a fill; the top frame adds the frames' results up for the panel.
  async function fillFrame(target, all, run) {
    if (filling) return;
    filling = true;
    job = target;
    const done = { run, form: false, filled: 0, byAi: 0, open: 0, error: '' };
    try {
      const controls = formControls().filter((c) => c.kind !== 'button' && c.kind !== 'link').slice(0, 400);
      done.form = controls.some(isField);
      if (!done.form) return;
      startKeeping();
      const text = (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 4000);
      const r = await ask({ type: 'plan', body: { job_id: job ? job.job_id : null, fill_all: all, title: document.title.slice(0, 300), text, controls: controls.map(wire) } });
      if (!r.ok || !r.data) { done.error = r.error || 'LinKit All could not read this form.'; return; }
      const byId = Object.fromEntries(controls.map((c) => [c.id, c]));
      const missed = [];
      for (const [id, value] of Object.entries(r.data.fill)) {
        if (!byId[id] || value === null || value === '') continue;
        try {
          if (await fillOne(byId[id], value)) { done.filled++; if (r.data.sources[id] === 'ai') done.byAi++; } else missed.push(id);
        } catch { missed.push(id); }
      }
      for (const id of missed) mark(id, 'LinkIt could not fill this: please check it');
      for (const m of r.data.missing) mark(m.id, 'Only you can answer this one');
      for (const c of window.lkSnapshot('')) if (watched.has(c.id) || r.data.asked.includes(c.id)) watched.set(c.id, JSON.stringify(valueOf(c)));
      done.open = r.data.missing.length + missed.length;
    } finally {
      filling = false;
      if (TOP || done.form) ask({ type: 'report', report: done });
    }
  }

  function showReport(r) {
    if (r.run !== totals.run) totals = { run: r.run, form: false, filled: 0, byAi: 0, open: 0, error: '' };
    totals.form ||= r.form;
    totals.error ||= r.error;
    totals.filled += r.filled; totals.byAi += r.byAi; totals.open += r.open;
    if (totals.error) return say(totals.error);
    if (!totals.form) return say(`No form found here. ${HINT}`);
    say(`Filled ${totals.filled} field(s)` + (totals.byAi ? `, ${totals.byAi} written by AI and saved.` : ' from your saved data.') + (totals.open ? ` ${totals.open} marked in orange need you.` : '') + ' Check, then press Next or Submit yourself.');
  }

  async function markDone(auto) {
    if (doneSent || !job) return;
    doneSent = true;
    const r = await ask({ type: 'done', body: { job_id: job.job_id, text: (document.body.innerText || '').slice(0, 20000) } });
    say(r.ok ? (auto ? 'Confirmation seen: marked as applied in LinKit All.' : 'Marked as applied in LinKit All.') : (r.error || 'Could not reach LinKit All.'));
    if (!r.ok) doneSent = false;
  }

  function showPanel() {
    if (panel) return;
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;';
    const root = host.attachShadow({ mode: 'closed' });
    root.innerHTML = `
      <style>
        .p{font:13px/1.4 system-ui,sans-serif;background:#fff;color:#0f172a;border:1px solid #cbd5e1;border-radius:12px;
           box-shadow:0 8px 24px rgba(0,0,0,.18);padding:12px;width:280px}
        .t{font-weight:600;margin-bottom:6px}.s{color:#475569;margin:6px 0 10px}
        button{font:inherit;border-radius:8px;padding:6px 10px;border:1px solid #cbd5e1;background:#f8fafc;cursor:pointer;margin-right:6px}
        button.go{background:#059669;border-color:#047857;color:#fff;font-weight:600}
        @media (prefers-color-scheme: dark){.p{background:#0f172a;color:#e2e8f0;border-color:#334155}.s{color:#94a3b8}
          button{background:#1e293b;color:#e2e8f0;border-color:#334155}}
      </style>
      <div class="p" role="region" aria-label="LinkIt Fill">
        <div class="t"></div><div class="s" aria-live="polite"></div>
        <button class="go" type="button">Fill this step</button><button class="d" type="button">I submitted it</button>
      </div>`;
    heading = root.querySelector('.t');
    status = root.querySelector('.s');
    doneBtn = root.querySelector('.d');
    root.querySelector('.go').addEventListener('click', () => { say('Reading this step…'); ask({ type: 'fill-tab', all: false }); });
    doneBtn.addEventListener('click', () => markDone(false));
    document.documentElement.appendChild(host);
    panel = host;
  }

  function watchForConfirmation() {
    if (watching) return;
    watching = true;
    let timer = null;
    new MutationObserver(() => {  // the site's confirmation, after the user pressed Submit
      clearTimeout(timer);
      timer = setTimeout(() => { if (job && CONFIRM.test(document.body.innerText || '')) markDone(true); }, 1000);
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function showJob(found, asked) {
    if ((found && found.job_id) !== (job && job.job_id)) doneSent = false;
    job = found;
    if (!job && !asked) { panel?.remove(); panel = null; return; }
    showPanel();
    heading.textContent = job ? `LinkIt: ${job.title} at ${job.company}` : 'LinkIt: not one of your waiting jobs';
    doneBtn.hidden = !job;
    if (job) watchForConfirmation();
  }

  const pageInfo = () => ({
    url: location.href.slice(0, 4000),
    title: document.title.slice(0, 500),
    heading: [...document.querySelectorAll('h1, h2')].slice(0, 8).map((h) => h.innerText).join(' | ').slice(0, 2000),
    text: (document.body.innerText || '').slice(0, 20000),
  });

  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (msg.type === 'fill') {
      if (TOP) { showJob(msg.job, true); say('Reading this form…'); }
      fillFrame(msg.job, msg.all, msg.run);
    } else if (!TOP) return;
    else if (msg.type === 'page') reply(pageInfo());
    else if (msg.type === 'report') showReport(msg.report);
    else if (msg.type === 'say') { showPanel(); say(msg.text); }
  });

  async function identify(autoFill) {
    const r = await ask({ type: 'waiting', page: pageInfo() });
    if (!r.ok) return;
    showJob(r.data, false);
    if (!job) return;
    if (autoFill && !job.carried && !window.__lkNoAuto) { say('Reading this step…'); ask({ type: 'fill-tab', all: false }); }
    else say(job.carried ? `You came here from this job's Apply button. ${HINT}` : HINT);
  }

  if (TOP) {
    identify(true);
    let url = location.href;
    setInterval(() => {  // sites that change page without loading one (LinkedIn's job list)
      if (location.href === url) return;
      url = location.href;
      setTimeout(() => identify(false), 1000);  // its title and heading arrive after the address
    }, 1000);
  }
})();
