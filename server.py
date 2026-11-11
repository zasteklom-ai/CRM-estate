#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Усадьба·CRM — прототип CRM по образу amoCRM для бронирования загородных площадок.

Только стандартная библиотека Python: sqlite3 + http.server.
Запуск:  python3 server.py            (порт 8080, переменная CRM_PORT)
Сброс ДБ: rm -f crm.sqlite3 && python3 server.py
"""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CRM_DB") or os.path.join(ROOT, "crm.sqlite3")
WEB_DIR = os.path.join(ROOT, "web")
PORT = int(os.environ.get("CRM_PORT", "8080"))

CRITERIA = ["Баня", "Бассейн", "Банкет", "Свадьба", "Близость к городу"]
DIRECTIONS = ["Север", "Юг", "Восток"]

# ----------------------------------------------------------------权限 / permissions
PERM_DEFS = [
    {"key": "view_all_deals", "label": "Видеть все сделки (иначе только свои)", "group": "Данные"},
    {"key": "edit_clients", "label": "Редактировать карточки клиента и сделки", "group": "Данные"},
    {"key": "send_messages", "label": "Отвечать в чатах площадок", "group": "Данные"},
    {"key": "log_calls", "label": "Звонить из CRM и фиксировать звонки", "group": "Данные"},
    {"key": "delete_records", "label": "Удалять сделки и клиентов", "group": "Данные"},
    {"key": "manage_sources", "label": "Источники чатов: добавлять и отключать", "group": "Админка"},
    {"key": "manage_users", "label": "Пользователи: создавать, удалять, менять права", "group": "Админка"},
    {"key": "manage_stages", "label": "Настраивать воронку (этапы)", "group": "Админка"},
    {"key": "manage_settings", "label": "Настройки, телефония, вебхук-токен", "group": "Админка"},
    {"key": "view_reports", "label": "Дашборд и отчёты", "group": "Админка"},
]
PERM_KEYS = [p["key"] for p in PERM_DEFS]
ROLES = {
    "owner": "Владелец (все права)",
    "supervisor": "Руководитель отдела",
    "manager": "Менеджер",
    "viewer": "Наблюдатель",
}
ROLE_DEFAULTS = {
    "owner": list(PERM_KEYS),
    "supervisor": ["view_all_deals", "edit_clients", "send_messages", "log_calls",
                   "delete_records", "manage_stages", "view_reports"],
    "manager": ["edit_clients", "send_messages", "log_calls"],
    "viewer": ["view_all_deals", "view_reports"],
}

# ------------------------------------------------------------------ БД / database
SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'chat', api_state TEXT DEFAULT 'unknown',
  enabled INTEGER NOT NULL DEFAULT 1, position INTEGER NOT NULL DEFAULT 0,
  manager_id INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  phone TEXT DEFAULT '', role TEXT NOT NULL DEFAULT 'manager',
  perms TEXT NOT NULL DEFAULT '[]', active INTEGER NOT NULL DEFAULT 1,
  salt TEXT NOT NULL, hash TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS stages(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, sort INTEGER NOT NULL DEFAULT 0,
  prob INTEGER NOT NULL DEFAULT 50, color TEXT DEFAULT '#8a94a6',
  outcome TEXT);
CREATE TABLE IF NOT EXISTS clients(
  id INTEGER PRIMARY KEY, name TEXT DEFAULT '', phone TEXT DEFAULT '',
  phone_norm TEXT, source_id INTEGER, budget INTEGER, people INTEGER, km INTEGER,
  criteria TEXT DEFAULT '[]', directions TEXT DEFAULT '[]', comment TEXT DEFAULT '',
  external_ref TEXT DEFAULT '', owner_id INTEGER,
  created INTEGER NOT NULL, updated INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_clients_phone ON clients(phone_norm);
CREATE TABLE IF NOT EXISTS deals(
  id INTEGER PRIMARY KEY, title TEXT, client_id INTEGER, stage_id INTEGER NOT NULL,
  source_id INTEGER, owner_id INTEGER, price INTEGER DEFAULT 0,
  created INTEGER NOT NULL, updated INTEGER NOT NULL, last_in INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_deals_stage ON deals(stage_id);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY, deal_id INTEGER NOT NULL, chat_key TEXT,
  source_id INTEGER, dir TEXT NOT NULL, author TEXT DEFAULT '', text TEXT DEFAULT '',
  created INTEGER NOT NULL, unread INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_messages_deal ON messages(deal_id);
CREATE TABLE IF NOT EXISTS calls(
  id INTEGER PRIMARY KEY, deal_id INTEGER, client_id INTEGER, phone TEXT,
  dir TEXT NOT NULL, status TEXT DEFAULT 'answered', dur INTEGER DEFAULT 0,
  manager_id INTEGER, recording TEXT DEFAULT '', note TEXT DEFAULT '',
  created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS activity(
  id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, user_id INTEGER,
  action TEXT, entity TEXT, entity_id INTEGER, data TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS counters(name TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""

SOURCE_SEED = [
    ("avito", "Авито", "chat", "official_api", "Официальный Avito API (OAuth2): сообщения/чаты + объявления. Нужен статус партнёра и токен."),
    ("cian", "ЦИАН", "chat", "no_public_api", "Публичного API чатов нет. Пути: подменные номера ЦИАН (звонки), партнёрский кабинет, почтовый форвардинг или шлюз-расширение."),
    ("yandex_realty", "Янд. Недв.", "chat", "no_public_api", "Яндекс Недвижимость: заявок/чатов через открытый API нет — форвардинг на email/telegram-бот + ручной ввод либо договор с Яндекс."),
    ("yandex_travel", "Янд. Путеш.", "chat", "partner_api", "Яндекс Путешествия: партнёрский API отелей (брони, календарь). Сообщения — из партнёрского кабинета."),
    ("spitti", "Spitti", "chat", "official_api", "Spitti (RMS/канел-менеджер) отдаёт события броней и мессенджеры через свой API/вебхуки — подключаем входящим вебхуком."),
    ("sutochno", "Суточно.ру", "chat", "partner_api", "Суточно.ру: Partner API (брони, события) и синхронизация через channel-manager (Контур.Отель, Travelline, Spitti)."),
    ("telephony", "IP-телефония", "telephony", "sip", "Mango Office / UIS / Zadarma / SIP-транк: HTTP callback по событию вызова + REST click-to-call."),
    ("website", "Сайт / форма", "chat", "own", "Форма на сайте, Telegram-бот, email — собственный входящий вебхук."),
]

STAGE_SEED = [
    ("Новая заявка", 1, 10, "#4b8bf4", None),
    ("Квалификация", 2, 25, "#7c5cf0", None),
    ("Подбор даты", 3, 45, "#00a7a8", None),
    ("Бронь / предоплата", 4, 70, "#f2a33c", None),
    ("Заезд / проведение", 5, 90, "#3cb878", None),
    ("Успешно", 6, 100, "#2ecc71", "win"),
    ("Отказ / не целевой", 7, 0, "#e05a5a", "lose"),
]

USER_SEED = [
    ("admin", "Виктория Рыбак (владелец)", "+79161000001", "owner", "admin123"),
    ("olga", "Ольга Ким (РО)", "+79161000002", "supervisor", "demo123"),
    ("marina", "Марина Соболева", "+79161000003", "manager", "demo123"),
    ("igor", "Игорь Лаптев", "+79161000004", "manager", "demo123"),
]

CLIENT_SEED = [
    ("Елена Тропина", "+79265551122", "avito", 320000, 60, ["Банкет", "Близость к городу"], ["Север"], 18,
     "Юбилей 50 лет, нужен зал и ведущий"),
    ("Артур и Дарья", "+79037778899", "avito", 480000, 85, ["Свадьба", "Банкет", "Бассейн"], ["Юг"], 42,
     "Свадьба в августе, живём за городом"),
    ("Михаил Дюжев", "+79162223344", "cian", 150000, 12, ["Баня", "Бассейн"], ["Восток"], 60,
     "Дом с бассейном и баней на выходные"),
    ("ООО «Прайм»", "+79850001122", "sutochno", 95000, 25, ["Банкет", "Близость к городу"], ["Север"], 9,
     "Корпоратив, питание, парковка"),
    ("Светлана Ерохина", "+79269998877", "yandex_travel", 210000, 40, ["Свадьба"], ["Юг"], 35,
     "Просьба прислать фото террасы"),
    ("Роман Кузьмин", "+79167654321", "spitti", 78000, 8, ["Баня", "Бассейн"], ["Восток"], 75,
     "Новый год компанией"),
    ("Алина Гринёва", "+79055556677", "website", 260000, 55, ["Банкет", "Свадьба", "Баня"], ["Юг", "Восток"], 27, ""),
    ("Тимур Валеев", "+79173332211", "telephony", 130000, 20, ["Банкет", "Близость к городу"], ["Север"], 12,
     "Звонил сам, просил счёт на 20 чел"),
]

CHAT_SEED = {
    "Елена Тропина": [
        ("in", "Гость", "Здравствуйте! Есть свободные даты на 15 июня? Нужно 60 человек и банкетный зал."),
        ("out", "Марина Соболева", "Добрый день! На 15 июня естьMain hall, уточните пожалуйста бюджет и нужен ли ведущий."),
        ("in", "Гость", "Бюджет около 320, ведущего ищите сами. Бассейн обязателен? Нет, достаточноCloseality к городу."),
    ],
    "Артур и Дарья": [
        ("in", "Гость", "Ищем площадку под свадьбу, 85 гостей, август. Есть терраса и бассейн?"),
        ("out", "Игорь Лаптев", "Есть! Скину планировку и фото, сценарий заезда с 14:00."),
        ("in", "Гость", "Спасибо, обсудим с семьёй и вернёмся вечером."),
    ],
    "Михаил Дюжев": [
        ("in", "Гость", "Дом с баней и бассейном на 12 человек, восток, до 70 км. Что есть на 22 февраля?"),
    ],
    "ООО «Прайм»": [
        ("in", "Гость", "Корпоратив 25 человек, питание, парковка, нужен близко к городу."),
        ("out", "Ольга Ким", "Добрый день! Предложу зал + кейтеринг, пришлю смету в течение дня."),
    ],
}


def now():
    return int(time.time())


def conn():
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def allrows(sql, args=()):
    c = conn(); r = [dict(x) for x in c.execute(sql, args).fetchall()]; c.close(); return r


def onerow(sql, args=()):
    c = conn(); r = c.execute(sql, args).fetchone(); c.close(); return dict(r) if r else None


def scalar(sql, args=()):
    r = onerow(sql, args)
    if not r:
        return None
    return list(r.values())[0]


def run(sql, args=()):
    c = conn(); cur = c.execute(sql, args); c.commit(); lid = cur.lastrowid; c.close(); return lid


def hashes(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 40000).hex()
    return salt, h


def check_pw(pw, salt, h):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 40000).hex() == h


def norm_phone(raw):
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 11 and d[0] in "78":
        d = d[1:]
    if len(d) == 10:
        d = "7" + d
    if len(d) == 12 and d.startswith("88"):
        d = d[1:]
    return d if len(d) == 11 else (d or None)


def pretty_phone(d):
    if not d or len(d) != 11:
        return d or ""
    return "+%s (%s) %s-%s-%s" % (d[0], d[1:4], d[4:7], d[7:9], d[9:11])


def phones_in_text(text):
    return [p for p in re.findall(r"\+?\d[\d\s\-()]{7,}\d", text or "") if norm_phone(p)]


def setting(key, default=None):
    v = scalar("SELECT value FROM settings WHERE key=?", (key,))
    return v if v is not None else default


def set_setting(key, value):
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))


def perms_of(user):
    if not user:
        return set()
    if user.get("role") == "owner":
        return set(PERM_KEYS)
    try:
        return set(json.loads(user.get("perms") or "[]"))
    except Exception:
        return set()


def next_counter(name):
    run("INSERT INTO counters(name,value) VALUES(?,1) ON CONFLICT(name) DO UPDATE SET value=value+1", (name,))
    return scalar("SELECT value FROM counters WHERE name=?", (name,))


def log(user_id, action, entity, entity_id, data=None):
    run("INSERT INTO activity(ts,user_id,action,entity,entity_id,data) VALUES(?,?,?,?,?,?)",
        (now(), user_id, action, entity, entity_id, json.dumps(data, ensure_ascii=False) if data else None))


# ---------------------------------------------------------------------- seed
def seed():
    c = conn()
    c.executescript(SCHEMA)
    c.commit()
    if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        for i, (code, name, kind, api_state, note) in enumerate(SOURCE_SEED):
            c.execute("INSERT INTO sources(code,name,kind,api_state,enabled,position,note) VALUES(?,?,?, ?,1,?,?)",
                      (code, name, kind, api_state, i, note))
        for name, sort, prob, color, outcome in STAGE_SEED:
            c.execute("INSERT INTO stages(name,sort,prob,color,outcome) VALUES(?,?,?,?,?)",
                      (name, sort, prob, color, outcome))
        for login, name, phone, role, pw in USER_SEED:
            salt, h = hashes(pw)
            c.execute("INSERT INTO users(login,name,phone,role,perms,active,salt,hash,created) VALUES(?,?,?,?,?,?,?, ?,?)",
                      (login, name, phone, role, json.dumps(ROLE_DEFAULTS[role]), 1, salt, h, now()))
        c.commit()
        set_setting("webhook_token", secrets.token_hex(12))
        set_setting("assign_rule", "round_robin")
        set_setting("one_open_deal_per_client", "1")
        set_setting("company_name", "Усадьба «Сосновый берег»")
        set_setting("telephony", json.dumps({
            "provider": "mango", "sip_host": "pbx-3812.mango-office.ru", "trunk": "",
            "number": "+7 (495) 120-34-56", "callback_url": "", "click_to_call_url": "",
            "api_token": "", "recordings": True}, ensure_ascii=False))
        c.close()
        seed_demo()
    else:
        c.close()


def seed_demo():
    stages = allrows("SELECT * FROM stages ORDER BY sort")
    sources = {r["code"]: r for r in allrows("SELECT * FROM sources")}
    users = {r["login"]: r for r in allrows("SELECT * FROM users")}
    managers = [users["marina"], users["igor"], users["olga"]]
    plan = [(0, 0), (0, 1), (1, 1), (2, 2), (3, 3), (4, 3), (5, 6), (6, 4)]
    for idx, (ci, si) in enumerate(plan):
        name, phone, code, budget, people, crit, dirs, km, comment = CLIENT_SEED[ci]
        src = sources[code]
        pn = norm_phone(phone)
        ts = now() - (25 - idx * 2) * 86400
        cid = run("INSERT INTO clients(name,phone,phone_norm,source_id,budget,people,km,criteria,directions,comment,owner_id,created,updated)"
                  " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (name, pretty_phone(pn), pn, src["id"], budget, people, km,
                   json.dumps(crit, ensure_ascii=False), json.dumps(dirs, ensure_ascii=False),
                   comment, managers[idx % 3]["id"], ts, ts))
        owner = managers[idx % 3]
        did = run("INSERT INTO deals(title,client_id,stage_id,source_id,owner_id,price,created,updated,last_in)"
                  " VALUES(?,?,?,?,?,?,?,?,?)",
                  ("Бронирование площадки · " + src["name"], cid, stages[si]["id"], src["id"],
                   owner["id"], budget, ts, ts, ts))
        msgs = CHAT_SEED.get(name)
        if msgs:
            for j, (d, who, text) in enumerate(msgs):
                run("INSERT INTO messages(deal_id,chat_key,source_id,dir,author,text,created,unread) VALUES(?,?,?,?,?,?,?,?)",
                    (did, "seed-%d" % did, src["id"], d, who, text, ts + j * 900, 1 if (d == "in" and j == len(msgs) - 1) else 0))
        if code == "telephony":
            run("INSERT INTO calls(deal_id,client_id,phone,dir,status,dur,manager_id,note,created) VALUES(?,?,?,?,?,?,?,?,?)",
                (did, cid, pretty_phone(pn), "in", "answered", 312, owner["id"], "Первичная консультация", ts))
        if si >= 3:
            run("INSERT INTO calls(deal_id,client_id,phone,dir,status,dur,manager_id,note,created) VALUES(?,?,?,?,?,?,?,?,?)",
                (did, cid, pretty_phone(pn), "out", "answered", 178, owner["id"], "Прошу счёт и даты", ts + 7200))
    run("INSERT INTO activity(ts,user_id,action,entity,entity_id,data) VALUES(?,?,?,?,?,?)",
        (now() - 3600, users["admin"]["id"], "demo_seed", "system", None, None))


# ------------------------------------------------------------------ бизнес-логика
def enabled_source(code):
    s = onerow("SELECT * FROM sources WHERE code=? OR name=?", (code, code))
    if not s:
        for r in allrows("SELECT * FROM sources"):
            if (code or "").lower().startswith(r["code"][:4]) or r["code"].lower() in (code or "").lower():
                s = r
                break
    return s


def pick_owner(source_row=None):
    rule = setting("assign_rule", "round_robin")
    if rule == "manual":
        return None
    if source_row and source_row.get("manager_id"):
        u = onerow("SELECT * FROM users WHERE id=? AND active=1", (source_row["manager_id"],))
        if u:
            return u["id"]
    if rule == "source":
        return None
    pool = [u for u in allrows("SELECT * FROM users WHERE active=1")
            if u["role"] in ("manager", "supervisor") and "send_messages" in perms_of(u)]
    if not pool:
        return None
    def load(u):
        return scalar("SELECT COUNT(*) FROM deals d JOIN stages s ON s.id=d.stage_id "
                      "WHERE d.owner_id=? AND s.outcome IS NULL", (u["id"],)) or 0
    return min(pool, key=load)["id"]


def find_or_create_client(c, phone, name=None, source_id=None, external_ref=""):
    pn = norm_phone(phone)
    if pn:
        row = onerow("SELECT * FROM clients WHERE phone_norm=?", (pn,))
        if row:
            changed = {}
            if source_id and not row["source_id"]:
                c.execute("UPDATE clients SET source_id=?, updated=? WHERE id=?", (source_id, now(), row["id"]))
            return dict(row), False
    row = None
    if external_ref:
        row = onerow("SELECT * FROM clients WHERE external_ref=? AND external_ref!=''", (external_ref,))
    if row:
        return row, False
    ts = now()
    cid = c.execute("INSERT INTO clients(name,phone,phone_norm,source_id,external_ref,owner_id,created,updated)"
                    " VALUES(?,?,?,?,?,?,?,?) RETURNING id",
                    (name or "Новый клиент", pretty_phone(pn) if pn else (phone or ""), pn, source_id,
                     external_ref or "", None, ts, ts)).fetchone()[0]
    row = dict(c.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone())
    return row, True


def open_deal_for(c, client_id):
    return onerow("SELECT d.* FROM deals d JOIN stages s ON s.id=d.stage_id "
                  "WHERE d.client_id=? AND s.outcome IS NULL ORDER BY d.id DESC", (client_id,))


def ensure_deal(c, client, source, title=None):
    """Создаёт сделку по входящему обращению, если политика этого требует."""
    if setting("one_open_deal_per_client", "1") == "1":
        d = open_deal_for(c, client["id"])
        if d:
            return d, False
    first = onerow("SELECT * FROM stages ORDER BY sort LIMIT 1")
    owner = pick_owner(source)
    ts = now()
    did = c.execute("INSERT INTO deals(title,client_id,stage_id,source_id,owner_id,price,created,updated,last_in)"
                    " VALUES(?,?,?,?,?,?,?,?,?) RETURNING id",
                    (title or ("Новое обращение · " + (source["name"] if source else "—")),
                     client["id"], first["id"], source["id"] if source else None, owner,
                     client["budget"] or 0, ts, ts, ts)).fetchone()[0]
    if owner:
        c.execute("UPDATE clients SET owner_id=?, updated=? WHERE id=? AND (owner_id IS NULL OR owner_id=?)",
                  (owner, ts, client["id"], None))
    return dict(c.execute("SELECT * FROM deals WHERE id=?", (did,)).fetchone()), True


def inbound_message(source_code, chat_key, text, author="Гость", phone=None,
                    client_name=None, user_id=None, external_ref=""):
    src = enabled_source(source_code)
    if not src:
        raise ApiError("источник '%s' не найден — добавьте его в Админка → Источники" % source_code, 400)
    if not src["enabled"]:
        raise ApiError("источник '%s' отключён" % src["name"], 409)
    found = phones_in_text(text)
    phone = phone or (found[0] if found else None)
    c = conn()
    client, client_new = find_or_create_client(c, phone or chat_key or "unknown", client_name, src["id"], external_ref)
    if not client_new:
        emptyish = not (client["name"] or "").strip() or client["name"] == "Новый клиент"
        if emptyish and client_name:
            c.execute("UPDATE clients SET name=?, updated=? WHERE id=?", (client_name, now(), client["id"]))
            client["name"] = client_name
        if not client["phone_norm"] and phone and norm_phone(phone):
            c.execute("UPDATE clients SET phone=?, phone_norm=?, updated=? WHERE id=?",
                      (pretty_phone(norm_phone(phone)), norm_phone(phone), now(), client["id"]))
    deal, deal_new = ensure_deal(c, client, src)
    mid = c.execute("INSERT INTO messages(deal_id,chat_key,source_id,dir,author,text,created,unread)"
                    " VALUES(?,?,?,?,?,?,?,1) RETURNING id",
                    (deal["id"], chat_key or ("auto-%d" % deal["id"]), src["id"], "in",
                     author, text, now())).fetchone()[0]
    c.execute("UPDATE deals SET last_in=?, updated=? WHERE id=?", (now(), now(), deal["id"]))
    c.commit()
    c.close()
    log(user_id, "inbound_message", "deal", deal["id"],
        {"source": src["code"], "client_new": client_new, "deal_new": deal_new})
    return {"message_id": mid, "deal_id": deal["id"], "deal_new": deal_new,
            "client_id": client["id"], "client_new": client_new,
            "source": {"id": src["id"], "code": src["code"], "name": src["name"]},
            "unread": scalar("SELECT COUNT(*) FROM messages WHERE deal_id=? AND unread=1", (deal["id"],))}


def inbound_call(payload, user_id=None):
    """Событие从 IP-телефонии: формирует сделку и карточку клиента."""
    src = enabled_source(payload.get("source") or "telephony") or \
          onerow("SELECT * FROM sources WHERE kind='telephony' LIMIT 1")
    phone = payload.get("phone") or payload.get("from") or payload.get("caller")
    found = phones_in_text(phone)
    if found:
        phone = found[0]
    pn = norm_phone(phone) or "unknown"
    name = payload.get("name") or ("Гость с %s" % pretty_phone(pn) if pn != "unknown" else "Неизвестный номер")
    c = conn()
    client, client_new = find_or_create_client(c, pn, name, src["id"] if src else None)
    deal, deal_new = ensure_deal(c, client, src)
    status = payload.get("status") or ("missed" if payload.get("event") in ("call_missed", "no_answer") else "answered")
    dur = int(payload.get("duration_sec") or payload.get("dur") or 0)
    manager = None
    login = payload.get("manager_login") or payload.get("user")
    if login:
        u = onerow("SELECT * FROM users WHERE login=?", (login,))
        manager = u["id"] if u else None
    manager = manager or deal["owner_id"]
    cid = c.execute("INSERT INTO calls(deal_id,client_id,phone,dir,status,dur,manager_id,recording,note,created)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?) RETURNING id",
                    (deal["id"], client["id"], pretty_phone(pn) if pn != "unknown" else phone,
                     payload.get("dir") or "in", status, dur, manager,
                     payload.get("recording_url") or payload.get("recording") or "",
                     payload.get("note") or payload.get("event") or "Звонок из телефонии", now())).fetchone()[0]
    if payload.get("note") or payload.get("text"):
        c.execute("INSERT INTO messages(deal_id,chat_key,source_id,dir,author,text,created,unread) VALUES(?,?,?,?,?,?,?,1)",
                  (deal["id"], "call-%d" % cid, src["id"] if src else None, "in", "Телефония",
                   payload.get("text") or payload.get("note"), now()))
    c.execute("UPDATE deals SET last_in=?, updated=? WHERE id=?", (now(), now(), deal["id"]))
    c.commit(); c.close()
    log(user_id, "inbound_call", "deal", deal["id"], {"phone": pn, "status": status,
                                                      "deal_new": deal_new, "client_new": client_new})
    return {"call_id": cid, "deal_id": deal["id"], "deal_new": deal_new,
            "client_id": client["id"], "client_new": client_new, "status": status,
            "phone": pretty_phone(pn) if pn != "unknown" else phone}


def decorate_deal(c, d):
    out = dict(d)
    out["criteria"] = json.loads(d["criteria"] or "[]") if d.get("criteria") else out.get("criteria")
    return out


DEAL_SQL = """
SELECT d.id, d.title, d.client_id, d.stage_id, d.source_id, d.owner_id, d.price,
       d.created, d.updated, d.last_in,
       s.name stage_name, s.sort stage_sort, s.color stage_color, s.outcome stage_outcome,
       c.name client_name, c.phone client_phone, c.phone_norm, c.budget, c.people, c.km,
       c.criteria, c.directions, c.comment, c.source_id client_source_id, c.external_ref,
       src.name source_name, src.code source_code, src.kind source_kind,
       u.name owner_name, u.login owner_login,
       (SELECT COUNT(*) FROM messages m WHERE m.deal_id=d.id AND m.unread=1) unread,
       (SELECT COUNT(*) FROM messages m WHERE m.deal_id=d.id) msg_count,
       (SELECT text FROM messages m WHERE m.deal_id=d.id ORDER BY m.id DESC LIMIT 1) last_text,
       (SELECT dir FROM messages m WHERE m.deal_id=d.id ORDER BY m.id DESC LIMIT 1) last_dir,
       (SELECT COUNT(*) FROM calls k WHERE k.deal_id=d.id) call_count
