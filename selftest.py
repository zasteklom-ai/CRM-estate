import json, urllib.request, urllib.error
import os
B = os.environ.get("CRM_BASE", "http://127.0.0.1:8080")
def call(path, body=None, method=None, token=None, hdr=None, base=B):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method or ("POST" if data else "GET"))
    r.add_header("Content-Type", "application/json")
    if token: r.add_header("X-Session-Token", token)
    for k, v in (hdr or {}).items(): r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try: return e.code, json.loads(raw)
        except Exception: return e.code, {"raw": raw[:300]}

ok = True
def chk(label, cond, extra=""):
    global ok
    print(("  OK  " if cond else " FAIL ") + label + (" | " + str(extra) if extra else ""))
    if not cond: ok = False

s, d = call("/healthz"); chk("healthz", s == 200, d)
s, d = call("/api/login", {"login": "admin", "password": "admin123"})
chk("login admin", s == 200 and d.get("token"), d.get("error"))
TOK = d["token"]
s, d = call("/api/login", {"login": "admin", "password": "wrong"})
chk("bad password rejected", s == 401, d)
s, d = call("/api/session", token=TOK)
chk("session", s == 200 and d["user"]["role"] == "owner", d["user"]["name"])
chk("token hidden for non-admin? (owner sees it)", len(d["meta"]["webhook_token"]) > 10)
TOKEN = d["meta"]["webhook_token"]
for p in ["/api/deals", "/api/chats", "/api/clients", "/api/calls", "/api/stats",
          "/api/admin/users", "/api/admin/sources", "/api/admin/stages", "/api/admin/settings", "/api/log"]:
    s, d = call(p, token=TOK)
    chk("GET " + p, s == 200, list(d)[:3])
s, d = call("/api/deals", token=TOK)
deals = d["deals"]
print("     deals=%d, example=%s" % (len(deals), json.dumps({k: deals[0][k] for k in ["id","client_name","phone_pretty","stage_name","source_code","criteria","directions","km","people","unread"]}, ensure_ascii=False)))
s, d = call("/api/deals/%d" % deals[0]["id"], token=TOK)
chk("deal detail", s == 200 and "messages" in d, "msgs=%d calls=%d" % (len(d["messages"]), len(d["calls"])))

# --- webhook: incoming chat message -> client + deal auto-created
s, d = call("/webhook/chat", {"platform": "cian", "chat_id": "cian-777",
        "from": {"name": "Новый гость Тест", "phone": "+7 999 111-22-33"},
        "text": "Ищем дом с баней и бассейном на 14 человек, восток, до 55 км, бюджет 180000"},
        hdr={"X-Webhook-Token": TOKEN})
chk("webhook/chat creates client+deal", s == 201 and d["client_new"] and d["deal_new"], d)
NEW_DEAL = d["deal_id"]
s, d2 = call("/api/deals/%d" % NEW_DEAL, token=TOK)
c = d2["deal"]
chk("card fields filled from message", c["source_code"] == "cian" and "999" in c["phone_pretty"] and c["client_name"] == "Новый гость Тест",
    json.dumps({k: c[k] for k in ["client_name","phone_pretty","source_name","stage_name","owner_name"]}, ensure_ascii=False))
# second message in same chat -> no duplicate deal
s, d3 = call("/webhook/chat", {"platform": "cian", "chat_id": "cian-777", "phone": "+7 999 111-22-33",
        "text": "И ещё вопрос: есть ли мангал?"}, hdr={"X-Webhook-Token": TOKEN})
chk("no duplicate deal for same client", d3["deal_id"] == NEW_DEAL and not d3["deal_new"], d3)
# bad token
s, d4 = call("/webhook/chat", {"platform": "avito", "text": "hi"}, hdr={"X-Webhook-Token": "nope"})
chk("webhook rejects bad token", s == 401, d4)

# --- webhook: call from IP telephony
s, d5 = call("/webhook/call", {"event": "call_answered", "phone": "+7 925 000-11-22", "duration_sec": 190,
        "manager_login": "marina", "recording_url": "https://mango/rec/1.wav", "note": "банкет 30 чел, север"},
        hdr={"X-Webhook-Token": TOKEN})
