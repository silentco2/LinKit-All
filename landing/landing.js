(() => {
  const d = document;
  const $ = (s, c = d) => c.querySelector(s);
  const $$ = (s, c = d) => [...c.querySelectorAll(s)];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---- hero sequence: sheets settle, counts tick, form types itself, stamp lands (~6s) ---- */
  const stage = $('#stage'), form = $('#appform'), replay = $('#replay');
  const vals = $$('.v', form), flds = $$('.fld', form), counts = $$('[data-count]');
  const states = ['has-cv', 'has-note', 'has-banner', 'real', 'has-proof', 'stamped'];
  let run = 0;

  const fmt = n => n.toLocaleString('en-US');
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const frame = () => new Promise(r => requestAnimationFrame(r));

  function tick(el, id) {
    const to = +el.dataset.count, t0 = performance.now(), dur = 1000;
    const step = async () => {
      const k = Math.min(1, (performance.now() - t0) / dur);
      if (id !== run) return;
      el.textContent = fmt(Math.round(to * (1 - Math.pow(1 - k, 3))));
      if (k < 1) { await frame(); step(); }
    };
    step();
  }
  async function type(i, ms, id) {
    const v = vals[i], s = v.dataset.text, f = v.closest('.fld');
    f.classList.add('on');
    const t0 = performance.now();
    for (;;) {
      const k = Math.min(s.length, Math.floor((performance.now() - t0) / ms * s.length));
      if (id !== run) return;
      v.textContent = s.slice(0, k);
      if (k >= s.length) break;
      await frame();
    }
    f.classList.remove('on');
  }
  function clear() {
    run++;
    form.classList.remove(...states);
    vals.forEach(v => { v.textContent = ''; });
    flds.forEach(f => f.classList.remove('on'));
  }
  async function play(withCounts) {
    clear();
    const id = run;
    if (withCounts) { counts.forEach(c => { c.textContent = '0'; }); await wait(450); if (id !== run) return; counts.forEach(c => tick(c, id)); }
    await wait(withCounts ? 500 : 200);
    const step = async (fn, ms) => { if (id !== run) return false; await fn(); if (id !== run) return false; await wait(ms); return id === run; };
    (await step(() => type(0, 450, id), 80)) &&
    (await step(() => type(1, 550, id), 80)) &&
    (await step(() => form.classList.add('has-cv'), 350)) &&
    (await step(() => type(2, 900, id), 200)) &&
    (await step(() => form.classList.add('has-note'), 500)) &&
    (await step(() => form.classList.add('has-banner'), 900)) &&
    (await step(() => form.classList.add('real'), 450)) &&
    (await step(() => form.classList.add('has-proof'), 350)) &&
    (await step(() => form.classList.add('stamped'), 0));
  }

  if (reduce) {
    stage.classList.add('go');
  } else {
    replay.hidden = false;
    replay.addEventListener('click', () => play(false));
    clear(); // start from the empty form; the final state is the no-JS default
    counts.forEach(c => { c.textContent = '0'; });
    let started = false;
    const start = () => { if (started) return; started = true; stage.classList.add('go'); play(true); };
    if ('IntersectionObserver' in window) {
      new IntersectionObserver((es, o) => { if (es.some(e => e.isIntersecting)) { o.disconnect(); start(); } }, { threshold: 0.15 }).observe(stage);
    }
    setTimeout(start, 2500); // never leave the hero hidden
  }

  /* ---- scroll reveals ---- */
  if (!reduce && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    }), { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    $$('[data-rv]').forEach(el => io.observe(el));
  } else {
    $$('[data-rv]').forEach(el => el.classList.add('in'));
  }

  /* ---- pipeline tabs ---- */
  const tabs = $$('[role=tab]'), panels = $$('[role=tabpanel]');
  const pick = (i, focus) => {
    tabs.forEach((t, j) => { t.setAttribute('aria-selected', j === i); t.tabIndex = j === i ? 0 : -1; });
    panels.forEach((p, j) => { p.hidden = j !== i; });
    if (focus) tabs[i].focus();
  };
  pick(0);
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => pick(i));
    t.addEventListener('keydown', e => {
      const n = tabs.length, k = { ArrowRight: (i + 1) % n, ArrowLeft: (i + n - 1) % n, Home: 0, End: n - 1 }[e.key];
      if (k !== undefined) { e.preventDefault(); pick(k, true); }
    });
  });

  /* ---- copy button ---- */
  $$('[data-copy]').forEach(b => b.addEventListener('click', async () => {
    const text = $('#' + b.dataset.copy).textContent;
    try { await navigator.clipboard.writeText(text); } catch {
      const r = d.createRange(); r.selectNodeContents($('#' + b.dataset.copy));
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      try { d.execCommand('copy'); } catch { return; }
    }
    const l = $('span', b); b.dataset.copied = ''; l.textContent = 'Copied';
    setTimeout(() => { delete b.dataset.copied; l.textContent = 'Copy'; }, 1600);
  }));
})();
