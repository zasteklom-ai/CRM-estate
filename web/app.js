/* Усадьба·CRM — фронт (vanilla JS, без сборки) */
const S = {
  user: null, meta: null, view: 'deals', cardTab: 'card', adminTab: 'sources',
  deals: [], stages: [], sources: [], users: [], filters: { q: '', source: '', owner: '' },
  threads: [], threadId: null, clients: [], calls: [], stats: null, card: null,
  admin: { users: [], sources: [], stages: [], settings: null }, log: [],
  clientFilter: { q: '', source: '', criteria: '' }, expanded: {}, newMode: false,
};
const tok = () => localStorage.getItem('crm_sid') || '';
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const can = (p) => !!S.user && (S.user.role === 'owner' || (S.user.perms || []).includes(p));
const money = (n) => (n ? Number(n).toLocaleString('ru-RU') + ' ₽' : '—');
const DTF = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
const dt = (ts) => (ts ? DTF.format(new Date(ts * 1000)) : '—');
function ago(ts) {
  if (!ts) return '—';
  const d = Math.max(1, Math.round((Date.now() / 1000 - ts) / 60));
  if (d < 60) return d + ' мин назад';
  if (d < 1440) return Math.round(d / 60) + ' ч назад';
  return Math.round(d / 1440) + ' дн назад';
}
const initials = (n) => (n || '?').split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
const opt = (arr, cur, tf) => arr.map((x) => `<option value="${esc(tf ? tf(x).v : x.v ?? x.id)}"${((tf ? tf(x).v : x.v ?? x.id) == cur) ? ' selected' : ''}>${esc(tf ? tf(x).t : x.t || x.name)}</option>`).join('');
function toast(msg, err) {
  let box = $('toasts');
  if (!box) { box = document.createElement('div'); box.className = 'toasts'; document.body.appendChild(box); }
  const t = document.createElement('div');
  t.className = 'toast' + (err ? ' err' : '');
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.remove(), err ? 6000 : 3200);
}
async function api(path, body, method) {
  // относительный URL — приложение работает и под путём-префиксом превью-прокси
  const url = String(path).replace(/^\/+/, '');
  const r = await fetch(url, {
    method: method || (body ? 'POST' : 'GET'),
    headers: { 'Content-Type': 'application/json', 'X-Session-Token': tok() },
    body: body ? JSON.stringify(body) : undefined,
  });
  let d = {};
  try { d = await r.json(); } catch (e) { /* empty */ }
  if (r.status === 401) { S.user = null; S.card = null; render(); throw new Error(d.error || 'вход required'); }
  if (!r.ok) throw new Error(d.error || ('ошибка HTTP ' + r.status));
  return d;
}

/* ---------------------------------------------------------------- boot */
async function boot() {
  const box = $('app'); if (box) box.setAttribute('data-boot', 'ok');
  try {
    const d = await api('/api/session');
    if (d.user) { S.user = d.user; S.meta = d.meta; S.stages = d.meta.stages; await goto(S.view); return; }
  } catch (e) { /* login screen */ }
  render();
}

/* ---------------------------------------------------------------- nav */
async function goto(view, force) {
  S.view = view; S.card = null;
  try {
    if (view === 'deals') { const d = await api('/api/deals' + dealQuery()); Object.assign(S, { deals: d.deals, stages: d.stages, sources: d.sources, users: d.users }); }
    if (view === 'chats') { const d = await api('/api/chats'); S.threads = d.threads || []; if (!S.threadId || !S.threads.some((t) => t.deal_id === S.threadId)) S.threadId = S.threads[0] && S.threads[0].deal_id; if (S.threadId) await openCard(S.threadId, true); }
    if (view === 'clients') { const d = await api('/api/clients' + clientQuery()); S.clients = d.clients; }
    if (view === 'calls') { const d = await api('/api/calls'); S.calls = d.calls; S.meta.telephony = d.telephony; }
    if (view === 'dash') S.stats = (await api('/api/stats'));
    if (view === 'admin') await loadAdmin(force);
  } catch (e) { toast(e.message, true); }
  if (S.user) { try { S.stats = await api('/api/stats'); } catch (e) { /* ignore */ } }
  render();
}
const dealQuery = () => '?' + new URLSearchParams(Object.entries(S.filters).filter(([, v]) => v));
const clientQuery = () => '?' + new URLSearchParams(Object.entries(S.clientFilter).filter(([, v]) => v));
async function loadAdmin(force) {
  const t = S.adminTab;
  try {
    if (t === 'users' || force) S.admin.users = (await api('/api/admin/users'));
    if (t === 'sources' || force) S.admin.sources = (await api('/api/admin/sources'));
    if (t === 'stages' || force) S.admin.stages = (await api('/api/admin/stages'));
    if (t === 'settings' || t === 'telephony' || force) S.admin.settings = (await api('/api/admin/settings'));
    if (t === 'log' || force) S.log = (await api('/api/log')).log;
  } catch (e) { toast('Админка: ' + e.message, true); }
}

/* ---------------------------------------------------------------- render */
function render() {
  const app = $('app');
  if (!S.user) { app.innerHTML = loginView(); return; }
  const side = S.newMode ? newCardForm() : (S.view === 'chats' ? '' : drawer());
  const a = document.activeElement;
  const keep = a && a.id && a.value !== undefined ? { id: a.id, pos: a.selectionStart } : null;
  app.innerHTML = `<div class="shell">${rail()}<div class="main">${topbar()}${pageView()}</div></div>
    <div class="toasts" id="toasts"></div>${side}`;
  if (keep && $(keep.id)) { const el = $(keep.id); el.focus(); try { el.setSelectionRange(keep.pos, keep.pos); } catch (e) {} }
  if (S.view === 'deals') hookDrag();
}
function loginView() {
  return `<div class="login"><form class="login-card" onsubmit="doLogin(event); return false">
    <h2>Усадьба·CRM</h2><div class="login-sub">бронирование площадок · чаты площадок + IP-телефония</div>
    <div class="field"><label>Логин</label><input class="inp" id="lgUser" autocomplete="username"></div>
    <div class="field"><label>Пароль</label><input class="inp" id="lgPass" type="password" autocomplete="current-password"></div>
    <button class="btn" style="width:100%;justify-content:center">Войти</button>
    <div class="login-hint">Демо-доступы (клик = подставить):<br>
      <b onclick="fillLogin('admin','admin123')">admin / admin123</b> — владелец<br>
      <b onclick="fillLogin('olga','demo123')">olga / demo123</b> — руководитель (видит всё)<br>
      <b onclick="fillLogin('marina','demo123')">marina / demo123</b> — менеджер (только свои сделки)</div>
  </form></div>`;
}
function rail() {
  const items = [
    ['deals', 'Сделки'], ['chats', 'Чаты'], ['clients', 'Клиенты'], ['calls', 'Звонки'], ['dash', 'Дашборд'],
  ];
  if (['manage_users', 'manage_sources', 'manage_stages', 'manage_settings', 'view_reports'].some(can)) items.push(['admin', 'Админка']);
  const unread = (S.stats && S.stats.unread) || 0;
  return `<div class="rail"><div class="brand">${esc(S.meta.company_name || 'Усадьба·CRM')}<span>прототип · amoCRM-style</span></div>
    ${items.map(([v, l]) => `<div class="rail-item${S.view === v ? ' active' : ''}" data-act="nav" data-v="${v}">${l}${v === 'chats' && unread ? `<span class="rail-badge">${unread}</span>` : ''}</div>`).join('')}
    <div class="rail-foot">подключено источников: ${S.meta.sources.filter((s) => s.enabled).length}<br>
      <b data-act="logout">выйти (${esc(S.user.login)})</b></div></div>`;
}
function topbar() {
  return `<div class="topbar">
    <div class="tb-search"><input class="inp" id="globalQ" placeholder="Поиск по телефону, имени, комментарию…" value="${esc(S.filters.q)}"></div>
    <div class="tb-right">
      ${S.stats && S.stats.unread ? `<span class="pill bad">${S.stats.unread} непрочитанных</span>` : '<span class="pill mute">нет новых сообщений</span>'}
      <div class="userchip"><div class="avatar">${esc(initials(S.user.name))}</div>
      <div>${esc(S.user.name)}<br><span style="color:var(--muted)">${esc(S.user.role_label)}</span></div></div>
    </div></div>`;
}
function pageView() {
  if (S.view === 'deals') return dealsPage();
  if (S.view === 'chats') return chatsPage();
  if (S.view === 'clients') return clientsPage();
  if (S.view === 'calls') return callsPage();
  if (S.view === 'dash') return dashPage();
  return adminPage();
}