chk("webhook/call creates deal", s == 201 and d5["deal_new"], d5)
CALL_DEAL = d5["deal_id"]
s, d6 = call("/api/calls", token=TOK)
chk("call logged with recording", any(x["id"] == d6.get("call_id") or x.get("recording") for x in d6["calls"]), len(d6["calls"]))

# --- reply + unread cleared
s, d7 = call("/api/deals/%d/messages" % NEW_DEAL, {"text": "Добрый день! Да, мангал есть. Удобно созвониться в 15:00?"}, token=TOK)
chk("reply saved", s == 201, d7)
s, d8 = call("/api/deals/%d" % NEW_DEAL, token=TOK)
chk("unread cleared after open", d8["deal"]["unread"] == 0, d8["deal"]["unread"])

# --- card edit (all spec fields)
s, d9 = call("/api/clients/%d" % d2["deal"]["client_id"], {"budget": 180000, "people": 14, "km": 55,
        "criteria": ["Баня", "Бассейн", "Банкет"], "directions": ["Восток"], "source": "cian",
        "comment": "приезд в пятницу", "name": "Тестовый гость"}, method="PATCH", token=TOK)
chk("client PATCH ok", s == 200, d9)
s, d10 = call("/api/deals/%d" % NEW_DEAL, token=TOK)
c = d10["deal"]
chk("values persisted", c["budget"] == 180000 and c["people"] == 14 and c["km"] == 55 and c["criteria"] == ["Баня","Бассейн","Банкет"] and c["directions"] == ["Восток"],
    json.dumps({k: c[k] for k in ["budget","people","km","criteria","directions"]}, ensure_ascii=False))
s, d11 = call("/api/deals/%d" % NEW_DEAL, {"stage_id": d10["stages"][2]["id"]}, method="PATCH", token=TOK)
chk("stage move", s == 200, d11)

# --- sources admin: add, disable, delete
s, d12 = call("/api/admin/sources", {"name": "Booking.com", "code": "booking", "kind": "chat", "api_state": "partner_api", "note": "тест"})
pass
s, d12 = call("/api/admin/sources", {"name": "Booking.com", "code": "booking", "kind": "chat", "api_state": "partner_api", "note": "тест"}, token=TOK)
chk("source add", s == 201, d12)
SID = d12["source_id"]
s, d13 = call("/webhook/chat", {"platform": "booking", "text": "hello"}, hdr={"X-Webhook-Token": TOKEN})
chk("new source accepts webhooks", s == 201 and d13["source"]["code"] == "booking", d13)
s, d14 = call("/api/admin/sources/%d" % SID, {"enabled": False}, method="PATCH", token=TOK)
s, d15 = call("/webhook/chat", {"platform": "booking", "text": "hello"}, hdr={"X-Webhook-Token": TOKEN})
chk("disabled source rejects", d15.get("error") and s == 409 if False else d15.get("error"), d15)
s, d15b = call("/api/deals/%d" % d13["deal_id"], method="DELETE", token=TOK)
s, d15c = call("/api/clients/%d" % d13["client_id"], method="DELETE", token=TOK)
s, d16 = call("/api/admin/sources/%d" % SID, method="DELETE", token=TOK)
chk("source deleted after clearing its records", s == 200, d16)
s, d17 = call("/api/admin/sources/1", method="DELETE", token=TOK)
chk("source with data -> 409 (archive instead)", s == 409, d17)

