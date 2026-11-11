#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Адаптеры входящих событий → единый формат CRM.

CRM принимает только два эндпоинта: /webhook/chat и /webhook/call.
Каждая площадка/АТС отдаёт свой payload, поэтому слой адаптеров — это единственное место,
где мы знаем про «чужие» названия полей. Тело каждого адаптера помечено:

  [FACT]  — поле есть в документации источника
  [CHECK] — уточнить по живому ответу/договору с площадкой (названия полей плывут)
  [NO-API] — официального способа получить сообщение нет, см. README (партнёрское
             подключение или канал через email/бота)

Тесты контракта: python3 integrations/adapters.py  (печатает, во что превращаются образцы)
"""
from __future__ import annotations
import json
import urllib.request

CRM_BASE = "http://127.0.0.1:8080"
WEBHOOK_TOKEN = ""  # из Админка → Настройки; в проде — из переменных окружения, не из кода


def push_chat(payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(CRM_BASE + "/webhook/chat", data=body,
                                 headers={"Content-Type": "application/json",
                                          "X-Webhook-Token": WEBHOOK_TOKEN})
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode() or "{}")


def push_call(payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(CRM_BASE + "/webhook/call", data=body,
                                 headers={"Content-Type": "application/json",
                                          "X-Webhook-Token": WEBHOOK_TOKEN})
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode() or "{}")


# ------------------------------------------------------------------ чаты площадок
def avito(ev: dict) -> dict:
    """Авито, официальный API для бизнеса (OAuth2).

    [FACT] сообщения читаются/отправляются через API чатов Авито; идентификатор диалога
           приходит в событии; телефон гостя Авито НЕ отдаёт (закрытый номер) —
           поэтому карточка создаётся по chat_id, а телефон добирается при первом звонке/слове.
    [CHECK] точные имена полей и scope'ы — по документации вашего кабинета (они менялись).
    """
    return {
        "platform": "avito",
        "chat_id": str(ev.get("chat_id") or ev.get("chat", {}).get("id")),
        "from": {"name": ev.get("from", {}).get("user", {}).get("name") or "Гость Авито"},
        "text": ev.get("message", {}).get("body") or ev.get("text") or "",
        "phone": None,                       # см. [FACT]
        "external_ref": "avito:" + str(ev.get("chat_id") or ev.get("listing", {}).get("id") or ""),
    }


def sutochno(ev: dict) -> dict:
    """Суточно.ру: Partner API (бронирования/события) либо события из channel-manager'а.

    [CHECK] сообщения площадки приходят либо webhook'ом партнерского API, либо через
           RMS (Spitti/Контур.Отель/Travelline) — тогда payload приходит от RMS, а не от Суточно.
    """
    booking = ev.get("booking") or {}
    return {
        "platform": "sutochno",
        "chat_id": "sutochno-" + str(ev.get("chat_id") or booking.get("id")),
        "from": {"name": (ev.get("guest") or {}).get("name") or booking.get("guest_name") or "Гость Суточно",
                 "phone": (ev.get("guest") or {}).get("phone") or booking.get("guest_phone")},
        "text": ev.get("message") or ev.get("text") or ("Новая заявка: " + str(booking.get("id") or "")),
        "external_ref": "sutochno:" + str(booking.get("id") or ev.get("chat_id") or ""),
    }


def spitti(ev: dict) -> dict:
    """Spitti (RMS + мессенджер-хаб). [CHECK] схема события уточняется в их API-доках:
    обычно event ∈ {message_received, booking_created}, есть channel/room_id и контактные данные."""
    return {
        "platform": "spitti",
        "chat_id": "spitti-" + str(ev.get("room_id") or ev.get("chat_id")),
        "from": {"name": ev.get("client", {}).get("name") or "Гость Spitti",
                 "phone": ev.get("client", {}).get("phone")},
        "text": ev.get("message") or ev.get("text") or json.dumps(ev, ensure_ascii=False)[:200],
        "external_ref": "spitti:" + str(ev.get("booking_id") or ""),
    }


def yandex_travel(ev: dict) -> dict:
    """Яндекс Путешествия: партнёрский API отелей. [CHECK] события броней есть, сообщения —
    чаще всего только в партнерском кабинете → тогда заводим ручной/почтовый канал."""
    b = ev.get("booking") or {}
    return {
        "platform": "yandex_travel",
        "chat_id": "ya-travel-" + str(b.get("id") or ev.get("chat_id")),
        "from": {"name": (b.get("guest") or {}).get("name") or "Гость Яндекс Путешествия",
                 "phone": (b.get("guest") or {}).get("phone")},
        "text": ev.get("message") or ("Бронирование через Яндекс Путешествия: " + str(b.get("id"))),
    }


def yandex_realty(ev: dict) -> dict:
    """Яндекс Недвижимость. [NO-API] публичного API чатов нет.
    Практические каналы: (1) уведомление о заявке на email/Telegram → бот разбирает и зовёт push_chat,
    (2) партнёрское agreement с Яндекс. Сюда прилетает уже нормализованная заметка."""
    return {
        "platform": "yandex_realty",
        "chat_id": "ya-realty-" + str(ev.get("offer_id") or ev.get("id")),
        "from": {"name": ev.get("name") or "Заявка Яндекс Недвижимость", "phone": ev.get("phone")},
        "text": ev.get("message") or ev.get("body") or "",
    }


def cian(ev: dict) -> dict:
    """ЦИАН. [NO-API] чатов через открытый API нет.
    (1) звонки идут на подменный номер → попадать будут в norm_call, platform='cian';
    (2) сообщения — из ЛК: либо партнёрское подключение, либо форвард на почту и разбор письма."""
    return {
        "platform": "cian",
        "chat_id": "cian-" + str(ev.get("chat_id") or ev.get("listing_id")),
        "from": {"name": ev.get("name") or "Гость ЦИАН", "phone": ev.get("phone")},
        "text": ev.get("message") or ev.get("body") or "",
    }


def website_form(ev: dict) -> dict:
    """Своя форма/бот/почта — самый простой и полностью подконтрольный канал."""
    return {
        "platform": ev.get("channel") or "website",
        "chat_id": "web-" + str(ev.get("form_id")),
        "from": {"name": ev.get("name"), "phone": ev.get("phone")},
        "text": ev.get("comment") or ev.get("message") or "Заявка с сайта",
    }


# ------------------------------------------------------------------ телефония
def norm_call(ev: dict, provider: str = "mango") -> dict:
    """Приводит событие АТС к нашему формату.

    [FACT] у Mango Office / UIS / Zadarma есть HTTP-callback о вызове (start/answer/end),
           длительность, направление, внутренний номер, ссылка на запись.
    """
    status = {"answered": "answered", "call_answered": "answered", "finished": "answered",
              "missed": "missed", "no_answer": "missed", "ringing": "ringing"}.get(
        str(ev.get("event") or ev.get("status") or ""), "answered")
    return {
        "platform": "telephony",
        "event": ev.get("event") or "call_answered",
        "phone": ev.get("caller_number") or ev.get("from") or ev.get("caller") or ev.get("phone"),
        "dir": "in" if (ev.get("direction") or ev.get("type") or "in") in ("in", "inbound", "dialin") else "out",
        "status": status,
        "duration_sec": ev.get("duration") or ev.get("billsec") or ev.get("duration_sec") or 0,
        "recording_url": ev.get("recording_url") or ev.get("record_file") or "",
        "manager_login": ev.get("internal") or ev.get("user") or ev.get("queue_agent") or "",
        "note": ev.get("note") or f"{provider}: {ev.get('event') or 'call'}",
    }


def click_to_call(phone: str, manager: str, telephony: dict) -> dict:
    """Исходящий из карточки: «позвони с нашего номера на внутренний менеджеру, потом на гостя».

    [CHECK] конкретный URL и подписи — по докам провайдера (telephony.api_token из админки).
    """
    url = telephony.get("click_to_call_url")
    return {"would_call": url, "phone": phone, "manager": manager,
            "from_number": telephony.get("number"),
            "todo": "добавить авторизацию провайдера и, при необходимости, HMAC-подпись"}


# ------------------------------------------------------------------ исходящие
def send_chat_message(platform: str, chat_key: str, text: str, tokens: dict) -> dict:
    """Отправка ответа гостю на площадку. Здесь нужен реальный вызов API источника.

    [FACT] Авито отвечает на сообщения через тот же API чатов;
    [NO-API] для ЦИАН/Яндекс Недвижимости ответа «из CRM» может не быть — тогда текст
             копируется менеджеру и в карточке помечается как отправлен вручную.
    """
    if platform == "avito":
        return {"endpoint": "https://api.avito.ru/…/chats/%s/messages" % chat_key,
                "method": "POST", "auth": "Bearer " + (tokens.get("avito_access") or "<OAuth>"),
                "body": {"body": text}, "status": "реализовать обмен OAuth и поллинг токенов"}
    if platform in ("cian", "yandex_realty"):
        return {"endpoint": None, "status": "исходящих через API нет — ответить можно в ЛК площадки, "
                                           "в CRM сообщение отмечается как отправленное вручную"}
    return {"endpoint": "webhook вашего шлюза для %s" % platform, "method": "POST",
            "body": {"chat_key": chat_key, "text": text}}


ADAPTERS = {"avito": avito, "sutochno": sutochno, "spitti": spitti, "yandex_travel": yandex_travel,
            "yandex_realty": yandex_realty, "cian": cian, "website": website_form}


if __name__ == "__main__":
    samples = {
        "avito": {"chat_id": "c-100", "from": {"user": {"name": "Елена"}},
                  "message": {"body": "есть бассейн? свадьба 60 человек"}, "listing": {"id": 555}},
        "sutochno": {"chat_id": "ch-1", "guest": {"name": "Артём", "phone": "+79260001122"},
                     "message": "заезд в пятницу, 25 человек, нужен банкет"},
        "spitti": {"room_id": "r-7", "client": {"name": "Ольга", "phone": "+79031112233"},
                   "message": "баня и бассейн на выходные", "booking_id": "b-1"},
        "yandex_travel": {"booking": {"id": "yt-9", "guest": {"name": "Иван", "phone": "+79161234567"}}},
        "yandex_realty": {"offer_id": "yr-3", "name": "Марат", "phone": "+79876543210",
                          "message": "дом с баней, восток"},
        "cian": {"chat_id": "ci-5", "name": "Сергей", "phone": "+79998887766",
                 "message": "корпоратив 40 человек, близко к городу"},
        "website": {"form_id": "f-11", "name": "Алина", "phone": "+79055554433",
                    "comment": "свадьба 55 человек, юг, бюджет 260000"},
    }
    for name, ev in samples.items():
        print("%-14s → %s" % (name, json.dumps(ADAPTERS[name](ev), ensure_ascii=False)))
    print("call(mango)  →", json.dumps(norm_call(
        {"event": "call_answered", "caller_number": "+79161234567", "duration": 214,
         "internal": "marina", "recording_url": "https://mango/rec.wav"}, "mango"), ensure_ascii=False))
    print("outbound     →", json.dumps(send_chat_message("avito", "c-100", "Да, бассейн есть", {}),
                                        ensure_ascii=False))
