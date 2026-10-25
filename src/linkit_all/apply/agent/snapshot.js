(prefix) => {  // prefix: makes ids unique across the page's frames
  const S = (window.__lkAgent ||= {n: 0, ids: new WeakMap(), groups: new WeakMap(), g: 0});
  const clean = (t) => (t || '').replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim();
  const parent = (n) => n.parentElement || (n.getRootNode() instanceof ShadowRoot ? n.getRootNode().host : null);
  const all = [];
  const walk = (root) => { for (const e of root.querySelectorAll('*')) { all.push(e); if (e.shadowRoot) walk(e.shadowRoot); } };
  walk(document);

  // Rendered text of a subtree, without controls and options (labels wrap their inputs).
  const visText = (root) => {
    const out = [], w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let t; (t = w.nextNode());) {
      const p = t.parentElement;
      if (p && !p.closest('select, option, textarea, script, style, button') && p.checkVisibility()) out.push(t.textContent);
    }
    return out.join(' ');
  };
  const hiddenUp = (e) => { for (let n = e; n; n = parent(n)) if (n.getAttribute('aria-hidden') === 'true' || n.hasAttribute('inert')) return true; return false; };
  const shown = (e) => {
    const cs = getComputedStyle(e), r = e.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && +cs.opacity !== 0 && (r.width || r.height)
      && r.right + scrollX >= 0 && r.bottom + scrollY >= 0 && r.left + scrollX < 20000;  // off-screen = honeypot
  };
  const labelsOf = (e) => e.labels ? [...e.labels] : (e.closest('label') ? [e.closest('label')] : []);
  const byIds = (e, attr) => (e.getAttribute(attr) || '').split(/\s+/).filter(Boolean)
    .map((id) => e.getRootNode().getElementById?.(id)).filter(Boolean);
  // Question text above a control or group: legend, aria group label, or the closest text before it.
  const nearText = (start, members = []) => {
    let n = start;
    for (let i = 0; n && i < 5; i++, n = parent(n)) {
      if (n.tagName === 'FIELDSET') { const lg = n.querySelector('legend'); if (lg) return [visText(lg), lg]; }
      if (['radiogroup', 'group'].includes(n.getAttribute('role') || '')) {
        const l = byIds(n, 'aria-labelledby')[0];
        if (l) return [visText(l), l];
        if (n.getAttribute('aria-label')) return [n.getAttribute('aria-label'), n];
      }
      const head = members.length && [...n.children].find((c) => /^(LABEL|LEGEND|H[1-6])$/.test(c.tagName)
        && !c.querySelector('input, select, textarea') && !members.includes(c.control) && clean(visText(c)));
      if (head) return [visText(head), head];
      let s = n.previousElementSibling;
      for (let j = 0; s && j < 3; j++, s = s.previousElementSibling) {
        if (s.querySelector('input, select, textarea')) break;
        if (clean(visText(s))) return [visText(s), s];
      }
    }
    return ['', start];
  };
  const nameOf = (e) => {
    const by = byIds(e, 'aria-labelledby');
    if (by.length) return [by.map(visText).join(' '), by[0]];
    const labs = labelsOf(e);
    if (labs.length) return [labs.map(visText).join(' '), labs[0]];
    if (e.getAttribute('aria-label')) return [e.getAttribute('aria-label'), e];
    const near = nearText(e);
    return near[0] ? near : [e.placeholder || e.title || e.name || '', e];
  };
  const optionOf = (e) => {
    const l = labelsOf(e)[0];
    return clean(l ? visText(l) : (e.getAttribute('role') ? e.innerText : '')) || e.value || '';
  };
  const lca = (els) => { let a = els[0]; while (a && !els.every((x) => a.contains(x))) a = parent(a); return a; };
  const reqOf = (els, nameEl, raw) => /[*✱]/.test(raw) || /required/i.test(nameEl?.className || '')
    || !!nameEl?.querySelector?.('[class*=required i]')
    || els.some((c) => c.required || c.getAttribute('aria-required') === 'true');
  const tok = (e, id) => {
    const cur = (e.getAttribute('data-lk-agent') || '').split(' ').filter(Boolean);
    if (!cur.includes(id)) e.setAttribute('data-lk-agent', [...cur, id].join(' '));
  };
  const gid = (n) => { if (!S.groups.has(n)) S.groups.set(n, S.g++); return S.groups.get(n); };

  // 1. visible, enabled controls
  const items = [];
  for (const e of all) {
    if (!e.matches('input, select, textarea, button, [role=combobox], [role=radio], [role=checkbox], [role=switch], [role=button]')) continue;
    if (e.disabled || hiddenUp(e)) continue;
    const type = (e.getAttribute('type') || '').toLowerCase(), role = e.getAttribute('role') || '';
    if (e.tagName === 'INPUT' && ['hidden', 'image', 'reset', 'range', 'color'].includes(type)) continue;
    if (/captcha-response/.test(e.name || '')) continue;
    if (type === 'checkbox' && parent(e)?.querySelector('button[aria-pressed]')) continue;  // mirror of a Yes/No toggle
    const pick = ['radio', 'checkbox', 'file'].includes(type) || ['radio', 'checkbox', 'switch'].includes(role);
    // Styled radios, checkboxes and file inputs are often invisible; their label or box shows.
    if (!(shown(e) || (pick && (labelsOf(e).some(shown) || (type === 'file' && parent(e) && shown(parent(e))))))) continue;
    let kind;
    if (type === 'radio' || role === 'radio') kind = 'radio';
    else if (type === 'checkbox' || role === 'checkbox' || role === 'switch') kind = 'checkbox';
    else if (e.tagName === 'SELECT') kind = 'select';
    else if (e.tagName === 'TEXTAREA') kind = 'textarea';
    else if (type === 'file') kind = 'file';
    else if (role === 'combobox' || e.classList.contains('select__input')) kind = 'combobox';
    else if (e.hasAttribute('aria-pressed')) kind = 'toggle';
    else if (e.tagName === 'BUTTON' || ['submit', 'button'].includes(type) || role === 'button') kind = 'button';
    else kind = ['email', 'tel', 'number', 'url', 'date', 'password'].includes(type) ? type : 'text';
    items.push({e, kind, type});
  }

  // 2. radios, checkbox lists and toggle pairs become one control
  const groups = new Map(), units = [];
  const groupKey = (it) => {
    const e = it.e, form = e.form ? gid(e.form) : -1;
    if (it.kind === 'toggle') return 't' + gid(parent(e));
    if (it.kind === 'radio') return e.name ? `r${form}:${e.name}` : 'r' + gid(e.closest('[role=radiogroup], fieldset') || e);
    if (it.kind === 'checkbox') {
      const fs = e.closest('fieldset, [role=group]');
      if (fs && !fs.querySelector('input:not([type=checkbox]):not([type=hidden]), select, textarea')) return 'c' + gid(fs);
      return e.name ? `c${form}:${e.name}` : null;
    }
    return null;
  };
  for (const it of items) {
    const key = groupKey(it);
    if (key === null) { units.push({kind: it.kind, els: [it.e], type: it.type}); continue; }
    if (!groups.has(key)) { const u = {kind: it.kind, els: [], type: it.type}; groups.set(key, u); units.push(u); }
    groups.get(key).els.push(it.e);
  }

  // 3. describe
  const out = [];
  for (const u of units) {
    const first = u.els[0], many = u.els.length > 1;
    let kind = u.kind, tagEl = first, options = [], value = '', empty = true;
    if (kind === 'radio' || (kind === 'checkbox' && many)) {
      kind = kind === 'radio' ? 'radio' : 'multi';
      tagEl = lca(u.els); if (u.els.includes(tagEl)) tagEl = parent(tagEl);
      options = u.els.map(optionOf);
      const on = u.els.filter((c) => c.checked || c.getAttribute('aria-checked') === 'true').map(optionOf);
      value = on.join(', '); empty = !on.length;
    } else if (kind === 'toggle') {
      if (!many) kind = 'button';
      else {
        kind = 'yesno'; tagEl = parent(first);
        options = u.els.map((b) => clean(b.innerText));
        const on = u.els.filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => clean(b.innerText));
        value = on.join(', '); empty = !on.length;
      }
    } else if (kind === 'checkbox') { value = first.checked ? 'checked' : ''; empty = !first.checked; }
    else if (kind === 'select') {
      options = [...first.options].map((o) => clean(o.text)).filter((t, i) => t && !(i === 0 && /^(select|choose|please|--|click here)/i.test(t))).slice(0, 2000);
      value = first.value ? clean(first.selectedOptions[0]?.text) : ''; empty = !first.value;
    } else if (kind === 'file') { value = [...first.files].map((f) => f.name).join(', '); empty = !first.files.length; }
    else if (kind === 'combobox') {
      const box = first.closest('[class*=container i], [class*=select i]') || parent(first);
      const chosen = clean(box?.querySelector('[class*=single-value i], [class*=multi-value i]')?.textContent);
      value = first.value || chosen; empty = !value;
    } else if (kind !== 'button') { value = kind === 'password' ? '' : first.value; empty = !first.value.trim(); }

    let raw, nameEl;
    if (kind === 'button') { raw = first.innerText || first.value || first.getAttribute('aria-label') || first.title || ''; nameEl = first; }
    else if (kind === 'radio' || kind === 'multi' || kind === 'yesno') [raw, nameEl] = nearText(tagEl, u.els);
    else [raw, nameEl] = nameOf(first);
    const name = clean(raw).slice(0, 240);
    if (kind === 'button' && !name) continue;  // nothing to choose it by (hidden helper buttons)

    if (!S.ids.has(first)) S.ids.set(first, (prefix || '') + 'a' + S.n++);
    const id = S.ids.get(first);
    tok(tagEl, id);
    first.setAttribute('data-lk-input', id);
    out.push({
      id, kind, name, options, value: value.slice(0, 120), empty,
      required: kind !== 'button' && (reqOf(u.els, nameEl, raw)
        || (kind === 'checkbox' && /required/i.test(nearText(first, u.els)[1].className || ''))),  // Ashby: asterisk on the fieldset title
      html_name: first.name || first.id || '',
      type: kind === 'button' ? (first.getAttribute('type') || (first.tagName === 'BUTTON' ? 'submit' : '')).toLowerCase() : u.type,
    });
  }
  return out;
}
