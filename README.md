# HOMEd Device Request Bot

Telegram-бот для приёма заявок на добавление поддержки Zigbee-устройств в
[HOMEd](https://github.com/u236/homed-service-zigbee). Пользователи пишут заявку
боту, бот ведёт их по шагам issue-шаблона и сам создаёт issue на GitHub.
Заявки принимаются **только через бота** — вручную на GitHub ходить не нужно.

## Возможности

- Пошаговый диалог, повторяющий issue-шаблон репозитория:
  1. **Информация об устройстве** (обязательно) — данные из окна «⋮»
     в веб-интерфейсе HOMEd (JSON или текст).
  2. **Дополнительная информация** (необязательно) — название, ссылка на товар,
     особенности работы; `/skip` — пропустить.
- Автоматическое создание issue через GitHub API:
  - заголовок `[DEVICE] <имя/модель>` — вытаскивается из `friendly_name`,
    `model_id`, `model` или JSON-данных устройства;
  - лейбл `new device`;
  - тело в формате шаблона (данные устройства в code block + доп. информация).
- `/start` — начать заявку, `/cancel` — отменить, `/skip` — пропустить шаг 2.
- Фото прикладывается ссылкой на товар (в шаге 2) — Telegram-картинки
  напрямую к issue прикрепить нельзя.
- Опциональное ограничение по Telegram user_id (`allowed_users`).

## Требования

- Python 3.6+ (только стандартная библиотека, ничего ставить не нужно)
- Токен Telegram-бота (получить у [@BotFather](https://t.me/BotFather):
  `/newbot`)
- GitHub Personal Access Token (fine-grained):
  - GitHub → Settings → Developer settings →
    Personal access tokens → **Fine-grained tokens** → Generate new token
  - Repository access: *Only select repositories* → `homed-service-zigbee`
  - Permissions: **Issues → Read and write**, остальное не нужно
  - Токен начинается с `github_pat_...` и показывается один раз.

## Установка и запуск

1. Скопируйте на сервер два файла: `homed_device_bot.py` и
   `homed_device_bot.json`.

2. Впишите в `homed_device_bot.json`:

   ```json
   {
     "telegram_token": "123456:ABC-ваш-токен-от-BotFather",
     "github_token": "github_pat_ваш_токен",
     "github_repo": "u236/homed-service-zigbee",
     "allowed_users": [],
     "issue_labels": ["new device"],
     "issue_title_prefix": "[DEVICE] "
   }
   ```

   - `allowed_users` — пустой список = заявки принимает от всех; для
     ограничения впишите числа-`user_id` (узнать свой: [@userinfobot]).
   - `github_repo` — `owner/repo`, можно поменять на любой другой.

3. Тестовый запуск:

   ```bash
   python3 homed_device_bot.py
   ```

   Путь к конфигу можно передать аргументом:
   `python3 homed_device_bot.py /путь/к/конфигу.json`

4. Отправьте боту `/start` в Telegram и пройдите диалог — issue должен
   появиться в репозитории.

## Автозапуск (systemd)

Создайте `/etc/systemd/system/homed-device-bot.service`:

```ini
[Unit]
Description=HOMEd device request Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=ВАШ_ПОЛЬЗОВАТЕЛЬ
WorkingDirectory=/путь/к/папке/бота
ExecStart=/usr/bin/python3 /путь/к/папке/бота/homed_device_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Затем:

```bash
systemctl daemon-reload
systemctl enable --now homed-device-bot
systemctl status homed-device-bot   # проверить
journalctl -u homed-device-bot -f   # смотреть лог
```

## Файлы

| Файл | Назначение |
|------|------------|
| `homed_device_bot.py` | сам бот |
| `homed_device_bot.json` | настройки (токены, репозиторий, лейблы) |