/* ---------------------------------------------------------------- deals */
function srcPill(d) {
  return d.source_code ? `<span class="badge-src">${esc(d.source_name)}</span>` : '';
}
function chipsRow(d) {
  const bits = [];
  if (d.people) bits.push(d.people + ' чел');
  if (d.km) bits.push(d.km + ' км');
  (d.directions || []).forEach((x) => bits.push('↑' + x.toLowerCase()));
  return bits.map((b) => `<span class="chip sm">${esc(b)}</span>`).join('');
}
function dealsPage() {
  const stages = S.stages.slice().sort((a, b) => a.sort - b.sort);
  const cols = stages.map((st) => {
    const list = S.deals.filter((d) => d.stage_id === st.id);
    const sum = list.reduce((s, d) => s + (d.price || 0), 0);
    return `<div class="kcol" data-stage="${st.id}">
      <div class="kcol-head" style="border-top-color:${esc(st.color)}"><span>${esc(st.name)} <span class="cnt">${list.length}</span></span>
        <span style="font-size:11px;color:var(--muted)">${money(sum)}</span></div>
      <div class="kcol-body">${list.map(dealCard).join('') || '<div style="color:var(--muted);font-size:12px;padding:6px">пусто</div>'}</div></div>`;
  }).join('');
  return `<div class="page"><div class="page-head"><div><h1>Сделки — воронка бронирования</h1>
      <div class="sub">${S.deals.length} видно · прав: ${can('view_all_deals') ? 'все сделки' : 'только мои'}</div></div>
    <div class="head-actions">
      <select class="inp" id="demoSrc" style="width:auto">${S.meta.sources.filter((s) => s.enabled).map((s) => `<option value="${esc(s.code)}">${esc(s.name)}</option>`).join('')}</select>
      <button class="btn ghost" data-act="demoInbound">Симулировать входящее</button>
      ${can('edit_clients') ? '<button class="btn" data-act="newDeal">+ Новая сделка</button>' : ''}
    </div></div>
    <div class="toolbar">
      <label style="margin:0">Источник</label>
      <select class="inp" data-chg="fSource"><option value="">все</option>${S.meta.sources.map((s) => `<option value="${esc(s.code)}"${S.filters.source === s.code ? ' selected' : ''}>${esc(s.name)}${s.enabled ? '' : ' (выкл)'}</option>`).join('')}</select>
      <label style="margin:0">Менеджер</label>
      <select class="inp" data-chg="fOwner"><option value="">все</option>${S.users.map((u) => `<option value="${u.id}"${S.filters.owner == u.id ? ' selected' : ''}>${esc(u.name)}</option>`).join('')}</select>
      <button class="btn ghost sm" data-act="clearFilters">Сбросить</button>
      <span style="color:var(--muted);font-size:12px;margin-left:auto">перетаскивайте карточки между этапами</span>
    </div>
    <div class="kanban">${cols}</div></div>`;
}
function dealCard(d) {
  return `<div class="deal" data-id="${d.id}" data-act="openDeal" draggable="true" style="border-left-color:${esc(d.stage_color)}">
    <div class="deal-title"><span>${esc(d.client_name || 'Без имени')}</span>${d.unread ? `<span class="unread-dot">${d.unread}</span>` : ''}</div>
    <div class="deal-phone">${esc(d.phone_pretty || 'телефон не указан')}</div>
    <div class="deal-row">${srcPill(d)}${chipsRow(d)}</div>
    <div class="deal-row">${(d.criteria || []).slice(0, 3).map((c) => `<span class="chip sm">${esc(c)}</span>`).join('')}</div>
    <div class="deal-foot"><span class="budget">${money(d.price)}</span><span>${esc((d.owner_name || 'не назначен').split(' ')[0])} · ${ago(d.last_in)}</span></div>
  </div>`;
}

/* ---------------------------------------------------------------- chats */
function chatsPage() {
  const list = S.threads.map((t, i) => `<div class="thread${S.threadId === t.deal_id ? ' active' : ''}" data-act="openThread" data-id="${t.deal_id}">
    <div class="avatar" style="background:${t.unread ? 'var(--red)' : 'var(--blue)'}">${t.unread || initials(t.client_name)}</div>
    <div style="min-width:0"><div class="who">${esc(t.client_name)} ${t.source_code ? `<span class="badge-src">${esc(t.source_name)}</span>` : ''}</div>
      <div class="last">${esc((t.last_text || 'нет сообщений').slice(0, 60))}</div>
      <div style="font-size:11px;color:var(--muted)">${esc(t.phone || '')} · ${esc(t.stage_name || '')}</div></div>
    <div class="tm">${ago(t.last_in).replace(' назад', '')}</div></div>`).join('');
  const c = S.card;
  const pane = c ? `<div class="pane"><div class="pane-head">
      <div class="avatar">${esc(initials(c.deal.client_name))}</div>
      <div><b>${esc(c.deal.client_name)}</b> <span class="badge-src">${esc(c.deal.source_name || '')}</span>
      <div style="font-size:12px;color:var(--muted)">${esc(c.deal.phone_pretty || '')} · этап: ${esc(c.deal.stage_name)} · ${esc(c.deal.owner_name || 'без ответственного')}</div></div>
      <button class="btn ghost sm" style="margin-left:auto" data-act="cardFromChat" data-id="${c.deal.id}">Карточка →</button></div>
    <div class="pane-body"><div class="msgs">${msgsHtml(c.messages)}</div></div>
    ${can('send_messages') ? `<div class="reply" style="margin-top:10px"><textarea class="inp" id="chatReply" placeholder="Ответить в чат площадки (Enter — отправить)"></textarea>
      <button class="btn" data-act="sendReply" data-target="chatReply">Отправить</button></div>` : ''}
  </div>` : '<div class="empty">нет чатов</div>';
  return `<div class="page"><div class="page-head"><div><h1>Чаты площадок</h1>
      <div class="sub">Авито · ЦИАН · Яндекс · Spitti · Суточно · сайт — единое окно. Новый диалог = новая сделка.</div></div></div>
    <div class="threads"><div class="thread-list">${list || '<div class="empty">пусто</div>'}</div>${pane}</div></div>`;
}
function msgsHtml(msgs) {
  return (msgs || []).map((m) => `<div class="msg ${m.dir === 'out' ? 'out' : 'in'}">
    <div class="msg-meta"><span>${esc(m.author || (m.dir === 'out' ? 'мы' : 'гость'))}</span><span>${dt(m.created)}</span>
      ${m.unread ? '<span style="color:var(--red);font-weight:700">новое</span>' : ''}</div>${esc(m.text)}</div>`).join('');
}