FROM deals d
JOIN stages s ON s.id=d.stage_id
LEFT JOIN clients c ON c.id=d.client_id
LEFT JOIN sources src ON src.id=COALESCE(d.source_id, c.source_id)
LEFT JOIN users u ON u.id=d.owner_id
"""


def visible_deals(user, where="", args=(), order="d.last_in DESC"):
    parts, a = [], list(args)
    if "view_all_deals" not in perms_of(user):
        parts.append("d.owner_id=?"); a.append(user["id"])
    if where:
        parts.append(where)
    sql = DEAL_SQL + (" WHERE " + " AND ".join(parts) if parts else "") + " ORDER BY " + order
    rows = allrows(sql, a)
    for r in rows:
        r["criteria"] = json.loads(r["criteria"] or "[]")
        r["directions"] = json.loads(r["directions"] or "[]")
        r["phone_pretty"] = pretty_phone(r["phone_norm"]) or r["client_phone"]
    return rows


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


# ---------------------------------------------------------------------- HTTP
ROUTES = []


def route(method, pattern):
    rx = re.compile("^" + pattern + "$")
    def deco(fn):
        ROUTES.append((method, rx, fn.__name__)); return fn
    return deco


CT = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
      ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
      ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
      ".md": "text/markdown; charset=utf-8"}


class H(BaseHTTPRequestHandler):
    server_version = "UsadbaCRM/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # ---------- plumbing
    def do_GET(self): self.dispatch("GET")
    def do_POST(self): self.dispatch("POST")
    def do_PATCH(self): self.dispatch("PATCH")
    def do_PUT(self): self.dispatch("PUT")
    def do_DELETE(self): self.dispatch("DELETE")
    def do_HEAD(self): self.dispatch("HEAD")

    def dispatch(self, method):
        try:
            if os.environ.get("CRM_ACCESS_LOG", "1") != "0":
                print("[req] %s %s" % (method, self.path), flush=True)
        except Exception:
            pass
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        self.qdict = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.raw = parsed.query
        if method in ("GET", "HEAD") and not path.startswith("/api/") and not path.startswith("/webhook/") and path != "/healthz":
            return self.serve_static(path)
        body = None
        length = int(self.headers.get("Content-Length") or 0)
        if method in ("GET", "HEAD") and length:
            self.rfile.read(length)
        if length:
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except Exception:
                raise ApiError("тело запроса не JSON", 400)
        self.body = body or {}
        for m, rx, name in ROUTES:
            if m != method:
                continue
            mt = rx.match(path)
            if mt:
                self.params = {k: unquote_or(v) for k, v in mt.groupdict().items()}
                try:
                    getattr(self, name)()
                except ApiError as e:
                    self.json({"error": str(e.args[0])}, e.status)
                except Exception as e:  # noqa
                    traceback.print_exc()
                    self.json({"error": "внутренняя ошибка: %s: %s" % (e.__class__.__name__, e),
                               "trace": traceback.format_exc().splitlines()[-3:]}, 500)
                return
        self.json({"error": "не найдено: %s %s" % (method, path), "known": "см. Админка → API"}, 404)

    def serve_static(self, path):
        if path in ("/", "/index.html"):
            path = "/index.html"
        safe = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(WEB_DIR, safe)
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            full = os.path.join(WEB_DIR, "index.html")
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CT.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if status in (200, 201) and self.command == "POST":
            pass
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def cookie(self, name):
        raw = self.headers.get("Cookie") or ""
        ck = SimpleCookie(); ck.load(raw)
        m = ck.get(name)
        return m.value if m else None

    def user(self, required=True):
        tok = self.cookie("sid") or self.headers.get("X-Session-Token")
        if not tok:
            if required:
                raise ApiError("нужен вход (401)", 401)
            return None
        u = onerow("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (tok,))
        if not u or not u["active"]:
            if required:
                raise ApiError("сессия истекла — войдите заново", 401)
            return None
        u["_perms"] = sorted(perms_of(u))
        return u

    def need(self, *perm):
        u = self.user()
        p = perms_of(u)
        if not all(x in p for x in perm):
            raise ApiError("недостаточно прав: %s" % ", ".join(perm), 403)
        return u

    def webhook_token_ok(self):
        tok = self.headers.get("X-Webhook-Token") or self.qdict.get("token") or \
              (self.body or {}).get("token") or ""
        if tok != setting("webhook_token", ""):
            raise ApiError("неверный X-Webhook-Token", 401)

    # ---------- auth
    @route("POST", "/api/login")
    def h_login(self):
        login = (self.body.get("login") or "").strip()
        pw = self.body.get("password") or ""
        u = onerow("SELECT * FROM users WHERE lower(login)=lower(?)", (login,))
        if not u or not u["active"] or not check_pw(pw, u["salt"], u["hash"]):
            raise ApiError("неверный логин или пароль", 401)
        tok = secrets.token_urlsafe(24)
        run("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)", (tok, u["id"], now()))
        log(u["id"], "login", "user", u["id"])
        self.json({"ok": True, "token": tok, "user": public_user(u)})

    @route("POST", "/api/logout")
    def h_logout(self):
        tok = self.cookie("sid")
        if tok:
            run("DELETE FROM sessions WHERE token=?", (tok,))
        self.json({"ok": True})

    @route("GET", "/api/session")
    def h_session(self):
        u = self.user(required=False)
        if not u:
            return self.json({"user": None})
        m = meta()
        if "manage_settings" not in perms_of(u):
            m["webhook_token"] = ""
        self.json({"user": public_user(u), "meta": m})

    # ---------- read
    @route("GET", "/api/deals")
    def h_deals(self):
        u = self.user()
        where, args = [], []
        if self.qdict.get("stage"):
            where.append("d.stage_id=?"); args.append(self.qdict["stage"])
        if self.qdict.get("source"):
            where.append("COALESCE(d.source_id,c.source_id) IN (SELECT id FROM sources WHERE code=?)")
            args.append(self.qdict["source"])
        if self.qdict.get("owner"):
            where.append("d.owner_id=?"); args.append(self.qdict["owner"])
        if self.qdict.get("q"):
            like = "%" + self.qdict["q"] + "%"
            where.append("(c.name LIKE ? OR c.phone_norm LIKE ? OR d.title LIKE ? OR c.comment LIKE ?)")
            args += [like, like.replace("%", ""), like, like]
        rows = visible_deals(u, " AND ".join(where) if where else "", args)
        self.json({"deals": rows, "stages": allrows("SELECT * FROM stages ORDER BY sort"),
                   "sources": allrows("SELECT * FROM sources ORDER BY position"),
                   "users": [public_user(x) for x in allrows("SELECT * FROM users ORDER BY name")],
                   "server_time": now()})

    @route("GET", "/api/chats")
    def h_chats(self):
        u = self.user()
        deals = visible_deals(u, order="(SELECT COUNT(*) FROM messages m WHERE m.deal_id=d.id AND m.unread=1) DESC, d.last_in DESC")
        self.json({"threads": [{
            "deal_id": d["id"], "client_id": d["client_id"], "client_name": d["client_name"],
            "phone": d["phone_pretty"], "source_name": d["source_name"], "source_code": d["source_code"],
            "stage_name": d["stage_name"], "stage_color": d["stage_color"], "unread": d["unread"],
            "last_text": d["last_text"], "last_dir": d["last_dir"], "last_in": d["last_in"],
            "owner_name": d["owner_name"], "criteria": d["criteria"],
        } for d in deals]})

    @route("GET", "/api/deals/(?P<i>[0-9]+)")
    def h_deal(self):
        u = self.user()
        d = onerow(DEAL_SQL + " WHERE d.id=?", (int(self.params["i"]),))
        if not d:
            raise ApiError("сделка не найдена", 404)
        if "view_all_deals" not in perms_of(u) and d["owner_id"] != u["id"]:
            raise ApiError("сделка принадлежит другому менеджеру", 403)
        d["criteria"] = json.loads(d["criteria"] or "[]")
        d["directions"] = json.loads(d["directions"] or "[]")
        d["phone_pretty"] = pretty_phone(d["phone_norm"]) or d["client_phone"]
        msgs = allrows("SELECT * FROM messages WHERE deal_id=? ORDER BY id", (d["id"],))
        calls = allrows("SELECT k.*, u.name manager_name FROM calls k LEFT JOIN users u ON u.id=k.manager_id "
                        "WHERE k.deal_id=? ORDER BY k.id DESC", (d["id"],))
        had_unread = d["unread"]
        run("UPDATE messages SET unread=0 WHERE deal_id=? AND unread=1", (d["id"],))
        d["unread_read_now"] = had_unread
        d["unread"] = 0
        self.json({"deal": d, "messages": msgs, "calls": calls,
                   "stages": allrows("SELECT * FROM stages ORDER BY sort"),
                   "sources": allrows("SELECT * FROM sources WHERE enabled=1 ORDER BY position"),
                   "users": [public_user(x) for x in allrows("SELECT * FROM users WHERE active=1 ORDER BY name")]})

    @route("GET", "/api/clients")
    def h_clients(self):
        u = self.user()
        parts, args = [], []
        if "view_all_deals" not in perms_of(u):
            parts.append("(c.owner_id=? OR c.id IN (SELECT client_id FROM deals WHERE owner_id=?))")
            args += [u["id"], u["id"]]
        if self.qdict.get("q"):
            like = "%" + self.qdict["q"] + "%"
            digits = re.sub(r"\D", "", self.qdict["q"])
            parts.append("(c.name LIKE ? OR c.phone_norm LIKE ? OR c.comment LIKE ?)")
            args += [like, ("%" + digits + "%") if digits else "невозможно", like]
        if self.qdict.get("source"):
            parts.append("c.source_id IN (SELECT id FROM sources WHERE code=?)"); args.append(self.qdict["source"])
        if self.qdict.get("criteria"):
            parts.append("c.criteria LIKE ?"); args.append('%"%s"%' % self.qdict["criteria"])
        sql = ("SELECT c.*, src.name source_name, src.code source_code, u.name owner_name, "
               "(SELECT COUNT(*) FROM deals d WHERE d.client_id=c.id) deal_count, "
               "(SELECT id FROM deals d WHERE d.client_id=c.id ORDER BY d.id DESC LIMIT 1) last_deal_id, "
               "(SELECT s.name FROM deals d JOIN stages s ON s.id=d.stage_id WHERE d.client_id=c.id "
               " ORDER BY d.id DESC LIMIT 1) last_stage "
               "FROM clients c LEFT JOIN sources src ON src.id=c.source_id LEFT JOIN users u ON u.id=c.owner_id")
        if parts:
            sql += " WHERE " + " AND ".join(parts)
        sql += " ORDER BY c.updated DESC LIMIT 400"
        rows = allrows(sql, args)
        for r in rows:
            r["criteria"] = json.loads(r["criteria"] or "[]")
            r["directions"] = json.loads(r["directions"] or "[]")
            r["phone_pretty"] = pretty_phone(r["phone_norm"]) or r["client_phone"]
        self.json({"clients": rows, "criteria_options": CRITERIA, "direction_options": DIRECTIONS,
                   "sources": allrows("SELECT * FROM sources WHERE enabled=1 ORDER BY position")})

    @route("GET", "/api/calls")
    def h_calls(self):
        self.user()
        rows = allrows("SELECT k.*, c.name client_name, u.name manager_name, d.title deal_title, "
                       "d.id deal_id FROM calls k "
                       "LEFT JOIN clients c ON c.id=k.client_id LEFT JOIN users u ON u.id=k.manager_id "
                       "LEFT JOIN deals d ON d.id=k.deal_id "
                       "ORDER BY k.id DESC LIMIT 300")
        for r in rows:
            r["phone_pretty"] = r["phone"]
        self.json({"calls": rows, "telephony": json.loads(setting("telephony", "{}")),
                   "callback_url": "/webhook/call"})

    @route("GET", "/api/stats")
    def h_stats(self):
        u = self.user()
        deals = visible_deals(u)
        stages = allrows("SELECT * FROM stages ORDER BY sort")
        by_stage = {s["id"]: 0 for s in stages}
        by_stage_value = {s["id"]: 0 for s in stages}
        by_source, crit, dirs = {}, {}, {}
        won = lost = 0
        for d in deals:
            by_stage[d["stage_id"]] = by_stage.get(d["stage_id"], 0) + 1
            by_stage_value[d["stage_id"]] = by_stage_value.get(d["stage_id"], 0) + (d["price"] or 0)
            key = d["source_code"] or "—"
            by_source[key] = by_source.get(key, {})
            by_source[key]["name"] = d["source_name"] or key
            by_source[key]["count"] = by_source[key].get("count", 0) + 1
            by_source[key]["value"] = by_source[key].get("value", 0) + (d["price"] or 0)
            for x in d["criteria"]:
                crit[x] = crit.get(x, 0) + 1
            for x in d["directions"]:
                dirs[x] = dirs.get(x, 0) + 1
            if d["stage_outcome"] == "win":
                won += 1
            elif d["stage_outcome"] == "lose":
                lost += 1
        active = [d for d in deals if not d["stage_outcome"]]
        self.json({
            "total": len(deals), "active": len(active), "won": won, "lost": lost,
            "conversion": round(100.0 * won / (won + lost), 1) if (won + lost) else 0,
            "pipeline_value": sum(d["price"] or 0 for d in active),
            "won_value": sum(d["price"] or 0 for d in deals if d["stage_outcome"] == "win"),
            "unread": sum(d["unread"] for d in deals),
            "stages": [{**s, "count": by_stage.get(s["id"], 0), "value": by_stage_value.get(s["id"], 0)}
                       for s in stages],
            "sources": sorted(by_source.values(), key=lambda x: -x["count"]),
            "criteria": crit, "directions": dirs,
            "week_new": len([d for d in deals if d["created"] > now() - 7 * 86400]),
        })

    @route("GET", "/api/log")
    def h_log(self):
        self.need("view_all_deals")
        rows = allrows("SELECT a.*, u.name user_name FROM activity a LEFT JOIN users u ON u.id=a.user_id "
                       "ORDER BY a.id DESC LIMIT 200")
        self.json({"log": rows})

    # ---------- write
    @route("POST", "/api/deals")
    def h_create_deal(self):
        u = self.user()
        b = self.body
        c = conn()
        phone = b.get("phone") or ""
        if b.get("client_id"):
            client = dict(c.execute("SELECT * FROM clients WHERE id=?", (b["client_id"],)).fetchone())
            client_new = False
        else:
            client, client_new = find_or_create_client(c, phone, b.get("client_name"),
                                                       src_id(b.get("source")), b.get("external_ref") or "")
        src = enabled_source(b.get("source")) if b.get("source") else None
        first = onerow("SELECT * FROM stages ORDER BY sort LIMIT 1")
        ts = now()
        did = c.execute("INSERT INTO deals(title,client_id,stage_id,source_id,owner_id,price,created,updated,last_in)"
                        " VALUES(?,?,?,?,?,?,?,?,?) RETURNING id",
                        (b.get("title") or ("Бронирование · " + (client["name"] or "клиент")),
                         client["id"], int(b.get("stage_id") or first["id"]),
                         src["id"] if src else client["source_id"], b.get("owner_id") or u["id"],
                         int(b.get("price") or client["budget"] or 0), ts, ts, ts)).fetchone()[0]
        c.commit(); c.close()
        log(u["id"], "deal_create", "deal", did, {"client_new": client_new})
        self.json({"deal_id": did, "client_id": client["id"], "client_new": client_new}, 201)

    @route("PATCH", "/api/deals/(?P<i>[0-9]+)")
    def h_patch_deal(self):
        u = self.user()
        self.need("edit_clients")
        did = int(self.params["i"])
        d = onerow("SELECT * FROM deals WHERE id=?", (did,))
        if not d:
            raise ApiError("сделка не найдена", 404)
        if "view_all_deals" not in perms_of(u) and d["owner_id"] != u["id"]:
            raise ApiError("не ваша сделка", 403)
        b = self.body
        fields, args = [], []
        if "stage_id" in b:
            st = onerow("SELECT * FROM stages WHERE id=?", (int(b["stage_id"]),))
            if not st:
                raise ApiError("этап не найден", 400)
            fields.append("stage_id=?"); args.append(st["id"])
        if "owner_id" in b:
            fields.append("owner_id=?"); args.append(int(b["owner_id"]) if b["owner_id"] else None)
        if "price" in b:
            fields.append("price=?"); args.append(int(b["price"] or 0))
        if "title" in b:
            fields.append("title=?"); args.append(b["title"])
        if not fields:
            raise ApiError("нечего обновлять", 400)
        fields.append("updated=?"); args.append(now()); args.append(did)
        run("UPDATE deals SET " + ",".join(fields) + " WHERE id=?", args)
        log(u["id"], "deal_update", "deal", did, b)
        self.json({"ok": True, "deal": onerow("SELECT * FROM deals WHERE id=?", (did,))})

    @route("DELETE", "/api/deals/(?P<i>[0-9]+)")
    def h_delete_deal(self):
        u = self.need("delete_records")
        did = int(self.params["i"])
        run("DELETE FROM messages WHERE deal_id=?", (did,))
        run("UPDATE calls SET deal_id=NULL WHERE deal_id=?", (did,))
        run("DELETE FROM deals WHERE id=?", (did,))
        log(u["id"], "deal_delete", "deal", did)
        self.json({"ok": True})

    @route("POST", "/api/clients")
    def h_create_client(self):
        u = self.user()
        b = self.body
        c = conn()
        client, _ = find_or_create_client(c, b.get("phone") or b.get("name"),
                                          b.get("name"), src_id(b.get("source")), "")
        cid = client["id"]
        c.execute("UPDATE clients SET budget=?,people=?,km=?,criteria=?,directions=?,comment=?,owner_id=?,updated=?"
                  " WHERE id=?", (int_or_none(b.get("budget")), int_or_none(b.get("people")),
                                  int_or_none(b.get("km")),
                                  json.dumps(b.get("criteria") or [], ensure_ascii=False),
                                  json.dumps(b.get("directions") or [], ensure_ascii=False),
                                  b.get("comment") or "", u["id"], now(), cid))
        c.commit(); c.close()
        log(u["id"], "client_create", "client", cid, {"phone": client["phone_norm"]})
        self.json({"client_id": cid}, 201)

    @route("PATCH", "/api/clients/(?P<i>[0-9]+)")
    def h_patch_client(self):
        u = self.need("edit_clients")
        cid = int(self.params["i"])
        if not onerow("SELECT id FROM clients WHERE id=?", (cid,)):
            raise ApiError("клиент не найден", 404)
        b = self.body
        fields, args = [], []
        mapping = {"name": "name", "phone": "phone", "budget": "budget", "people": "people",
                   "km": "km", "comment": "comment", "external_ref": "external_ref"}
        for k, col in mapping.items():
            if k in b:
                if k == "phone":
                    pn = norm_phone(b[k])
                    fields.append("phone_norm=?"); args.append(pn)
                if k in ("budget", "people", "km"):
                    fields.append("%s=?" % col); args.append(int_or_none(b[k]))
                else:
                    fields.append("%s=?" % col); args.append(b[k])
        if "source" in b:
            src = enabled_source(b["source"]) if b["source"] else None
            fields.append("source_id=?"); args.append(src["id"] if src else None)
        if "criteria" in b:
            fields.append("criteria=?"); args.append(json.dumps(b["criteria"] or [], ensure_ascii=False))
        if "directions" in b:
            fields.append("directions=?"); args.append(json.dumps(b["directions"] or [], ensure_ascii=False))
        if "owner_id" in b:
            fields.append("owner_id=?"); args.append(int(b["owner_id"]) if b["owner_id"] else None)
        if not fields:
            raise ApiError("нечего обновлять", 400)
        fields.append("updated=?"); args.append(now()); args.append(cid)
        run("UPDATE clients SET " + ",".join(fields) + " WHERE id=?", args)
        log(u["id"], "client_update", "client", cid, b)
        self.json({"ok": True})

    @route("DELETE", "/api/clients/(?P<i>[0-9]+)")
    def h_delete_client(self):
        u = self.need("delete_records")
        cid = int(self.params["i"])
        n = scalar("SELECT COUNT(*) FROM deals WHERE client_id=?", (cid,)) or 0
        if n:
            raise ApiError("у клиента %d сделок — сначала удалите сделки" % n, 409)
        run("DELETE FROM clients WHERE id=?", (cid,))
        log(u["id"], "client_delete", "client", cid)
        self.json({"ok": True})

    @route("POST", "/api/deals/(?P<i>[0-9]+)/messages")
    def h_send_message(self):
        u = self.need("send_messages")
        did = int(self.params["i"])
        d = onerow("SELECT * FROM deals WHERE id=?", (did,))
        if not d:
            raise ApiError("сделка не найдена", 404)
        text = (self.body.get("text") or "").strip()
        if not text:
            raise ApiError("пустое сообщение", 400)
        chat = onerow("SELECT chat_key,source_id FROM messages WHERE deal_id=? AND chat_key IS NOT NULL "
                      "ORDER BY id DESC LIMIT 1", (did,))
        mid = run("INSERT INTO messages(deal_id,chat_key,source_id,dir,author,text,created,unread) "
                  "VALUES(?,?,?,?,?,?,?,0)",
                  (did, chat["chat_key"] if chat else None, d["source_id"], "out", u["name"], text, now()))
        run("UPDATE deals SET updated=?, owner_id=COALESCE(owner_id,?) WHERE id=?", (now(), u["id"], did))
        log(u["id"], "message_send", "deal", did, {"len": len(text)})
        self.json({"ok": True, "message_id": mid,
                   "sent_to_platform": bool(chat and chat["chat_key"] and not str(chat["chat_key"]).startswith("seed-")
                                            and not str(chat["chat_key"]).startswith("auto-"))}, 201)

    @route("POST", "/api/calls")
    def h_call(self):
        u = self.need("log_calls")
        b = self.body
        phone = norm_phone(b.get("phone")) or ""
        if b.get("client_id") and not b.get("phone"):
            phone = scalar("SELECT phone_norm FROM clients WHERE id=?", (b["client_id"],)) or ""
        if b.get("deal_id") and not b.get("client_id"):
            b["client_id"] = scalar("SELECT client_id FROM deals WHERE id=?", (b["deal_id"],))
        if b.get("action") == "click_to_call":
            t = json.loads(setting("telephony", "{}"))
            self.json({"ok": True, "dial": pretty_phone(phone),
                       "would_call": t.get("click_to_call_url") or "(не настроено: Админка → Телефония)",
                       "provider": t.get("provider"), "from_number": t.get("number")})
            return
        cid = run("INSERT INTO calls(deal_id,client_id,phone,dir,status,dur,manager_id,recording,note,created) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (b.get("deal_id"), b.get("client_id"), pretty_phone(phone) if phone else b.get("phone"),
                   b.get("dir") or "out", b.get("status") or "answered", int(b.get("dur") or 0), u["id"],
                   b.get("recording") or "", b.get("note") or "", now()))
        if b.get("deal_id"):
            run("UPDATE deals SET updated=? WHERE id=?", (now(), b["deal_id"]))
        log(u["id"], "call_log", "call", cid, b)
        self.json({"ok": True, "call_id": cid}, 201)

    # ---------- admin: sources
    @route("GET", "/api/admin/sources")
    def h_sources(self):
        self.need("manage_sources")
        rows = allrows("SELECT s.*, u.name manager_name FROM sources s LEFT JOIN users u ON u.id=s.manager_id "
                       "ORDER BY s.position, s.name")
        for r in rows:
            r["deals"] = scalar("SELECT COUNT(*) FROM deals WHERE source_id=?", (r["id"],))
            r["clients"] = scalar("SELECT COUNT(*) FROM clients WHERE source_id=?", (r["id"],))
        self.json({"sources": rows, "users": [public_user(x) for x in allrows("SELECT * FROM users WHERE active=1 ORDER BY name")]})

    @route("POST", "/api/admin/sources")
    def h_source_add(self):
        u = self.need("manage_sources")
        b = self.body
        code = (b.get("code") or slugify(b.get("name") or ""))
        if not code or not b.get("name"):
            raise ApiError("нужны name и code", 400)
        if onerow("SELECT id FROM sources WHERE code=?", (code,)):
            raise ApiError("источник с кодом '%s' уже есть" % code, 409)
        pos = (scalar("SELECT MAX(position) FROM sources") or 0) + 1
        sid = run("INSERT INTO sources(code,name,kind,api_state,enabled,position,manager_id,note)"
                  " VALUES(?,?,?,?,?,?,?,?)",
                  (code, b["name"], b.get("kind") or "chat", b.get("api_state") or "own",
                   1 if b.get("enabled", True) else 0, pos, b.get("manager_id") or None, b.get("note") or ""))
        log(u["id"], "source_add", "source", sid, b)
        self.json({"ok": True, "source_id": sid}, 201)

    @route("PATCH", "/api/admin/sources/(?P<i>[0-9]+)")
    def h_source_patch(self):
        u = self.need("manage_sources")
        sid = int(self.params["i"]); b = self.body
        fields, args = [], []
        for k, col in (("name", "name"), ("note", "note"), ("api_state", "api_state"), ("kind", "kind")):
            if k in b:
                fields.append("%s=?" % col); args.append(b[k])
        if "enabled" in b:
            fields.append("enabled=?"); args.append(1 if b["enabled"] else 0)
        if "manager_id" in b:
            fields.append("manager_id=?"); args.append(int(b["manager_id"]) if b["manager_id"] else None)
        if not fields:
            raise ApiError("нечего обновлять", 400)
        args.append(sid)
        run("UPDATE sources SET " + ",".join(fields) + " WHERE id=?", args)
        log(u["id"], "source_update", "source", sid, b)
        self.json({"ok": True})

    @route("DELETE", "/api/admin/sources/(?P<i>[0-9]+)")
    def h_source_delete(self):
        u = self.need("manage_sources")
        sid = int(self.params["i"])
        n = scalar("SELECT COUNT(*) FROM deals WHERE source_id=? ", (sid,)) or 0
        m = scalar("SELECT COUNT(*) FROM clients WHERE source_id=?", (sid,)) or 0
        if n or m:
            raise ApiError("есть %d сделок и %d клиентов с этим источником — отключите вместо удаления" % (n, m), 409)
        run("DELETE FROM sources WHERE id=?", (sid,))
        log(u["id"], "source_delete", "source", sid)
        self.json({"ok": True})

    # ---------- admin: users
    @route("GET", "/api/admin/users")
    def h_users(self):
        self.need("manage_users")
        rows = allrows("SELECT * FROM users ORDER BY name")
        out = []
        for r in rows:
            p = public_user(r)
            p["deal_count"] = scalar("SELECT COUNT(*) FROM deals WHERE owner_id=?", (r["id"],))
            out.append(p)
        self.json({"users": out, "perm_defs": PERM_DEFS, "roles": ROLES,
                   "role_defaults": ROLE_DEFAULTS, "me": public_user(self.user())})

    @route("POST", "/api/admin/users")
    def h_user_add(self):
        u = self.need("manage_users")
        b = self.body
        login = (b.get("login") or "").strip().lower()
        if not login or not b.get("name") or not b.get("password"):
            raise ApiError("нужны login, name, password", 400)
        if len(b["password"]) < 5:
            raise ApiError("пароль короткий (мин. 5)", 400)
        if onerow("SELECT id FROM users WHERE lower(login)=lower(?)", (login,)):
            raise ApiError("логин занят", 409)
        role = b.get("role") if b.get("role") in ROLES else "manager"
        perms = b.get("perms") if isinstance(b.get("perms"), list) else ROLE_DEFAULTS[role]
        salt, h = hashes(b["password"])
        uid = run("INSERT INTO users(login,name,phone,role,perms,active,salt,hash,created) VALUES(?,?,?,?,?,?,?,?,?)",
                  (login, b["name"], b.get("phone") or "", role, json.dumps(sorted(set(perms))),
                   1, salt, h, now()))
        log(u["id"], "user_add", "user", uid, {"login": login, "role": role})
        self.json({"ok": True, "user_id": uid}, 201)

    @route("PATCH", "/api/admin/users/(?P<i>[0-9]+)")
    def h_user_patch(self):
        me = self.need("manage_users")
        uid = int(self.params["i"]); b = self.body
        target = onerow("SELECT * FROM users WHERE id=?", (uid,))
        if not target:
            raise ApiError("пользователь не найден", 404)
        fields, args = [], []
        for k, col in (("name", "name"), ("phone", "phone")):
            if k in b:
                fields.append("%s=?" % col); args.append(b[k])
        if "role" in b:
            if b["role"] not in ROLES:
                raise ApiError("неизвестная роль", 400)
            fields.append("role=?"); args.append(b["role"])
            if "perms" not in b:
                fields.append("perms=?"); args.append(json.dumps(sorted(set(ROLE_DEFAULTS[b["role"]]))))
        if "perms" in b and isinstance(b["perms"], list):
            allowed = [x for x in b["perms"] if x in PERM_KEYS]
            fields.append("perms=?"); args.append(json.dumps(sorted(set(allowed))))
        if "password" in b and b["password"]:
            salt, h = hashes(b["password"])
            fields += ["salt=?", "hash=?"]; args += [salt, h]
            run("DELETE FROM sessions WHERE user_id=?", (uid,))
        if "active" in b:
            if uid == me["id"] and not b["active"]:
                raise ApiError("нельзя отключить самого себя", 400)
            fields.append("active=?"); args.append(1 if b["active"] else 0)
            if not b["active"]:
                run("DELETE FROM sessions WHERE user_id=?", (uid,))
        if not fields:
            raise ApiError("нечего обновлять", 400)
        args.append(uid)
        run("UPDATE users SET " + ",".join(fields) + " WHERE id=?", args)
        log(me["id"], "user_update", "user", uid, {k: v for k, v in b.items() if k != "password"})
        self.json({"ok": True, "user": public_user(onerow("SELECT * FROM users WHERE id=?", (uid,)))})

    @route("DELETE", "/api/admin/users/(?P<i>[0-9]+)")
    def h_user_delete(self):
        me = self.need("manage_users")
        uid = int(self.params["i"])
        if uid == me["id"]:
            raise ApiError("нельзя удалить себя", 400)
        t = onerow("SELECT * FROM users WHERE id=?", (uid,))
        if not t:
            raise ApiError("пользователь не найден", 404)
        if t["role"] == "owner":
            raise ApiError("нельзя удалить владельца", 400)
        n = scalar("SELECT COUNT(*) FROM deals WHERE owner_id=? AND stage_id IN "
                   "(SELECT id FROM stages WHERE outcome IS NULL)", (uid,)) or 0
        if n:
            raise ApiError("на пользователе %d активных сделок — сначала передайте их (карточка сделки → Ответственный)" % n, 409)
        run("UPDATE deals SET owner_id=NULL WHERE owner_id=?", (uid,))
        run("UPDATE clients SET owner_id=NULL WHERE owner_id=?", (uid,))
        run("UPDATE sources SET manager_id=NULL WHERE manager_id=?", (uid,))
        run("DELETE FROM sessions WHERE user_id=?", (uid,))
        run("DELETE FROM users WHERE id=?", (uid,))
        log(me["id"], "user_delete", "user", uid, {"login": t["login"]})
        self.json({"ok": True})

    # ---------- admin: stages, settings, telephony, demo
    @route("GET", "/api/admin/stages")
    def h_stages_admin(self):
        self.need("manage_stages")
        rows = allrows("SELECT s.*, (SELECT COUNT(*) FROM deals d WHERE d.stage_id=s.id) cnt FROM stages s ORDER BY s.sort")
        self.json({"stages": rows})

    @route("POST", "/api/admin/stages")
    def h_stage_add(self):
        u = self.need("manage_stages")
        b = self.body
        pos = (scalar("SELECT MAX(sort) FROM stages WHERE outcome IS NULL") or 0) + 1
        sid = run("INSERT INTO stages(name,sort,prob,color,outcome) VALUES(?,?,?,?,?)",
                  (b.get("name") or "Новый этап", b.get("sort") or pos, int(b.get("prob") or 50),
                   b.get("color") or "#8a94a6", b.get("outcome") or None))
        log(u["id"], "stage_add", "stage", sid, b)
        self.json({"ok": True, "stage_id": sid}, 201)

    @route("PATCH", "/api/admin/stages/(?P<i>[0-9]+)")
    def h_stage_patch(self):
        u = self.need("manage_stages")
        sid = int(self.params["i"]); b = self.body
        run("UPDATE stages SET name=?, sort=?, prob=?, color=?, outcome=? WHERE id=?",
            (b.get("name"), int(b.get("sort") or 0), int(b.get("prob") or 0), b.get("color"),
             b.get("outcome") or None, sid))
        log(u["id"], "stage_update", "stage", sid, b)
        self.json({"ok": True})

    @route("DELETE", "/api/admin/stages/(?P<i>[0-9]+)")
    def h_stage_delete(self):
        u = self.need("manage_stages")
        sid = int(self.params["i"])
        n = scalar("SELECT COUNT(*) FROM deals WHERE stage_id=?", (sid,)) or 0
        if n:
            raise ApiError("на этапе %d сделок — перенесите их сначала" % n, 409)
        run("DELETE FROM stages WHERE id=?", (sid,))
        log(u["id"], "stage_delete", "stage", sid)
        self.json({"ok": True})

    @route("GET", "/api/admin/settings")
    def h_settings_get(self):
        u = self.need("manage_settings")
        self.json({"settings": settings_map(), "me": public_user(u),
                   "webhook_base": "%s://%s" % (self.headers.get("X-Forwarded-Proto") or "http",
                                               self.headers.get("Host") or "localhost:%d" % PORT)})

    @route("PATCH", "/api/admin/settings")
    def h_settings_patch(self):
        u = self.need("manage_settings")
        for k, v in (self.body or {}).items():
            if k == "webhook_token" and v == "regen":
                v = secrets.token_hex(12)
            if k in ("assign_rule", "one_open_deal_per_client", "company_name", "webhook_token", "telephony"):
                if k == "one_open_deal_per_client":
                    v = "1" if v in (1, True, "1", "true") else "0"
                set_setting(k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
        log(u["id"], "settings_update", "settings", None, list((self.body or {}).keys()))
        self.json({"ok": True, "settings": settings_map()})

    @route("POST", "/api/demo/inbound")
    def h_demo_inbound(self):
        u = self.need("send_messages")
        code = self.body.get("source") or "avito"
        samples = {
            "avito": ("Здравствуйте! Ищем дом с бассейном на свадьбу, 60 человек, юг, до 40 км. "
                      "Бюджет 300000. Можно созвониться: +7926%s" % str(now())[-7:]),
            "cian": ("Ищем объект с баней, восток, удалённость до 70 км, на 12 человек. "
                     "Телефон +7916%s" % str(now())[-7:]),
            "sutochno": ("Бронь от гостей: корпоратив 25 человек, нужен близко к городу. "
                         "Контакт +7985%s" % str(now())[-7:]),
            "yandex_travel": ("Из Яндекс Путешествий: интерес к датчикам 20-22 июня, свадьба, "
                              "бассейн. Телефон +7926%s" % str(now())[-7:]),
            "spitti": ("Spitti: новый лид, банкет на 40 человек, юг, 35 км. +7916%s" % str(now())[-7:]),
            "yandex_realty": ("Яндекс Недвижимость: вопрос по дому, баня+бассейн, 8 человек, "
                              "восток 60 км. +7917%s" % str(now())[-7:]),
            "website": ("Заявка с сайта: свадьба 55 человек, юг, бюджет 260000. +7905%s" % str(now())[-7:]),
            "telephony": ("Звонок: банкет 20 человек, близко к городу, север 12 км. +7917%s" % str(now())[-7:]),
        }
        text = self.body.get("text") or samples.get(code, samples["avito"])
        if code == "telephony":
            res = inbound_call({"phone": phones_in_text(text)[0], "status": "answered",
                                "duration_sec": 145, "note": "Демо-звонок", "text": text}, u["id"])
        else:
            res = inbound_message(code, "%s-demo-%d" % (code, now()), text,
                                  author="Гость (демо)", user_id=u["id"])
        self.json(res, 201)

    # ---------- webhooks (интеграции площадок и телефонии)
    @route("POST", "/webhook/chat")
    def h_wh_chat(self):
        self.webhook_token_ok()
        b = self.body
        frm = b.get("from") if isinstance(b.get("from"), dict) else {}
        res = inbound_message(b.get("platform") or b.get("source") or b.get("channel"),
                              b.get("chat_id") or b.get("chat_key") or b.get("thread_id"),
                              b.get("text") or b.get("message") or "",
                              author=frm.get("name") or b.get("author") or "Гость",
                              phone=b.get("phone") or frm.get("phone"),
                              client_name=b.get("client_name") or frm.get("name"),
                              external_ref=b.get("external_ref") or "")
        self.json(res, 201)

    @route("POST", "/webhook/call")
    def h_wh_call(self):
        self.webhook_token_ok()
        self.json(inbound_call(self.body), 201)

    @route("GET", "/healthz")
    def h_health(self):
        self.json({"ok": True, "db": os.path.basename(DB_PATH), "ts": now()})


def unquote_or(v):
    from urllib.parse import unquote
    return unquote(v) if v else v


def src_id(code):
    if not code:
        return None
    s = enabled_source(code)
    return s["id"] if s else None


def int_or_none(v):
    try:
        return int(str(v).replace(" ", "").replace("₽", "")) if v not in (None, "") else None
    except Exception:
        return None


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:24]


def public_user(r):
    return {"id": r["id"], "login": r["login"], "name": r["name"], "phone": r["phone"],
            "role": r["role"], "role_label": ROLES.get(r["role"], r["role"]),
            "active": bool(r["active"]), "perms": r.get("_perms") or sorted(perms_of(r))}


def settings_map():
    return {r["key"]: r["value"] for r in allrows("SELECT * FROM settings")}


def meta():
    st = json.loads(setting("telephony", "{}"))
    return {
        "sources": [dict(x) for x in allrows("SELECT * FROM sources ORDER BY position")],
        "stages": [dict(x) for x in allrows("SELECT * FROM stages ORDER BY sort")],
        "criteria_options": CRITERIA, "direction_options": DIRECTIONS,
        "perm_defs": PERM_DEFS, "roles": ROLES, "role_defaults": ROLE_DEFAULTS,
        "assign_rule": setting("assign_rule", "round_robin"),
        "one_open_deal_per_client": setting("one_open_deal_per_client", "1"),
        "company_name": setting("company_name", "Усадьба"),
        "telephony": st,
        "webhook_token": setting("webhook_token", ""),
    }


def ensure_closed_at():
    """stage закрытия: добавляем колонку closed_at при первой необходимости."""
    try:
        run("ALTER TABLE deals ADD COLUMN closed_at INTEGER")
    except Exception:
        pass


if __name__ == "__main__":
    seed()
    ThreadingHTTPServer.allow_reuse_address = True
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("Усадьба·CRM готов: http://0.0.0.0:%d  (админ: admin / admin123)" % PORT, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
