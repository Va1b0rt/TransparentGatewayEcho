# Transparent Gateway Echo

Окремий HTTPS echo endpoint для перевірки вихідної IP та заголовків TransparentGateway.
Docker Compose запускає Caddy і невеликий Python backend без сторонніх Python-залежностей.

## Розгортання на віддаленому сервері

Потрібні Docker Engine з Compose v2, публічна IP сервера та домен, наприклад
`echo.example.com`. A-запис має вказувати прямо на сервер. Якщо DNS обслуговує
Cloudflare, використовуйте **DNS only**, без CDN/proxy: для вимірювання потрібна
адреса TCP-клієнта саме вашого сервера. AAAA додавайте лише з робочим IPv6-доступом.
Порти TCP80/443 мають бути доступні з інтернету й вільні на сервері.

Склонуйте цей репозиторій або розпакуйте наданий архів, перейдіть у каталог проєкту:

```sh
cp .env.example .env
chmod 600 .env
nano .env
```

Вкажіть свої значення:

```dotenv
ECHO_DOMAIN=echo.example.com
ACME_EMAIL=you@example.com
RATE_LIMIT=60
RATE_PERIOD=60
```

Запустіть:

```sh
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
python3 verify.py https://echo.example.com/
```

Caddy автоматично отримає й надалі оновлюватиме TLS-сертифікат. Успішний `up --wait`
підтверджує стан контейнерів; випуск сертифіката може ще тривати. HTTPS перевіряйте
командою `verify.py` без `-k` чи вимкнення TLS-перевірки.

Для перевірки обмеження запитів, після нового часового вікна:

```sh
python3 verify.py https://echo.example.com/ --rate-test
```

Команда робить до75 послідовних запитів і очікує HTTP429 з `Retry-After`; вона
витратить поточну квоту IP. Зі стандартними налаштуваннями зачекайте60секунд перед
іншими перевірками. Фінальний результат — `PUBLIC_ECHO_CHECK PASS`.

Простий запит для перегляду відповіді:

```sh
curl --fail --silent --show-error https://echo.example.com/ | python3 -m json.tool
```

## Відповідь і довіра до IP

`backend_peer` — адреса TCP-клієнта, яку бачить Caddy; `request_id` генерує сервер,
і той самий ID повертається в response-header `X-Request-ID`. Вхідний `X-Request-ID`
повертається окремо в `headers`, щоб зіставити запит. `headers` містить тільки
дозволені діагностичні поля: forwarding/identity headers, host, user-agent та request ID.
Authorization, Proxy-Authorization і cookies не повертаються.

Caddy перезаписує службовий `X-TG-Peer`, тому клієнт не може задати його сам.
Оригінальний клієнтський `X-Forwarded-For` копіюється у службовий заголовок до зміни
Caddy й повертається як діагностичне поле; джерелом довіреної IP він не є.
Backend не має опублікованого порту та перебуває у внутрішній Docker-мережі.
Не публікуйте8080 і не додавайте в цю мережу сторонні контейнери. Якщо перед Caddy
стоїть інший reverse proxy/CDN, `backend_peer` покаже його адресу; така схема не
підходить для цього тесту без окремо перевіреної моделі довіри.

Endpoint приймає лише GET `/`; query/body відхиляються. Він нічого не проксіює,
не зберігає payload і повертає `Cache-Control: no-store`. Rate limit — fixed window
на IPv4 або IPv6 /64 в одному процесі, із максимумом10000 ключів. Після рестарту
лічильники скидаються; це не розподілений ліміт. Паралельність backend обмежено32
з'єднаннями, контейнерам задано ліміти пам'яті/PID, headers і timeouts обмежені.

## Логи, перезапуск і оновлення

```sh
docker compose logs --tail=30 echo caddy
docker compose restart
```

Backend пише лише `event`, серверний `request_id` і HTTP `status`. IP, URL, headers,
cookies, токени й клієнтський request ID у ці логи не записуються. HTTP access/error
логи Caddy вимкнені; операційні повідомлення TLS/startup лишаються для діагностики.
Docker обмежує розмір логів. Не вмикайте debug або request logging на цьому endpoint.

Обидва контейнери мають `restart: unless-stopped` і повертаються після reboot, якщо
Docker увімкнений на сервері. Сертифікати зберігаються в `caddy_data`. Не видаляйте
цей volume під час звичайного оновлення:

```sh
git pull --ff-only
docker compose config --quiet
docker compose up -d --build --wait
python3 verify.py https://echo.example.com/
```

Базові образи закріплені manifest-digest. Оновлюйте їх явно після перевірки нової версії.
`.env` містить лише домен, контакт ACME та rate settings; API credentials не потрібні.

## Тести

```sh
python3 -m unittest discover -s tests -v
```

Цей репозиторій перевіряє сам echo endpoint. Успіх прямого запиту до нього ще не
підтверджує публічний вихід через TransparentGateway: після розгортання потрібна
окрема перевірка з gateway та клієнтської VM.

Caddy: [автоматичний HTTPS](https://caddyserver.com/docs/automatic-https),
[налаштування runtime-логів](https://caddyserver.com/docs/caddyfile/options#log).

Для інсталяції з архіву замість `git pull` оновіть файли з наступного релізу,
зберігши власний `.env` та Docker volumes.
