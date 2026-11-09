// LinkIt Fill service worker: the only part that talks to the LinKit All app on this computer.
// Content scripts cannot reach 127.0.0.1 (the page's CORS rules apply to them); this worker can,
// with the pairing token from the options page. Nothing is sent anywhere else. `linkit serve`
// writes its port to app.json in this folder each time it starts, so the user never types it.

const DEFAULT_PORT = 8765;
const FOLLOW_MS = 30 * 60 * 1000;  // a job stays with its tab (and tabs it opens) this long
const MENU = 'linkit-fill';
let hostCache = { at: 0, hosts: [] };

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => chrome.contextMenus.create({
    id: MENU,
    title: 'Fill with LinkIt',
    contexts: ['page', 'editable', 'frame', 'selection', 'link'],
    documentUrlPatterns: ['https://*/*', 'http://*/*'],
  }));
});

// Tab -> job, so pressing Apply on LinkedIn and landing on the employer's site (same tab or a new
// one) still fills that form. Kept in session storage: the worker may be stopped in between.
async function followed(tab) {
  if (!tab) return null;
  const { follow = {} } = await chrome.storage.session.get('follow');
  for (const id of [tab.id, tab.openerTabId]) {
    const f = id !== undefined && follow[id];
    if (f && Date.now() - f.at < FOLLOW_MS) return f;
  }
  return null;
}
async function follow(tab, job, site = '') {
  if (!tab || !job) return;
  const { follow = {} } = await chrome.storage.session.get('follow');
  follow[tab.id] = { job, at: Date.now(), site };
  await chrome.storage.session.set({ follow });
}
async function unfollow(match) {
  const { follow = {} } = await chrome.storage.session.get('follow');
  for (const [id, f] of Object.entries(follow)) if (match(id, f)) delete follow[id];
  await chrome.storage.session.set({ follow });
}
chrome.tabs.onRemoved.addListener((tabId) => unfollow((id) => id === String(tabId)));

async function settings() {
  const { token = '' } = await chrome.storage.local.get('token');
  const { port } = await fetch(chrome.runtime.getURL('app.json'), { cache: 'no-store' })
    .then((r) => r.json()).catch(() => ({ port: DEFAULT_PORT }));
  return { app: `http://127.0.0.1:${port}`, token };
}

async function call(path, init = {}) {
  const { app, token } = await settings();
  if (!token) throw new Error('not paired: open the LinkIt Fill options and paste the code from LinKit All');
  const res = await fetch(app + path, { ...init, headers: { ...(init.headers || {}), 'X-LinKit-Token': token } });
  if (res.status === 404) return null;
  if (res.status === 405) throw new Error('Restart LinKit All: it is older than this extension.');
  if (!res.ok) throw new Error(`LinKit All answered ${res.status}`);
  return res;
}

async function hosts() {
  if (Date.now() - hostCache.at < 60000) return hostCache.hosts;  // one request a minute at most
  const res = await call('/api/assist/hosts');
  hostCache = { at: Date.now(), hosts: res ? (await res.json()).hosts : [] };
  return hostCache.hosts;
}

const json = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const hostOf = (url) => new URL(url).hostname.replace(/^www\./, '');
const onSite = (host, sites) => sites.some((s) => host === s || host.endsWith('.' + s));  // eg.indeed.com is indeed.com

// Which waiting job is this page? `asked`: the user pressed something, so the page may be sent to
// the app even on a site with no job waiting. Without it, the page's address goes nowhere then.
async function jobFor(tab, page, asked) {
  const host = hostOf(page.url);
  const came = await followed(tab);
  if (asked || came || onSite(host, await hosts())) {
    const res = await call('/api/assist/match', json(page));
    const job = res ? await res.json() : null;
    if (job) { await follow(tab, job); return job; }
  }
  if (!came) return null;
  // Back on the job's own site, on another job: this page is not that one.
  if (onSite(host, came.job.hosts) || (came.site && came.site !== host)) {
    await unfollow((id) => id === String(tab.id));
    return null;
  }
  await follow(tab, came.job, host);
  return { ...came.job, carried: true };
}

// Pages open from before the extension was loaded have no content script yet.
async function pageOf(tab) {
  const asked = { type: 'page' }, top = { frameId: 0 };
  try {
    return await chrome.tabs.sendMessage(tab.id, asked, top);
  } catch {
    const target = { tabId: tab.id, allFrames: true };
    await chrome.scripting.executeScript({ target, func: () => { window.__lkNoAuto = true; } });
    await chrome.scripting.executeScript({ target, files: ['snapshot.js', 'content.js'] });
    return chrome.tabs.sendMessage(tab.id, asked, top);
  }
}

const tell = (tabId, msg) => chrome.tabs.sendMessage(tabId, msg, { frameId: 0 }).catch(() => {});

async function fillTab(tab, all) {
  try {
    const job = await jobFor(tab, await pageOf(tab), true);
    await chrome.tabs.sendMessage(tab.id, { type: 'fill', job, all, run: Date.now() });
  } catch (e) {
    await tell(tab.id, { type: 'say', text: String(e.message || e) });
  }
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === MENU && tab && tab.id !== undefined) fillTab(tab, true);
});

async function handle(msg, sender) {
  switch (msg.type) {
    case 'waiting': return jobFor(sender.tab, msg.page, false);
    case 'fill-tab': await fillTab(sender.tab, !!msg.all); return null;
    case 'report': await tell(sender.tab.id, { type: 'report', report: msg.report }); return null;
    case 'say': await tell(sender.tab.id, { type: 'say', text: msg.text }); return null;
    case 'plan': {
      const res = await call('/api/assist/plan', json(msg.body));
      return res ? res.json() : null;
    }
    case 'typed': {  // an answer the user gave in the form, for next time
      const res = await call('/api/assist/typed', json(msg.body));
      return res ? res.json() : null;
    }
    case 'cv': {  // the CV as base64, so the content script can put it in the upload box
      const res = await call(`/api/assist/cv/${msg.jobId}`);
      if (!res) return null;
      const name = (res.headers.get('content-disposition') || '').match(/filename="?([^";]+)/)?.[1] || 'CV.pdf';
      const bytes = new Uint8Array(await res.arrayBuffer());
      let bin = '';
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      return { name, type: res.headers.get('content-type') || 'application/pdf', data: btoa(bin) };
    }
    case 'done': {
      hostCache.at = 0;
      await unfollow((_id, f) => f.job.job_id === msg.body.job_id);
      const res = await call('/api/assist/done', json(msg.body));
      return res ? res.json() : null;
    }
  }
  return null;
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  handle(msg, sender).then((data) => reply({ ok: true, data }), (e) => reply({ ok: false, error: String(e.message || e) }));
  return true;  // the reply comes later
});
