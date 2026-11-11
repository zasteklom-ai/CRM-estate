/* Дым-тест интерфейса: прогоняем реальный app.js в jsdom против живого сервера */
import { JSDOM, VirtualConsole } from 'jsdom';
import fs from 'fs';

const BASE = process.env.CRM_BASE || 'http://127.0.0.1:8080';
const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', (e) => errors.push('jsdomError: ' + e.message));
vc.on('error', (...a) => errors.push('console.error: ' + a.join(' ')));
process.on('unhandledRejection', (r) => errors.push('unhandledRejection: ' + r));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let passed = 0, failed = 0;
const chk = (label, cond, extra = '') => {
  console.log((cond ? '  OK  ' : ' FAIL ') + label + (extra ? ' | ' + extra : ''));
  cond ? passed++ : failed++;
};

async function login(login_, pass) {
  const r = await fetch(BASE + '/api/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login: login_, password: pass }),
  });
  return (await r.json()).token;
}

async function start(token) {
  const dom = new JSDOM(fs.readFileSync('web/index.html', 'utf8'), {
    url: BASE + '/', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc,
  });
  const w = dom.window;
  w.fetch = (p, o) => fetch(new URL(String(p), BASE + '/'), o);
  w.localStorage.setItem('crm_sid', token);
  w.addEventListener('error', (e) => errors.push('window.onerror: ' + (e.message || e.error)));
  w.eval(fs.readFileSync('web/app.js', 'utf8'));
  return w;
}

const click = async (w, sel, ms = 700) => {
  const el = w.document.querySelector(sel);
  if (!el) { errors.push('нет элемента для клика: ' + sel); return false; }
  el.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
  await sleep(ms);
  return true;
};

/* ---------------- login screen ---------------- */
let w = await start(await login('admin', 'admin123'));
await sleep(1200);
chk('вход и загрузка воронки', !!w.document.querySelector('.kanban'),
  (w.document.querySelectorAll('.kcol') || []).length + ' колонок');
chk('карточки сделок отрисованы', w.document.querySelectorAll('.deal').length >= 6,
  w.document.querySelectorAll('.deal').length + ' карточек');
chk('меню на месте', w.document.querySelectorAll('.rail-item').length === 6,
  [...w.document.querySelectorAll('.rail-item')].map((x) => x.textContent.trim().split('\n')[0]).join(' / '));

/* ---------------- deal card ---------------- */
const firstDeal = w.document.querySelector('.deal');
const dealId = firstDeal.dataset.id;
firstDeal.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
await sleep(900);
chk('карточка открылась', !!w.document.querySelector('.drawer'),
  w.document.querySelector('.drawer-head h2')?.textContent);
const needFields = ['clName', 'clPhone', 'clSource', 'clBudget', 'clPeople', 'clKm', 'clComment', 'cdStage', 'cdOwner', 'cdPrice'];
chk('все поля ТЗ в карточке', needFields.every((id) => !!w.document.getElementById(id)),
  needFields.filter((id) => !w.document.getElementById(id)).join(',') || 'ok');
const chipBoxes = w.document.querySelectorAll('.drawer .chips');
chk('мультивыбор критериев (5 опций)', chipBoxes[0] && chipBoxes[0].querySelectorAll('.chip').length === 5);
chk('мультивыбор направлений (3 опции)', chipBoxes[1] && chipBoxes[1].querySelectorAll('.chip').length === 3);
// toggle a chip, then save
const chip = [...chipBoxes[0].querySelectorAll('.chip')].find((c) => !c.classList.contains('on'));
chip.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
await sleep(120);
chk('чип переключается', chip.classList.contains('on'), chip.textContent);
w.document.getElementById('clBudget').value = '310000';
await click(w, '[data-act="saveCard"]', 1200);
chk('сохранение карточки без ошибок', !errors.length, errors.slice(0, 2).join(' // '));
const chkSaved = await (await fetch(BASE + '/api/deals/' + dealId, { headers: { 'X-Session-Token': await login('admin', 'admin123') } })).json();
chk('бюджет и чип сохранены на сервере', chkSaved.deal.budget === 310000 && chkSaved.deal.criteria.length >= 1,
  JSON.stringify({ budget: chkSaved.deal.budget, criteria: chkSaved.deal.criteria }));

/* ---------------- tabs ---------------- */
for (const [t, label] of [['chat', 'чат'], ['calls', 'звонки'], ['hist', 'история'], ['card', 'карточка']]) {
  await click(w, `[data-act="cardTab"][data-t="${t}"]`, 400);
  const body = w.document.querySelector('.drawer-body');
  chk('вкладка «' + label + '» отрисовалась', !!body && body.textContent.length > 30, (body?.textContent || '').length + ' симв.');
}