/* ---------------------------------------------------------------- clients */
function clientsPage() {
  const rows = S.clients.map((c) => `<tr class="click" data-act="openClient" data-id="${c.id}" data-deal="${c.last_deal_id || ''}">
    <td><b>${esc(c.name)}</b><br><span style="color:var(--muted);font-size:12px">${esc(c.phone_pretty || c.phone || '')}</span></td>
    <td>${c.source_name ? `<span class="badge-src">${esc(c.source_name)}</span>` : '—'}</td>
    <td class="num">${money(c.budget)}</td><td class="num">${c.people || '—'}</td>
    <td>${(c.criteria || []).map((x) => `<span class="chip sm">${esc(x)}</span>`).join(' ') || '—'}</td>
    <td>${(c.directions || []).map((x) => `<span class="chip sm">${esc(x)}</span>`).join(' ')}${c.km ? ` <span style="color:var(--muted)">${c.km} км</span>` : ''}</td>
    <td>${esc(c.last_stage || 'нет сделки')}<br><span style="font-size:11px;color:var(--muted)">${esc(c.owner_name || '')}</span></td>
    <td style="font-size:12px;color:var(--muted)">${dt(c.updated)}</td></tr>`).join('');
  return `<div class="page"><div class="page-head"><div><h1>Клиенты</h1>
      <div class="sub">карточка клиента формируется автоматически из чата или звонка</div></div>
    <div class="head-actions">${can('edit_clients') ? '<button class="btn" data-act="newDeal">+ Новый клиент</button>' : ''}</div></div>
    <div class="toolbar">
      <input class="inp" id="clQ" placeholder="имя / телефон" value="${esc(S.clientFilter.q)}" style="width:200px">
      <select class="inp" data-chg="cSource"><option value="">все источники</option>${S.meta.sources.map((s) => `<option value="${esc(s.code)}"${S.clientFilter.source === s.code ? ' selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
      ${(S.meta.criteria_options || []).map((x) => `<span class="chip${S.clientFilter.criteria === x ? ' on' : ''}" data-act="cCrit" data-v="${esc(x)}">${esc(x)}</span>`).join('')}
      <button class="btn ghost sm" data-act="clearClients">Сброс</button>
      <span style="margin-left:auto;color:var(--muted);font-size:12px">${S.clients.length} карточек</span></div>
    <table class="table"><thead><tr><th>Клиент</th><th>Источник</th><th>Бюджет</th><th>Чел.</th>
      <th>Критерии поиска</th><th>Направление / км</th><th>Сделка</th><th>Обновлён</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="8" class="empty">ничего не найдено</td></tr>'}</tbody></table></div>`;
}

/* ---------------------------------------------------------------- calls */
function callsPage() {
  const t = S.meta.telephony || {};
  const rows = S.calls.map((c) => `<tr class="click" ${c.deal_id ? `data-act="openDeal" data-id="${c.deal_id}"` : ''}>
    <td>${dt(c.created)}</td><td>${c.dir === 'in' ? '↑ входящий' : '↓ исходящий'}</td>
    <td>${esc(c.phone)}</td><td>${esc(c.client_name || '—')}</td>
    <td>${c.status === 'missed' ? '<span class="pill bad">пропущен</span>' : '<span class="pill ok">' + (c.dur + ' c') + '</span>'}</td>
    <td>${esc(c.manager_name || '—')}</td><td>${esc(c.note || '')}</td>
    <td>${c.deal_id ? `<span class="pill mute">сделка #${c.deal_id}</span>` : ''}</td></tr>`).join('');
  return `<div class="page"><div class="page-head"><div><h1>Звонки</h1>
      <div class="sub">провайдер: ${esc(t.provider || '—')} · номер ${esc(t.number || '—')} · приём событий на <code>/webhook/call</code></div></div>
    <div class="head-actions">
      <button class="btn ghost" data-act="demoCall">Симулировать входящий звонок</button>
      <button class="btn ghost" data-act="gotoTelephony">Настроить телефонию</button></div></div>
    <table class="table"><thead><tr><th>Когда</th><th>Направление</th><th>Номер</th><th>Клиент</th><th>Статус</th>
      <th>Менеджер</th><th>Заметка</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="8" class="empty">звонков пока нет</td></tr>'}</tbody></table></div>`;
}

/* ---------------------------------------------------------------- dashboard */
function bars(rows, color) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return rows.map((r) => `<div class="bar-row"><div class="nm">${esc(r.name)}</div>
    <div class="track"><div class="fill" style="width:${(100 * r.value) / max}%;background:${color || 'var(--blue)'}"></div></div>
    <div class="val">${esc(r.label || r.value)}</div></div>`).join('') || '<div class="hint">нет данных</div>';
}
function dashPage() {
  const s = S.stats || { stages: [], sources: [], criteria: {}, directions: {} };
  const crit = Object.entries(s.criteria || {}).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  const dir = Object.entries(s.directions || {}).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  return `<div class="page"><div class="page-head"><div><h1>Дашборд</h1><div class="sub">всего в воронке · за всё время</div></div></div>
    <div class="tiles">
      <div class="tile"><div class="tile-k">Сделок активно</div><div class="tile-v">${s.active}</div><div class="tile-s">всего ${s.total}</div></div>
      <div class="tile"><div class="tile-k">В воронке</div><div class="tile-v">${money(s.pipeline_value)}</div><div class="tile-s">выиграно ${money(s.won_value)}</div></div>
      <div class="tile"><div class="tile-k">Конверсия</div><div class="tile-v">${s.conversion}%</div><div class="tile-s">${s.won} выиграно / ${s.lost} отказов</div></div>
      <div class="tile"><div class="tile-k">Новых за 7 дней</div><div class="tile-v">${s.week_new}</div><div class="tile-s">${s.unread} непрочитано</div></div>
    </div>
    <div class="cols"><div class="panel"><div class="panel-title">Этапы воронки</div>
      ${bars(s.stages.map((x) => ({ name: x.name, value: x.count, label: x.count + ' / ' + money(x.value) })))}</div>
      <div class="panel"><div class="panel-title">Источники обращений</div>
        ${bars(s.sources.map((x) => ({ name: x.name, value: x.count, label: x.count + ' / ' + money(x.value) })), '#7c5cf0')}</div></div>
    <div class="cols"><div class="panel"><div class="panel-title">Критерии поиска клиентов</div>${bars(crit, '#00a7a8')}</div>
      <div class="panel"><div class="panel-title">Направление от города</div>${bars(dir, '#f2a33c')}</div></div></div>`;
}

/* ---------------------------------------------------------------- drawer/card */
function drawer() {
  const c = S.card;
  if (!c) return '';
  const d = c.deal;
  const readonly = !can('edit_clients');
  const tabs = [['card', 'Карточка'], ['chat', 'Чат'], ['calls', 'Звонки'], ['hist', 'История']];
  let body = '';
  if (S.cardTab === 'card') body = cardForm(c, readonly);
  if (S.cardTab === 'chat') body = `<div class="msgs">${msgsHtml(c.messages)}</div>
    ${can('send_messages') ? `<div class="reply"><textarea class="inp" id="chatReply" placeholder="Ответ гостю…"></textarea>
      <button class="btn" data-act="sendReply" data-target="chatReply">Отправить</button></div>` : '<div class="hint">нет права «Отвечать в чатах»</div>'}`;
  if (S.cardTab === 'calls') body = callsTab(c);
  if (S.cardTab === 'hist') body = `<div class="kv"><div class="k">Сделка создана</div><div>${dt(d.created)}</div>
      <div class="k">Обновлена</div><div>${dt(d.updated)}</div><div class="k">Последнее входящее</div><div>${dt(d.last_in)}</div>
      <div class="k">ID сделки / клиента</div><div>#${d.id} / #${d.client_id}</div>
      <div class="k">Сообщений</div><div>${c.messages.length}</div><div class="k">Звонков</div><div>${c.calls.length}</div>
      <div class="k">Внешний id диалога</div><div>${esc((c.messages[0] || {}).chat_key || '—')}</div></div>
    <div class="hint" style="margin-top:10px">Здесь же прикручивается аудит: кто менял бюджет, кто переводил этап, кто писал гостю.</div>`;
  return `<div class="drawer"><div class="drawer-head">
      <div class="avatar">${esc(initials(d.client_name))}</div>
      <div><h2>${esc(d.client_name || 'Новый клиент')}</h2>
        <div class="meta">${esc(d.phone_pretty || 'телефон не указан')} · ${esc(d.source_name || 'без источника')} · <span class="pill" style="background:${esc(d.stage_color)};color:#fff">${esc(d.stage_name)}</span></div></div>
      <button class="btn ghost sm" style="margin-left:auto" data-act="closeCard">✕</button></div>
    <div class="tabs">${tabs.map(([k, l]) => `<div class="tab${S.cardTab === k ? ' active' : ''}" data-act="cardTab" data-t="${k}">${l}</div>`).join('')}</div>
    <div class="drawer-body">${body}</div></div>`;
}
function chipPicker(list, sel) {
  return `<div class="chips">${list.map((x) => `<span class="chip${sel.includes(x) ? ' on' : ''}" data-act="toggleChip">${esc(x)}</span>`).join('')}</div>`;
}
function cardForm(c, ro) {
  const d = c.deal;
  const srcOpts = S.meta.sources.filter((s) => s.enabled || s.id === (d.client_source_id || d.source_id));
  const dis = ro ? ' disabled' : '';
  return `<div class="grid2">
    <div class="field"><label>ФИО / название</label><input class="inp" id="clName" value="${esc(d.client_name)}"${dis}></div>
    <div class="field"><label>Номер телефона</label><input class="inp" id="clPhone" value="${esc(d.phone_pretty || d.client_phone || '')}" placeholder="+7 …"${dis}></div>
    <div class="field"><label>Источник</label><select class="inp" id="clSource"${dis}>${
      srcOpts.map((s) => `<option value="${esc(s.code)}"${(d.client_source_id || d.source_id) === s.id ? ' selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>
    <div class="field"><label>Бюджет, ₽</label><input class="inp" id="clBudget" type="number" value="${d.budget || ''}"${dis}></div>
    <div class="field"><label>Количество человек</label><input class="inp" id="clPeople" type="number" value="${d.people || ''}"${dis}></div>
    <div class="field"><label>Удалённость от города, км</label><input class="inp" id="clKm" type="number" value="${d.km || ''}"${dis}></div>
  </div>
  <div class="field"><label>Критерии поиска (мультивыбор)</label>${chipPicker(S.meta.criteria_options, d.criteria || [])}</div>
  <div class="field"><label>Направление от города (мультивыбор)</label>${chipPicker(S.meta.direction_options, d.directions || [])}</div>
  <div class="field"><label>Комментарий / пожелания</label><textarea class="inp" id="clComment"${dis}>${esc(d.comment || '')}</textarea></div>
  <div class="grid3">
    <div class="field"><label>Этап</label><select class="inp" id="cdStage"${dis}>${c.stages.map((s) => `<option value="${s.id}"${d.stage_id === s.id ? ' selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>
    <div class="field"><label>Ответственный</label><select class="inp" id="cdOwner"${dis}><option value="">не назначен</option>${c.users.map((u) => `<option value="${u.id}"${d.owner_id === u.id ? ' selected' : ''}>${esc(u.name)}</option>`).join('')}</select></div>
    <div class="field"><label>Сумма сделки, ₽</label><input class="inp" id="cdPrice" type="number" value="${d.price || 0}"${dis}></div>
  </div>
  <div class="field"><label>Название сделки</label><input class="inp" id="cdTitle" value="${esc(d.title)}"${dis}></div>
  ${ro ? '<div class="hint">У вашей роли нет права «Редактировать карточки» — поля только для чтения.</div>' : ''}
  <div class="card-actions">
    ${ro ? '' : `<button class="btn" data-act="saveCard">Сохранить</button>`}
    ${can('log_calls') ? `<button class="btn ghost" data-act="clickCall">Позвонить (click-to-call)</button>` : ''}
    ${can('edit_clients') ? `<button class="btn ghost" data-act="logCallWin">Отметить звонок</button>` : ''}
    ${can('delete_records') ? `<button class="btn danger" data-act="delDeal">Удалить сделку</button>` : ''}
  </div>`;
}
function callsTab(c) {
  const rows = c.calls.map((k) => `<tr><td>${dt(k.created)}</td><td>${k.dir === 'in' ? '↑' : '↓'} ${esc(k.status)}</td>
    <td>${k.dur} c</td><td>${esc(k.manager_name || '')}</td><td>${esc(k.note || '')} ${k.recording ? `<a href="${esc(k.recording)}">запись</a>` : ''}</td></tr>`).join('');
  return `<table class="table" style="margin-bottom:12px"><thead><tr><th>Когда</th><th>Тип</th><th>Длит.</th><th>Кто</th><th>Заметка</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="5" class="empty">звонков по этой сделке нет</td></tr>'}</tbody></table>
    <div class="grid3">
      <div class="field"><label>Статус</label><select class="inp" id="ncStatus"><option>answered</option><option>missed</option></select></div>
      <div class="field"><label>Длительность, сек</label><input class="inp" id="ncDur" type="number" value="120"></div>
      <div class="field"><label>&nbsp;</label><button class="btn" data-act="addCall" style="width:100%">Записать звонок</button></div>
    </div>
    <div class="field"><label>Заметка к звонку</label><input class="inp" id="ncNote" placeholder="обсудили даты, отправили смету"></div>
    <div class="hint">Номер для звонка: ${esc(c.deal.phone_pretty || '—')} · провайдер ${(S.meta.telephony || {}).provider || '—'}</div>`;
}

/* ---------------------------------------------------------------- new client/deal */
function newCardForm() {
  const src = S.meta.sources.filter((s) => s.enabled);
  return `<div class="drawer"><div class="drawer-head"><div class="avatar">+</div>
    <div><h2>Новый клиент / сделка</h2><div class="meta">карточка создаётся вручную (например, с телефона на стойке)</div></div>
    <button class="btn ghost sm" style="margin-left:auto" data-act="closeCard">✕</button></div>
    <div class="drawer-body"><div class="grid2">
      <div class="field"><label>ФИО / название</label><input class="inp" id="nwName"></div>
      <div class="field"><label>Номер телефона</label><input class="inp" id="nwPhone" placeholder="+7 …"></div>
      <div class="field"><label>Источник</label><select class="inp" id="nwSource">${src.map((s) => `<option value="${esc(s.code)}">${esc(s.name)}</option>`).join('')}</select></div>
      <div class="field"><label>Бюджет, ₽</label><input class="inp" id="nwBudget" type="number"></div>
      <div class="field"><label>Количество человек</label><input class="inp" id="nwPeople" type="number"></div>
      <div class="field"><label>Удалённость, км</label><input class="inp" id="nwKm" type="number"></div></div>
      <div class="field"><label>Критерии поиска</label><div class="chips" id="nwCrit">${S.meta.criteria_options.map((x) => `<span class="chip" data-act="toggleChip">${esc(x)}</span>`).join('')}</div></div>
      <div class="field"><label>Направление от города</label><div class="chips" id="nwDir">${S.meta.direction_options.map((x) => `<span class="chip" data-act="toggleChip">${esc(x)}</span>`).join('')}</div></div>
      <div class="field"><label>Комментарий</label><textarea class="inp" id="nwComment"></textarea></div>
      <div class="field"><label>Этап</label><select class="inp" id="nwStage">${S.stages.filter((s) => !s.outcome).map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select></div>
      <div class="card-actions"><button class="btn" data-act="createClient">Создать</button>
        <button class="btn ghost" data-act="closeCard">Отмена</button></div></div></div>`;
}

/* ---------------------------------------------------------------- admin */
function adminPage() {
  const tabs = [['sources', 'Источники чатов'], ['users', 'Пользователи и права'], ['stages', 'Воронка'],
                ['settings', 'Настройки'], ['telephony', 'IP-телефония'], ['log', 'Журнал действий'], ['api', 'API / вебхуки']];
  const visible = tabs.filter(([k]) => {
    if (k === 'users') return can('manage_users');
    if (k === 'sources') return can('manage_sources');
    if (k === 'stages') return can('manage_stages');
    if (k === 'settings' || k === 'telephony' || k === 'api') return can('manage_settings');
    return true;
  });
  if (!visible.some(([k]) => k === S.adminTab)) S.adminTab = visible[0] ? visible[0][0] : 'log';
  return `<div class="page"><div class="page-head"><div><h1>Админка</h1>
      <div class="sub">источники, пользователи и права, воронка, телефония</div></div></div>
    <div class="admin-tabs">${visible.map(([k, l]) => `<div class="admin-tab${S.adminTab === k ? ' active' : ''}" data-act="adminTab" data-t="${k}">${l}</div>`).join('')}</div>
    ${adminBody()}</div>`;
}
function adminBody() {
  const t = S.adminTab;
  if (t === 'sources') return adminSources();
  if (t === 'users') return adminUsers();
  if (t === 'stages') return adminStages();
  if (t === 'settings') return adminSettings();
  if (t === 'telephony') return adminTelephony();
  if (t === 'log') return adminLog();
  return adminApi();
}
function adminSources() {
  const rows = (S.admin.sources.sources || []).map((s) => `<tr>
    <td><b>${esc(s.name)}</b><br><code>${esc(s.code)}</code> · ${s.kind === 'telephony' ? 'телефония' : 'чат'}</td>
    <td>${s.api_state === 'official_api' ? '<span class="pill ok">офиц. API</span>' : s.api_state === 'partner_api' ? '<span class="pill warn">партнёрский API</span>' : s.api_state === 'no_public_api' ? '<span class="pill bad">публичного API нет</span>' : '<span class="pill mute">свой канал</span>'}</td>
    <td class="src-note">${esc(s.note || '')}</td>
    <td>${s.deals} / ${s.clients}</td>
    <td><select class="inp" data-chg="srcManager" data-id="${s.id}" style="width:140px"><option value="">по правилу</option>
      ${(S.admin.users.users || S.users).map((u) => `<option value="${u.id}"${s.manager_id === u.id ? ' selected' : ''}>${esc(u.name.split(' ')[0])}</option>`).join('')}</select></td>
    <td><label class="switch"><input type="checkbox" data-chg="srcEnabled" data-id="${s.id}"${s.enabled ? ' checked' : ''}> активен</label></td>
    <td><div class="row-actions"><button class="btn ghost sm" data-act="delSource" data-id="${s.id}">Удалить</button></div></td></tr>`).join('');
  return `<div class="panel"><div class="panel-title">Источники чатов и звонков
      <span class="hint">отключение = новые заявки не создаются, история сохраняется</span></div>
    <table class="table"><thead><tr><th>Источник</th><th>Доступность API</th><th>Как подключается</th><th>Сделок/клиентов</th>
      <th>Ответственный по источнику</th><th>Статус</th><th></th></tr></thead><tbody>${rows}</tbody></table>
    <div class="inline-form">
      <div><label>Название</label><input class="inp" id="nsName" placeholder="Booking.com"></div>
      <div><label>Код (латиницей)</label><input class="inp" id="nsCode" placeholder="booking"></div>
      <div><label>Тип</label><select class="inp" id="nsKind"><option value="chat">чат</option><option value="telephony">телефония</option></select></div>
      <div><label>Статус API</label><select class="inp" id="nsApi"><option value="own">свой канал</option><option value="official_api">офиц. API</option><option value="partner_api">партнёрский API</option><option value="no_public_api">публичного API нет</option></select></div>
      <div style="flex:1"><label>Комментарий / как получаем сообщения</label><input class="inp" id="nsNote"></div>
      <button class="btn" data-act="addSource">Добавить источник</button></div>
    <div class="hint" style="margin-top:10px">Любой добавленный источник сразу доступен интеграции: POST <code>/webhook/chat</code> с <code>"platform":"&lt;код&gt;"</code>.</div></div>`;
}
function adminUsers() {
  const d = S.admin.users;
  if (!d.users) return '<div class="empty">нет доступа или данные не загружены</div>';
  const rows = d.users.map((u) => `<tr>
    <td><div style="display:flex;gap:8px;align-items:center"><div class="avatar">${esc(initials(u.name))}</div>
      <div><b>${esc(u.name)}</b><br><span style="font-size:11.5px;color:var(--muted)">${esc(u.login)} · ${esc(u.phone)}</span></div></div></td>
    <td><select class="inp" data-chg="uRole" data-id="${u.id}" style="width:170px">${Object.entries(d.roles).map(([k, l]) => `<option value="${k}"${u.role === k ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select></td>
    <td>${u.perms.length} прав</td><td class="num">${u.deal_count}</td>
    <td><label class="switch"><input type="checkbox" data-chg="uActive" data-id="${u.id}"${u.active ? ' checked' : ''}${u.id === d.me.id ? ' disabled' : ''}> активен</label></td>
    <td><div class="row-actions">
      <button class="btn ghost sm" data-act="togglePerms" data-id="${u.id}">${S.expanded[u.id] ? 'скрыть права' : 'права'}</button>
      <button class="btn ghost sm" data-act="setPass" data-id="${u.id}">пароль</button>
      <button class="btn danger sm" data-act="delUser" data-id="${u.id}"${u.role === 'owner' ? ' disabled' : ''}>удалить</button></div></td></tr>
    ${S.expanded[u.id] ? `<tr><td colspan="6">${permEditor(u, d)}</td></tr>` : ''}`).join('');
  return `<div class="panel"><div class="panel-title">Пользователи<span class="hint">права перекрывают роль — можно точечно</span></div>
    <table class="table"><thead><tr><th>Сотрудник</th><th>Роль</th><th>Права</th><th>Сделок</th><th>Доступ</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div class="inline-form">
      <div><label>Имя</label><input class="inp" id="nuName" placeholder="Анна Петрова"></div>
      <div><label>Логин</label><input class="inp" id="nuLogin" placeholder="anna"></div>
      <div><label>Телефон</label><input class="inp" id="nuPhone" placeholder="+7…"></div>
      <div><label>Роль</label><select class="inp" id="nuRole">${Object.entries(d.roles).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('')}</select></div>
      <div><label>Пароль</label><input class="inp" id="nuPass" placeholder="мин. 5 символов"></div>
      <button class="btn" data-act="addUser">Добавить пользователя</button></div></div>
    <div class="panel"><div class="panel-title">Что дают права</div><div class="hint">${d.perm_defs.map((p) => `<b>${esc(p.label)}</b> — <code>${esc(p.key)}</code><br>`).join('')}</div></div>`;
}
function permEditor(u, d) {
  return `<div class="perm-grid">${d.perm_defs.map((p) => `<label><input type="checkbox" data-perm="${p.key}"${u.perms.includes(p.key) ? ' checked' : ''}${u.role === 'owner' ? ' disabled' : ''}> ${esc(p.label)} <span style="color:var(--muted)">(${esc(p.group)})</span></label>`).join('')}</div>
    <div style="margin-top:8px">${u.role === 'owner' ? '<span class="hint">владелец всегда имеет все права</span>' : `<button class="btn sm" data-act="savePerms" data-id="${u.id}">Сохранить права</button>`}</div>`;
}
function adminStages() {
  const rows = (S.admin.stages.stages || []).map((s) => `<tr>
    <td><input class="inp" value="${esc(s.name)}" data-st="name" data-id="${s.id}" style="width:190px"></td>
    <td><input class="inp" type="number" value="${s.prob}" data-st="prob" data-id="${s.id}" style="width:80px"></td>
    <td><input class="inp" type="number" value="${s.sort}" data-st="sort" data-id="${s.id}" style="width:80px"></td>
    <td><input class="inp" type="color" value="${esc(s.color)}" data-st="color" data-id="${s.id}" style="width:60px;height:34px;padding:2px"></td>
    <td><select class="inp" data-st="outcome" data-id="${s.id}" style="width:150px"><option value="">рабочий</option>
      <option value="win"${s.outcome === 'win' ? ' selected' : ''}>успех (закрывает)</option>
      <option value="lose"${s.outcome === 'lose' ? ' selected' : ''}>отказ (закрывает)</option></select></td>
    <td class="num">${s.cnt}</td><td>${esc(s.name)}</td>
    <td><button class="btn sm" data-act="saveStage" data-id="${s.id}">Сохранить</button>
      <button class="btn danger sm" data-act="delStage" data-id="${s.id}"${s.cnt ? ' disabled' : ''}>Удалить</button></td></tr>`).join('');
  return `<div class="panel"><div class="panel-title">Воронка этапов</div>
    <table class="table"><thead><tr><th>Название</th><th>Вероятность, %</th><th>Порядок</th><th>Цвет</th><th>Исход</th><th>Сделок</th><th></th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div class="inline-form"><div><label>Новый этап</label><input class="inp" id="nstName" placeholder="Депозит получен"></div>
      <div><label>Вероятность</label><input class="inp" id="nstProb" type="number" value="50" style="width:110px"></div>
      <button class="btn" data-act="addStage">Добавить</button></div>
    <div class="hint" style="margin-top:8px">«Успех» и «Отказ» — закрытые этапы: после перевода сделка перестаёт считаться активной и участвует в конверсии.</div></div>`;
}
function adminSettings() {
  const s = (S.admin.settings || {}).settings || {};
  return `<div class="panel"><div class="panel-title">Правила разбора входящих</div>
    <div class="grid2">
      <div class="field"><label>Название компании</label><input class="inp" id="stCompany" value="${esc(s.company_name || '')}"></div>
      <div class="field"><label>Кому назначать новую заявку</label><select class="inp" id="stAssign">
        <option value="round_robin"${s.assign_rule === 'round_robin' ? ' selected' : ''}>round-robin (кому меньше сделок)</option>
        <option value="source"${s.assign_rule === 'source' ? ' selected' : ''}>ответственному источника (см. Источники)</option>
        <option value="manual"${s.assign_rule === 'manual' ? ' selected' : ''}>не назначать (в входящие)</option></select></div>
    </div>
    <label class="switch"><input type="checkbox" id="stOneDeal"${s.one_open_deal_per_client === '1' ? ' checked' : ''}>
      одна открытая сделка на клиента (иначе — новая сделка на каждый диалог)</label>
    <div class="card-actions"><button class="btn" data-act="saveSettings">Сохранить правила</button></div></div>
    <div class="panel"><div class="panel-title">Токен входящих вебхуков</div>
      <div class="kv"><div class="k">Заголовок</div><div><code>X-Webhook-Token: ${esc(s.webhook_token || '')}</code></div>
        <div class="k">Чаты</div><div><code>POST ${esc((S.admin.settings || {}).webhook_base || '')}/webhook/chat</code></div>
        <div class="k">Звонки</div><div><code>POST ${esc((S.admin.settings || {}).webhook_base || '')}/webhook/call</code></div></div>
      <div class="card-actions"><button class="btn ghost" data-act="regenToken">Сгенерировать новый токен</button></div></div>
    <div class="panel"><div class="panel-title">Проверка авто-создания сделки</div>
      <div class="row-actions">${S.meta.sources.filter((x) => x.enabled).map((x) => `<button class="btn ghost sm" data-act="demoInbound" data-src="${esc(x.code)}">${esc(x.name)}</button>`).join('')}</div>
      <div class="hint" style="margin-top:8px">Клик = приходит фейковое сообщение с новым телефоном → CRM создаёт клиента, карточку и сделку на первом этапе.</div></div>`;
}
function adminTelephony() {
  const set = S.admin.settings || {};
  let t = {}; try { t = JSON.parse((set.settings || {}).telephony || '{}'); } catch (e) { t = {}; }
  return `<div class="panel"><div class="panel-title">IP-телефония<span class="hint">события приходят на <code>/webhook/call</code></span></div>
    <div class="grid2">
      <div class="field"><label>Провайдер</label><select class="inp" id="tpProvider">
        ${[['mango', 'Mango Office'], ['uis', 'UIS / МГТС'], ['zadarma', 'Zadarma'], ['sip', 'чистый SIP-транк (Asterisk/FreePBX)'], ['none', 'не подключено']].map(([v, l]) => `<option value="${v}"${t.provider === v ? ' selected' : ''}>${l}</option>`).join('')}</select></div>
      <div class="field"><label>Городской номер</label><input class="inp" id="tpNumber" value="${esc(t.number || '')}"></div>
      <div class="field"><label>Хост / IP-АТС</label><input class="inp" id="tpHost" value="${esc(t.sip_host || '')}" placeholder="pbx-1234.mango-office.ru"></div>
      <div class="field"><label>SIP-логин (внутренний)</label><input class="inp" id="tpTrunk" value="${esc(t.trunk || '')}"></div>
      <div class="field"><label>URL click-to-call (REST)</label><input class="inp" id="tpC2C" value="${esc(t.click_to_call_url || '')}" placeholder="https://…/dial"></div>
      <div class="field"><label>Токен API провайдера</label><input class="inp" id="tpToken" value="${esc(t.api_token || '')}"></div>
    </div>
    <label class="switch"><input type="checkbox" id="tpRec"${t.recordings ? ' checked' : ''}> писать записи разговоров</label>
    <div class="card-actions"><button class="btn" data-act="saveTelephony">Сохранить телефонию</button></div>
    <div class="hint" style="margin-top:10px">Что нужно от провайдера: (1) HTTP-callback на событие вызова (входящий/ответ/завершение, запись),
      (2) REST «позвонить на внутренний/мобильный» для click-to-call, (3) доступ к API записей. Дальше адаптер провайдера
      нормализует payload в наш формат — см. Админка → API.</div></div>`;
}
function adminLog() {
  return `<div class="panel"><div class="panel-title">Журнал действий</div>
    <table class="table"><thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Объект</th><th>Детали</th></tr></thead>
    <tbody>${(S.log || []).map((l) => `<tr><td>${dt(l.ts)}</td><td>${esc(l.user_name || 'система')}</td>
      <td><code>${esc(l.action)}</code></td><td>${esc(l.entity)} #${l.entity_id || ''}</td>
      <td style="font-size:12px;color:var(--muted)">${esc(l.data || '')}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">пусто</td></tr>'}</tbody></table></div>`;
}
function adminApi() {
  const tokv = ((S.admin.settings || {}).settings || {}).webhook_token || '…';
  const base = (S.admin.settings || {}).webhook_base || location.origin;
  return `<div class="panel"><div class="panel-title">Как подключать площадки</div>
    <div class="kv"><div class="k">Чат-событие</div><div>POST <code>${base}/webhook/chat</code></div>
      <div class="k">Звонок</div><div>POST <code>${base}/webhook/call</code></div>
      <div class="k">Авторизация</div><div>заголовок <code>X-Webhook-Token: ${esc(tokv)}</code></div>
      <div class="k">Ответ CRM</div><div><code>{deal_id, client_id, deal_new, client_new, source}</code></div></div></div>
    <div class="panel"><div class="panel-title">Пример: входящее сообщение с Авито</div><pre class="pre">curl -X POST ${base}/webhook/chat \\
  -H 'Content-Type: application/json' \\
  -H 'X-Webhook-Token: ${esc(tokv)}' \\
  -d '{
    "platform": "avito",
    "chat_id": "a1b2c3",
    "from": {"name": "Елена", "phone": "+7 926 555-11-22"},
    "text": "Ищем дом с бассейном на свадьбу, 60 человек, юг, до 40 км"
  }'</pre></div>
    <div class="panel"><div class="panel-title">Пример: событие из IP-телефонии</div><pre class="pre">curl -X POST ${base}/webhook/call \\
  -H 'Content-Type: application/json' \\
  -H 'X-Webhook-Token: ${esc(tokv)}' \\
  -d '{
    "event": "call_answered", "phone": "+7 916 123-45-67",
    "duration_sec": 214, "recording_url": "https://…/rec/9F2.wav",
    "manager_login": "marina", "note": "запрос на банкет 25 человек"
  }'</pre></div>
    <div class="panel"><div class="panel-title">Что делает CRM при входящем</div>
      <div class="hint">1) нормализует телефон и ищет клиента → 2) если клиента нет, создаёт карточку с источником →
      3) если открытой сделки нет, создаёт сделку на первом этапе и назначает ответственного по правилу →
      4) кладёт сообщение/звонок в ленту, поднимает счётчик непрочитанных → 5) пишет событие в журнал.
      Повторный webhook с тем же chat_id в открытую сделку не дублирует её.</div></div>`;
}

/* ---------------------------------------------------------------- card open/save */
async function openCard(id, keepTab) {
  try {
    S.card = await api('/api/deals/' + id);
    if (!keepTab) S.cardTab = 'card';
    S.newMode = false;
    render();
  } catch (e) { toast(e.message, true); }
}
const picked = (box) => Array.from((box || document).querySelectorAll('.chip.on')).map((c) => c.textContent.trim());
async function saveCard() {
  const c = S.card; if (!c) return;
  const body = {
    name: $('clName').value.trim(), phone: $('clPhone').value.trim(), source: $('clSource').value,
    budget: $('clBudget').value, people: $('clPeople').value, km: $('clKm').value,
    comment: $('clComment').value.trim(), criteria: pickedAll('.drawer', 0),
    directions: pickedAll('.drawer', 1),
  };
  const deal = { stage_id: $('cdStage').value, owner_id: $('cdOwner').value, price: $('cdPrice').value, title: $('cdTitle').value.trim() };
  await api('/api/clients/' + c.deal.client_id, body, 'PATCH');
  await api('/api/deals/' + c.deal.id, deal, 'PATCH');
  toast('Карточка сохранена');
  if (S.view === 'deals') Object.assign(S, await api('/api/deals' + dealQuery()));
  if (S.view === 'chats') S.threads = (await api('/api/chats')).threads;
  await openCard(c.deal.id, true);
}
function pickedAll(sel, second) {
  const boxes = document.querySelectorAll(sel + ' .chips');
  const b = boxes[second ? 1 : 0];
  return b ? Array.from(b.querySelectorAll('.chip.on')).map((x) => x.textContent.trim()) : [];
}

/* ---------------------------------------------------------------- actions */
const ACTS = {
  async nav(el) { await goto(el.dataset.v); },
  logout() { localStorage.removeItem('crm_sid'); S.user = null; S.card = null; render(); },
  async openDeal(el) { await openCard(el.dataset.id); },
  async openThread(el) { S.threadId = Number(el.dataset.id); await openCard(el.dataset.id, true); },
  async cardFromChat(el) { S.view = 'deals'; await goto('deals'); await openCard(el.dataset.id); },
  closeCard() { S.card = null; S.newMode = false; render(); },
  cardTab(el) { S.cardTab = el.dataset.t; render(); },
  newDeal() { S.newMode = true; render(); },
  toggleChip(el) { el.classList.toggle('on'); },
  async createClient() {
    const boxes = document.querySelectorAll('.drawer .chips');
    const c = await api('/api/clients', {
      name: $('nwName').value.trim() || 'Новый клиент', phone: $('nwPhone').value.trim(), source: $('nwSource').value,
      budget: $('nwBudget').value, people: $('nwPeople').value, km: $('nwKm').value, comment: $('nwComment').value,
      criteria: Array.from(boxes[0].querySelectorAll('.chip.on')).map((x) => x.textContent.trim()),
      directions: Array.from(boxes[1].querySelectorAll('.chip.on')).map((x) => x.textContent.trim()),
    });
    const d = await api('/api/deals', { client_id: c.client_id, source: $('nwSource').value, stage_id: $('nwStage').value, price: $('nwBudget').value });
    toast('Клиент и сделка созданы');
    S.newMode = false; await goto(S.view); await openCard(d.deal_id);
  },
  async saveCard() { try { await saveCard(); } catch (e) { toast(e.message, true); } },
  async delDeal(el) {
    if (!confirm('Удалить сделку вместе с перепиской?')) return;
    const id = el.dataset.id || (S.card && S.card.deal.id);
    try { await api('/api/deals/' + id, null, 'DELETE'); toast('Удалено'); S.card = null; await goto(S.view); }
    catch (e) { toast(e.message, true); }
  },
  async openClient(el) {
    let id = el.dataset.deal;
    if (!id) {
      if (!can('edit_clients')) return toast('нет права создавать сделки');
      const r = await api('/api/deals', { client_id: el.dataset.id });
      id = r.deal_id; toast('Создана сделка для клиента');
    }
    await openCard(id);
  },
  async clickCall() {
    try {
      const r = await api('/api/calls', { action: 'click_to_call', phone: S.card.deal.phone_pretty || S.card.deal.client_phone, deal_id: S.card.deal.id });
      toast('Клик-ту-колл: ' + r.dial + ' → ' + r.would_call + (r.provider ? ' (' + r.provider + ')' : ''));
    } catch (e) { toast(e.message, true); }
  },
  logCallWin() { S.cardTab = 'calls'; render(); },
  async addCall() {
    try {
      await api('/api/calls', { deal_id: S.card.deal.id, client_id: S.card.deal.client_id, phone: S.card.deal.phone_pretty,
        dir: 'out', status: $('ncStatus').value, dur: $('ncDur').value, note: $('ncNote').value.trim() });
      toast('Звонок записан'); await openCard(S.card.deal.id, true);
    } catch (e) { toast(e.message, true); }
  },
  async sendReply(el) {
    const box = $(el.dataset.target || 'chatReply');
    const text = (box.value || '').trim();
    if (!text) return;
    try {
      const id = el.dataset.deal || (S.card && S.card.deal.id);
      const r = await api('/api/deals/' + id + '/messages', { text });
      box.value = '';
      toast(r.sent_to_platform ? 'Отправлено в чат площадки' : 'Сохранено в CRM (отправка на площадку — через адаптер)');
      if (S.view === 'chats') S.threads = (await api('/api/chats')).threads;
      await openCard(id, true);
    } catch (e) { toast(e.message, true); }
  },
  async demoInbound(el) {
    const src = (el && el.dataset.src) || ($('demoSrc') && $('demoSrc').value) || 'avito';
    try {
      const r = await api('/api/demo/inbound', { source: src });
      toast(`Создано: клиент ${r.client_new ? 'новый' : 'найден'}, сделка #${r.deal_id}${r.deal_new ? ' — новая' : ' — пополнена'}`);
      await goto(S.view === 'admin' ? 'deals' : S.view, true);
      await openCard(r.deal_id);
    } catch (e) { toast(e.message, true); }
  },
  async demoCall() {
    try {
      const r = await api('/api/demo/inbound', { source: 'telephony' });
      toast(`Звонок → сделка #${r.deal_id}, клиент #${r.client_id}`);
      await goto('calls'); await openCard(r.deal_id);
    } catch (e) { toast(e.message, true); }
  },
  gotoTelephony() { if (!can('manage_settings')) return toast('нет доступа к настройкам'); S.view = 'admin'; S.adminTab = 'telephony'; goto('admin'); },
  async adminTab(el) { S.adminTab = el.dataset.t; await loadAdmin(); render(); },
  async addSource() {
    try {
      await api('/api/admin/sources', { name: $('nsName').value.trim(), code: $('nsCode').value.trim(),
        kind: $('nsKind').value, api_state: $('nsApi').value, note: $('nsNote').value.trim(), enabled: true });
      toast('Источник добавлен'); S.meta.sources = (await api('/api/session')).meta.sources;
      await loadAdmin(); render();
    } catch (e) { toast(e.message, true); }
  },
  async delSource(el) {
    if (!confirm('Удалить источник?')) return;
    try { await api('/api/admin/sources/' + el.dataset.id, null, 'DELETE'); toast('Источник удалён'); await loadAdmin(); render(); }
    catch (e) { toast(e.message, true); }
  },
  async addUser() {
    try {
      await api('/api/admin/users', { name: $('nuName').value.trim(), login: $('nuLogin').value.trim(),
        phone: $('nuPhone').value.trim(), role: $('nuRole').value, password: $('nuPass').value });
      toast('Пользователь добавлен'); await loadAdmin(); render();
    } catch (e) { toast(e.message, true); }
  },
  togglePerms(el) { S.expanded[el.dataset.id] = !S.expanded[el.dataset.id]; render(); },
  async savePerms(el) {
    const row = el.closest('tr');
    const perms = Array.from(row.querySelectorAll('input[data-perm]:checked')).map((i) => i.dataset.perm);
    try {
      await api('/api/admin/users/' + el.dataset.id, { perms }, 'PATCH');
      toast('Права сохранены (у активных сессий применятся при следующем запросе)'); await loadAdmin(); render();
    } catch (e) { toast(e.message, true); }
  },
  async setPass(el) {
    const p = prompt('Новый пароль (мин. 5 символов)');
    if (!p) return;
    try { await api('/api/admin/users/' + el.dataset.id, { password: p }, 'PATCH'); toast('Пароль обновлён'); }
    catch (e) { toast(e.message, true); }
  },
  async delUser(el) {
    if (!confirm('Удалить пользователя?')) return;
    try { await api('/api/admin/users/' + el.dataset.id, null, 'DELETE'); toast('Пользователь удалён'); await loadAdmin(); render(); }
    catch (e) { toast(e.message, true); }
  },
  async addStage() {
    try { await api('/api/admin/stages', { name: $('nstName').value.trim(), prob: $('nstProb').value }); await loadAdmin(); render(); }
    catch (e) { toast(e.message, true); }
  },
  async saveStage(el) {
    const g = (k) => document.querySelector(`[data-st="${k}"][data-id="${el.dataset.id}"]`).value;
    try {
      await api('/api/admin/stages/' + el.dataset.id, { name: g('name'), prob: g('prob'), sort: g('sort'), color: g('color'), outcome: g('outcome') }, 'PATCH');
      toast('Этап сохранён'); S.meta.stages = (await api('/api/session')).meta.stages; await loadAdmin(); render();
    } catch (e) { toast(e.message, true); }
  },
  async delStage(el) {
    try { await api('/api/admin/stages/' + el.dataset.id, null, 'DELETE'); await loadAdmin(); render(); }
    catch (e) { toast(e.message, true); }
  },
  async saveSettings() {
    try {
      await api('/api/admin/settings', { company_name: $('stCompany').value.trim(), assign_rule: $('stAssign').value,
        one_open_deal_per_client: $('stOneDeal').checked ? '1' : '0' }, 'PATCH');
      toast('Правила сохранены'); S.meta.company_name = $('stCompany').value.trim(); await loadAdmin(true); render();
    } catch (e) { toast(e.message, true); }
  },
  async regenToken() {
    try { await api('/api/admin/settings', { webhook_token: 'regen' }, 'PATCH'); await loadAdmin(true); render(); toast('Токен обновлён'); }
    catch (e) { toast(e.message, true); }
  },
  async saveTelephony() {
    const t = { provider: $('tpProvider').value, number: $('tpNumber').value.trim(), sip_host: $('tpHost').value.trim(),
      trunk: $('tpTrunk').value.trim(), click_to_call_url: $('tpC2C').value.trim(), api_token: $('tpToken').value.trim(),
      recordings: $('tpRec').checked };
    try { await api('/api/admin/settings', { telephony: t }, 'PATCH'); S.meta.telephony = t; toast('Телефония сохранена'); await loadAdmin(true); render(); }
    catch (e) { toast(e.message, true); }
  },
  async clearFilters() { S.filters = { q: '', source: '', owner: '' }; await goto('deals'); },
  async clearClients() { S.clientFilter = { q: '', source: '', criteria: '' }; await goto('clients'); },
  async cCrit(el) { S.clientFilter.criteria = S.clientFilter.criteria === el.dataset.v ? '' : el.dataset.v; await goto('clients'); },
};

const CHANGES = {
  async fSource(el) { S.filters.source = el.value; await goto('deals'); },
  async fOwner(el) { S.filters.owner = el.value; await goto('deals'); },
  async cSource(el) { S.clientFilter.source = el.value; await goto('clients'); },
  async srcEnabled(el) {
    try { await api('/api/admin/sources/' + el.dataset.id, { enabled: el.checked }, 'PATCH');
      S.meta.sources = (await api('/api/session')).meta.sources; toast(el.checked ? 'Источник включён' : 'Источник отключён'); await loadAdmin(); render(); }
    catch (e) { toast(e.message, true); el.checked = !el.checked; }
  },
  async srcManager(el) {
    try { await api('/api/admin/sources/' + el.dataset.id, { manager_id: el.value || null }, 'PATCH'); toast('Ответственный источника сохранён'); }
    catch (e) { toast(e.message, true); }
  },
  async uRole(el) {
    try { await api('/api/admin/users/' + el.dataset.id, { role: el.value }, 'PATCH'); toast('Роль обновлена'); await loadAdmin(); render(); }
    catch (e) { toast(e.message, true); }
  },
  async uActive(el) {
    try { await api('/api/admin/users/' + el.dataset.id, { active: el.checked }, 'PATCH'); toast(el.checked ? 'Доступ открыт' : 'Доступ закрыт'); await loadAdmin(); render(); }
    catch (e) { toast(e.message, true); el.checked = !el.checked; }
  },
};

function hookDrag() {
  let dragId = null;
  document.querySelectorAll('.deal[draggable]').forEach((c) => {
    c.addEventListener('dragstart', () => { dragId = c.dataset.id; });
  });
  document.querySelectorAll('.kcol').forEach((col) => {
    col.addEventListener('dragover', (e) => { e.preventDefault(); col.classList.add('over'); });
    col.addEventListener('dragleave', () => col.classList.remove('over'));
    col.addEventListener('drop', async (e) => {
      e.preventDefault(); col.classList.remove('over');
      if (!dragId) return;
      if (!can('edit_clients')) return toast('нет права менять сделку');
      try {
        await api('/api/deals/' + dragId, { stage_id: col.dataset.stage }, 'PATCH');
        await goto('deals');
      } catch (err) { toast(err.message, true); }
      dragId = null;
    });
  });
}

/* ---------------------------------------------------------------- wiring */
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  const fn = ACTS[el.dataset.act];
  if (fn) { e.preventDefault(); fn(el, e); }
});
document.addEventListener('change', (e) => {
  const el = e.target.closest('[data-chg]');
  if (!el) return;
  const fn = CHANGES[el.dataset.chg];
  if (fn) fn(el, e);
});
let t1 = null;
document.addEventListener('input', (e) => {
  if (e.target.id === 'globalQ') {
    clearTimeout(t1);
    t1 = setTimeout(async () => {
      const v = e.target.value.trim();
      if (S.view === 'clients') { S.clientFilter.q = v; return goto('clients'); }
      if (S.view === 'deals') S.filters.q = v; else { S.filters.q = v; S.view = 'deals'; }
      await goto('deals');
    }, 400);
  }
  if (e.target.id === 'clQ') {
    clearTimeout(t1);
    t1 = setTimeout(async () => { S.clientFilter.q = e.target.value.trim(); await goto('clients'); }, 400);
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    if (e.target.id === 'chatReply' && !e.shiftKey) { e.preventDefault(); ACTS.sendReply({ dataset: { target: 'chatReply' } }); }
    if (e.target.id === 'lgPass') doLogin(e);
    if (e.target.id === 'nsCode') ACTS.addSource();
    if (e.target.id === 'nuPass') ACTS.addUser();
  }
  if (e.key === 'Escape' && S.card) { S.card = null; S.newMode = false; render(); }
});
async function doLogin(ev) {
  ev.preventDefault();
  try {
    const r = await api('/api/login', { login: $('lgUser').value.trim(), password: $('lgPass').value });
    localStorage.setItem('crm_sid', r.token);
    const s = await api('/api/session');
    S.user = s.user; S.meta = s.meta;
    toast('Добро пожаловать, ' + S.user.name.split(' ')[0]);
    await goto('deals');
  } catch (e) { toast(e.message, true); }
}
function fillLogin(a, b) { $('lgUser').value = a; $('lgPass').value = b; }
window.doLogin = doLogin; window.fillLogin = fillLogin;
boot();