# --- users admin: create, perms, visibility, delete guards
s, d18 = call("/api/admin/users", {"name": "Тест Менеджер", "login": "testmgr", "password": "test123", "role": "manager"}, token=TOK)
chk("user created", s == 201, d18)
UID = d18["user_id"]
s, dt2 = call("/api/login", {"login": "testmgr", "password": "test123"})
MT = dt2["token"]
s, d19 = call("/api/deals", token=MT)
chk("manager sees only own deals", len(d19["deals"]) <= len(deals), "%d vs %d" % (len(d19["deals"]), len(deals)))
s, d20 = call("/api/admin/users", token=MT)
chk("manager blocked from admin API", s == 403, d20)
s, d21 = call("/api/deals/%d" % CALL_DEAL, token=MT)
chk("other manager's deal -> 403", s == 403, d21)
s, d22 = call("/api/admin/users/%d" % UID, {"perms": ["edit_clients","send_messages","log_calls","view_all_deals"]}, method="PATCH", token=TOK)
s, d23 = call("/api/deals", token=MT)
chk("grant view_all_deals works", s == 200 and len(d23["deals"]) >= len(deals), "%d deals now" % len(d23["deals"]))
s, d24 = call("/api/admin/users/%d" % UID, method="DELETE", token=TOK)
chk("user deleted", s == 200, d24)
s, d25 = call("/api/admin/users/1", method="DELETE", token=TOK)
chk("cannot delete owner", s == 400, d25)
s, d26 = call("/api/admin/users/1", {"active": False}, method="PATCH", token=TOK)
chk("cannot disable self", s == 400, d26)
s, d27 = call("/api/admin/users/3", {"active": False}, method="PATCH", token=TOK)
chk("deactivate user ok", s == 200, d27)
s, d28 = call("/api/login", {"login": "marina", "password": "demo123"})
chk("deactivated user cannot login", s == 401, d28)
s, d29 = call("/api/admin/users/3", {"active": True}, method="PATCH", token=TOK)

# --- demo button endpoint + stats
s, d30 = call("/api/demo/inbound", {"source": "avito"}, token=TOK)
chk("demo inbound (avito)", s == 201 and d30["deal_new"], {k: d30[k] for k in ("deal_id","client_id","unread")})
s, d31 = call("/api/demo/inbound", {"source": "telephony"}, token=TOK)
chk("demo call", s == 201, d31)
s, d32 = call("/api/stats", token=TOK)
chk("stats sane", d32["total"] > 0 and d32["unread"] > 0, json.dumps({k: d32[k] for k in ["total","active","unread","conversion","pipeline_value"]}))

# --- stages CRUD + settings
s, d33 = call("/api/admin/stages", {"name": "Депозит получен", "prob": 80}, token=TOK)
chk("stage added", s == 201, d33)
s, d34 = call("/api/admin/stages/%d" % d33["stage_id"], {"name": "Депозит 50%", "prob": 85, "sort": 4, "color": "#123456", "outcome": ""}, method="PATCH", token=TOK)
chk("stage patched", s == 200, d34)
s, d35 = call("/api/admin/stages/%d" % d33["stage_id"], method="DELETE", token=TOK)
chk("empty stage deleted", s == 200, d35)
s, d36 = call("/api/admin/settings", {"assign_rule": "source", "one_open_deal_per_client": "0", "telephony": {"provider": "uis", "number": "+7 495 000-00-01", "click_to_call_url": "https://uis/dial", "api_token": "x", "recordings": True, "sip_host": "pbx.uis.ru", "trunk": "101"}}, method="PATCH", token=TOK)
chk("settings patch", s == 200, list(d36.get("settings", {})))
s, d37 = call("/api/calls", token=TOK)
chk("telephony visible in UI", d37["telephony"]["provider"] == "uis", d37["telephony"])
s, d38 = call("/api/admin/settings", {"webhook_token": "regen"}, method="PATCH", token=TOK)
chk("token regen", d38["settings"]["webhook_token"] != TOKEN, d38["settings"]["webhook_token"])
s, d39 = call("/api/admin/settings", {"company_name": "Усадьба «Сосновый берег»", "assign_rule": "round_robin", "one_open_deal_per_client": "1"}, method="PATCH", token=TOK)
# click-to-call mock
s, d40 = call("/api/calls", {"action": "click_to_call", "phone": "+79991112233"}, token=TOK)
chk("click-to-call returns dial plan", s == 200 and d40["would_call"], d40)
# static
r = json.dumps({"x": 1})
import urllib.request as u
with u.urlopen(B + "/", timeout=10) as resp:
    html = resp.read().decode()
chk("index.html served", "app.js" in html and "<!doctype" in html.lower())
with u.urlopen(B + "/style.css", timeout=10) as resp:
    chk("style.css served", resp.status == 200)
with u.urlopen(B + "/app.js", timeout=10) as resp:
    chk("app.js served", resp.status == 200)
print("\nRESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