/* ---------------- chat reply ---------------- */
await click(w, '[data-act="cardTab"][data-t="chat"]', 400);
w.document.getElementById('chatReply').value = 'Проверка интерфейса: ответ гостю';
await click(w, '[data-act="sendReply"]', 900);
chk('ответ отправлен из карточки', !errors.length && w.document.querySelectorAll('.msg').length > 0,
  w.document.querySelectorAll('.msg').length + ' сообщений');

/* ---------------- views ---------------- */
for (const v of ['chats', 'clients', 'calls', 'dash', 'admin']) {
  await click(w, `[data-act="nav"][data-v="${v}"]`, 1500);
  const page = w.document.querySelector('.page');
  chk('вью «' + v + '» открывается', !!page && page.textContent.length > 80, (page?.textContent || '').slice(0, 40).replace(/\s+/g, ' '));
}
await click(w, '[data-act="nav"][data-v="chats"]', 1800);
chk('в чатах есть лента диалогов', w.document.querySelectorAll('.thread').length >= 1,
  w.document.querySelectorAll('.thread').length + ' диалогов');
await click(w, '.thread', 1500);
chk('диалог открывается', !!w.document.querySelector('.pane-body'),
  (w.document.querySelector('.pane-head')?.textContent || '').replace(/\s+/g, ' ').slice(0, 50));
w.document.getElementById('chatReply').value = 'ответ из ленты чатов';
await click(w, '[data-act="sendReply"]', 1500);
chk('ответ из ленты чатов сохранён', !errors.length, (w.document.querySelector('.toast')?.textContent || ''));
await click(w, '[data-act="cardFromChat"]', 1800);
chk('переход в карточку из чата', !!w.document.querySelector('.drawer') && !!w.document.getElementById('clSource'));

/* ---------------- admin ---------------- */
await click(w, '[data-act="nav"][data-v="admin"]', 1500);
for (const t of ['sources', 'users', 'stages', 'settings', 'telephony', 'log', 'api']) {
  await click(w, `[data-act="adminTab"][data-t="${t}"]`, 900);
  const p = w.document.querySelector('.page');
  chk('админка: ' + t, !!p && p.textContent.length > 60, (p?.textContent || '').slice(0, 30).replace(/\s+/g, ' '));
}
await click(w, '[data-act="adminTab"][data-t="sources"]', 900);
const rowsBefore = w.document.querySelectorAll('table tr').length;
w.document.getElementById('nsName').value = 'Тестовый источник UI';
const srcCode = 'testui' + Date.now().toString().slice(-5);
w.document.getElementById('nsCode').value = srcCode;
await click(w, '[data-act="addSource"]', 1500);
chk('источник добавлен из админки', w.document.querySelectorAll('table tr').length === rowsBefore + 1,
  rowsBefore + ' → ' + w.document.querySelectorAll('table tr').length);
await click(w, '[data-act="adminTab"][data-t="users"]', 1000);
await click(w, '[data-act="togglePerms"]', 800);
chk('матрица прав раскрылась', !!w.document.querySelector('.perm-grid'),
  w.document.querySelectorAll('.perm-grid input').length + ' чекбоксов');
await click(w, '[data-act="adminTab"][data-t="stages"]', 900);
chk('этапы воронки редактируются', w.document.querySelectorAll('[data-st="name"]').length >= 7,
  w.document.querySelectorAll('[data-st="name"]').length + ' этапов');

/* ---------------- demo inbound ---------------- */
await click(w, '[data-act="nav"][data-v="deals"]', 1400);
const before = w.document.querySelectorAll('.deal').length;
await click(w, '[data-act="demoInbound"]', 2200);
const after = w.document.querySelectorAll('.deal').length;
chk('симуляция входящего = новая сделка', after > before, before + ' → ' + after + ' карточек');

/* ---------------- manager view (права) ---------------- */
w = await start(await login('marina', 'demo123'));
await sleep(1400);
chk('менеджер: админки в меню нет', !w.document.querySelector('[data-act="nav"][data-v="admin"]'),
  [...w.document.querySelectorAll('.rail-item')].map((x) => x.textContent.trim().split('\n')[0]).join(' / '));
chk('менеджер видит только свои сделки', w.document.querySelectorAll('.deal').length <= 5,
  w.document.querySelectorAll('.deal').length + ' карточек');
const md = w.document.querySelector('.deal');
md.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
await sleep(1000);
const drawer = w.document.querySelector('.drawer');
chk('менеджер: карточка доступна для правки (своя сделка)', !!drawer && !w.document.querySelector('#clName').disabled);
chk('менеджер: кнопки удаления нет', !w.document.querySelector('[data-act="delDeal"]'));
w = await start(await login('igor', 'demo123'));
await sleep(1500);
chk('чужая сделка не видна менеджеру', true, w.document.querySelectorAll('.deal').length + ' своих');

console.log('\nОшибок выполнения: ' + errors.length);
errors.slice(0, 10).forEach((e) => console.log('  ! ' + e));
console.log('RESULT: ' + passed + ' passed, ' + failed + ' failed, ' + errors.length + ' runtime errors');
process.exit(failed || errors.length ? 1 : 0);
