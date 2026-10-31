# Домофон Beward и локальный SIP

Стек для панели **Beward DKS20211**: звонок на квартиры `1`–`1000` приходит на одну страницу в браузере. Можно ответить, говорить, открыть дверь, записать лицо, временный код и ключ.

**Полная документация** (архитектура, все настройки с примерами, API, деплой, защита SIP):

→ **[DOCUMENTATION.md](DOCUMENTATION.md)**

## Коротко

1. Панель звонит на Kamailio (`ADVERTISE_IP`, порт **`15060`**).
2. Kamailio переводит вызов на софтфон `101` и добавляет `X-Apartment` / `X-Door-Station`.
3. Страница показывает звонок; после ответа RTP идёт напрямую между панелью и компьютером.
4. Настройки панелей и пароли — только в `config/` (локально) или `/etc/sip-server/` (прод). В git их нет; примеры — в `config.example/`.

Локальный стенд: [http://127.0.0.1:8090](http://127.0.0.1:8090).

```bash
mkdir -p config
cp config.example/env config.example/settings.json config.example/subscriber config/
docker compose up -d --build
```

Прод выкладывается push’ем в `master` (GitHub Actions → `deploy/up.sh`). На панели SIP-порт должен быть **`15060`**.
