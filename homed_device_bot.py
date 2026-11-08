#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот для приёма заявок на добавление Zigbee-устройств в HOMEd.

Собирает данные в диалоге (по шагам, как в issue-шаблоне репозитория) и
сам создаёт issue на GitHub через API. Запросы принимаются только через
бота — напрямую на GitHub пользователь ходить не должен.

Настройки: homed_device_bot.json рядом со скриптом (путь можно передать
первым аргументом). При отсутствии создаётся шаблон.

Запуск: python3 homed_device_bot.py
Остановка: Ctrl+C. Для systemd-автозапуска см. комментарии внизу файла.

Команды бота:
  /start    — начать заявку
  /cancel   — отменить текущую заявку
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

SCRIPT_PATH = os.path.abspath(sys.argv[0])
DEFAULT_CONFIG = os.path.join(os.path.dirname(SCRIPT_PATH), "homed_device_bot.json")

DEFAULTS = {
    "telegram_token": "",
    "github_token": "",
    "github_repo": "u236/homed-service-zigbee",
    "allowed_users": [],            # [] = любой; иначе список Telegram user_id
    "issue_labels": ["new device"],
    "issue_title_prefix": "[DEVICE] ",
}

CFG = {}

# ------------------------------ конфиг ------------------------------------
def load_config():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULTS, f, ensure_ascii=False, indent=2)
        print("Файл настроек не найден — создан шаблон: %s" % path)
        print("Заполните telegram_token и github_token и запустите снова.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        user = json.load(f)
    cfg = dict(DEFAULTS)
    cfg.update(user)
    if not cfg["telegram_token"]:
        sys.exit("config: не задан telegram_token")
    if not cfg["github_token"]:
        sys.exit("config: не задан github_token")
    if "/" not in cfg["github_repo"]:
        sys.exit("config: github_repo должен быть вида owner/repo")
    return cfg


# ------------------------------ Telegram ----------------------------------
TG_API = "https://api.telegram.org/bot%s/%s"


def tg(method, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(TG_API % (CFG["telegram_token"], method),
                                 data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def tg_send(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = {"keyboard": keyboard, "resize_keyboard": True}
    try:
        tg("sendMessage", payload)
    except Exception as e:
        print("telegram send ошибка: %s" % e)


def tg_send_plain(chat_id, text):
    """Без parse_mode (для эхо-сообщений с <, >, & и т.п.)."""
    payload = {"chat_id": chat_id, "text": text[:4096]}
    try:
        tg("sendMessage", payload)
    except Exception as e:
        print("telegram send ошибка: %s" % e)


# ------------------------------- GitHub ------------------------------------
def gh_create_issue(title, body, labels):
    url = "https://api.github.com/repos/%s/issues" % CFG["github_repo"]
    payload = {"title": title, "body": body, "labels": labels}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={
                                     "Authorization": "token " + CFG["github_token"],
                                     "Accept": "application/vnd.github+json",
                                     "Content-Type": "application/json",
                                     "User-Agent": "homed-device-bot",
                                 })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print("GitHub ошибка %s: %s" % (e.code, e.read().decode()[:500]))
        return None


# ------------------------------- диалог -------------------------------------
# state per chat: {"step": ..., "device_info": ..., "additional_info": ...}
SESSIONS = {}

ASK_DEVICE_INFO = (
    "➕ Добавление Zigbee-устройства\n\n"
    "Шаг 1/2. <b>Информация об устройстве</b> (обязательно):\n\n"
    "1. Откройте устройство в веб-интерфейсе HOMEd.\n"
    "2. Нажмите кнопку с тремя точками (⋮).\n"
    "3. Скопируйте содержимое открывшегося окна.\n"
    "4. Отправьте сюда."
)
ASK_ADDITIONAL = (
    "Шаг 2/2. <b>Дополнительная информация</b> (необязательно):\n\n"
    "Название устройства, ссылка на товар, особенности работы и т.д.\n\n"
    "Отправьте текст или /skip чтобы пропустить."
)


def start_session(chat_id):
    SESSIONS[chat_id] = {"step": "device_info"}
    tg_send(chat_id, ASK_DEVICE_INFO)


def build_issue_body(sess):
    return (
        "Запрос отправлен через Telegram-бота.\n\n"
        "### Информация об устройстве\n\n"
        "```\n%s\n```\n\n"
        "### Дополнительная информация\n\n%s"
    ) % (sess["device_info"], sess.get("additional_info") or "—")


def issue_title(sess):
    raw = sess["device_info"]
    # данные из HOMEd часто JSON — пробуем вытащить понятное имя/модель
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for k in ("friendly_name", "name", "model", "model_id", "description"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    return CFG["issue_title_prefix"] + v.strip()[:80]
            man = (data.get("manufacturer") or "").strip()
            mod = (data.get("model") or data.get("model_id") or "").strip()
            if man or mod:
                return CFG["issue_title_prefix"] + ("%s %s" % (man, mod)).strip()[:80]
    except (ValueError, AttributeError):
        pass
    import re as _re
    m = _re.search(r'"(?:friendly_name|model_id|model|name|description)"\s*:\s*"([^"]{2,80})"', raw)
    if m:
        return CFG["issue_title_prefix"] + m.group(1).strip()[:80]
    for line in raw.splitlines():
        s = line.strip().strip(',":{}')
        if s and "{" not in s and "}" not in s:
            return CFG["issue_title_prefix"] + s[:80]
    return CFG["issue_title_prefix"] + "запрос из Telegram"


def finish_session(chat_id, sess):
    resp = gh_create_issue(issue_title(sess),
                           build_issue_body(sess),
                           CFG["issue_labels"])
    SESSIONS.pop(chat_id, None)
    if resp and resp.get("number"):
        tg_send(chat_id,
                "✅ Заявка создана:\n%s" % resp.get("html_url", ""))
    else:
        tg_send(chat_id,
                "❌ Не удалось создать issue на GitHub. "
                "Попробуйте позже или обратитесь к администратору (ошибка в логах сервера).")


def allowed(update):
    if not CFG["allowed_users"]:
        return True
    return update.get("message", {}).get("from", {}).get("id") in CFG["allowed_users"]


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0] if text else ""

    if cmd == "/start":
        start_session(chat_id)
        return
    if cmd == "/cancel":
        SESSIONS.pop(chat_id, None)
        tg_send(chat_id, "Заявка отменена. /start — новая заявка.")
        return
    if cmd == "/skip":
        sess = SESSIONS.get(chat_id)
        if sess and sess.get("step") == "additional_info":
            sess["additional_info"] = None
            finish_session(chat_id, sess)
        return

    sess = SESSIONS.get(chat_id)
    if not sess:
        tg_send(chat_id,
                "Здравствуйте! Я принимаю заявки на добавление поддержки "
                "Zigbee-устройств в HOMEd.\n\n/start — начать заявку.")
        return

    if sess["step"] == "device_info":
        if len(text) < 10:
            tg_send(chat_id, "Слишком короткий текст. Вставьте данные из окна "
                             "под тремя точками в веб-интерфейсе HOMEd.")
            return
        sess["device_info"] = text
        sess["step"] = "additional_info"
        tg_send(chat_id, ASK_ADDITIONAL,
                keyboard=[["/skip — пропустить"]])
        return

    if sess["step"] == "additional_info":
        sess["additional_info"] = text
        finish_session(chat_id, sess)
        return


def main():
    global CFG
    CFG = load_config()
    print("Бот запущен. Репозиторий: %s" % CFG["github_repo"])
    offset = 0
    while True:
        try:
            resp = tg("getUpdates", {
                "offset": offset + 1, "timeout": 50,
                "allowed_updates": ["message"],
            })
            for upd in resp.get("result", []):
                offset = max(offset, upd["update_id"])
                msg = upd.get("message")
                if not msg or not msg.get("text"):
                    if msg:
                        tg_send(msg["chat"]["id"],
                                "Пожалуйста, отправляйте текст. Фото прикрепляйте "
                                "ссылкой на товар в поле «Дополнительная информация».")
                    continue
                if not allowed(upd):
                    continue
                try:
                    handle_message(msg)
                except Exception as e:
                    print("ошибка обработки: %s" % e)
                    tg_send(msg["chat"]["id"], "⚠️ Внутренняя ошибка, попробуйте ещё раз.")
        except urllib.error.URLError as e:
            print("сетевая ошибка: %s, повтор через 5с" % e)
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nОстановлено.")
            break


if __name__ == "__main__":
    main()

# ----------------------------------------------------------------------------
# systemd-юнит (/etc/systemd/system/homed-device-bot.service):
#
# [Unit]
# Description=HOMEd device request Telegram bot
# After=network-online.target
# Wants=network-online.target
#
# [Service]
# User=ВЫ
# WorkingDirectory=/путь/к/папке
# ExecStart=/usr/bin/python3 /путь/к/папке/homed_device_bot.py
# Restart=always
# RestartSec=10
#
# [Install]
# WantedBy=multi-user.target
#
# systemctl daemon-reload && systemctl enable --now homed-device-bot
