# Transparent Gateway Echo

Окремий HTTPS echo endpoint для перевірки вихідної IP та заголовків TransparentGateway.
Docker Compose запускає Caddy і невеликий Python backend без сторонніх Python-залежностей.

## Розгортання за Nginx Proxy Manager (smhost)

Для наявного NPM `nginx-proxy-manager_app_1` у мережі
`nginx-proxy-manager_default` використовуйте **окремий** файл Compose нижче.
Він запускає тільки echo, без Caddy та без опублікованих портів.
Мережа NPM має вже існувати. Її контейнери входять у межу довіри backend:
не підключайте до неї недовірені застосунки. Для іншої назви задайте `NPM_NETWORK` у `.env`.

На `root@smhost` (`203.0.113.10`), у каталозі `~/TransparentGatewayEcho`:

```sh
git pull --ff-only
docker compose -f compose.npm.yaml config --quiet
docker compose -f compose.npm.yaml up -d --build --wait --remove-orphans
docker compose -f compose.npm.yaml ps
```

`--remove-orphans` прибирає Caddy лише з цього echo-проєкту; NPM — окремий проєкт.
Для всіх наступних операцій цього варіанта завжди додавайте `-f compose.npm.yaml`.
Старі `HTTP_BIND`, `HTTPS_BIND` та `ECHO_DOMAIN` цим варіантом не використовуються.

У NPM створіть/відредагуйте Proxy Host:

| Поле | Значення |
|---|---|
| Domain Names | `echo.devdays.net.ua` |
| Scheme | `http` |
| Forward Hostname / IP | `tg-public-echo` |
| Forward Port | `8080` |
| Cache Assets / Block Common Exploits / Websockets | вимкнено |
| Access List | Publicly Accessible |
| Custom Locations | порожньо |
| SSL | дійсний сертифікат для `echo.devdays.net.ua` |
| Force SSL | увімкнено |

У вкладку **Advanced** скопіюйте **весь** вміст `npm-advanced.conf`,
потім збережіть. Без цього блоку перевірка IP не працюватиме правильно.
Сертифікат випускається/поновлюється NPM. Cloudflare Proxied + Full може лишитися;
Full (strict) можна використовувати з дійсним довіреним сертифікатом origin.

```sh
cat npm-advanced.conf
docker exec nginx-proxy-manager_app_1 nginx -t
python3 verify.py https://echo.devdays.net.ua/
```

Очікується `PUBLIC_ECHO_CHECK PASS`. Публічний порт — звичайний HTTPS443 NPM.
Після нового rate window можна додати `--rate-test`.

Advanced використовує `$realip_remote_addr`, щоб перевіряти саме TCP-адресу
Cloudflare до переписування `$remote_addr` модулем realip NPM. Backend перевіряє
її за списком Cloudflare і лише тоді довіряє `CF-Connecting-IP`. Прямі запити
позначаються `npm_tcp_peer`. Заголовки діагностики зберігаються після Cloudflare,
до стандартних доповнень NPM. Backend API і Caddy-варіант сумісні.

Access/error logs вимкнено всередині echo location; backend лишає тільки
згенерований request ID і статус. Це не вимикає глобальні логи NPM, TLS-помилки,
логи відхилених до вибору location запитів або журнал Cloudflare. Не надсилайте
production secrets у діагностичних запитах. Перевірка локального nginx не замінює
перевірку фактичного NPM та публічного маршруту після збереження Proxy Host.

## Розгортання на віддаленому сервері

Потрібні Docker Engine з Compose v2 та Cloudflare **Proxied + SSL/TLS Full**.
Для поточного стенда: `echo.devdays.net.ua` → A `203.0.113.10`, помаранчева хмаринка.
Caddy автоматично випускає локальний сертифікат від власного CA (`tls internal`).
Зовнішнього ACME, email і Cloudflare API token не потрібно. Сертифікат для відвідувачів
обслуговує Cloudflare. Цей локальний origin-сертифікат підходить для **Full**, але
не для **Full (strict)**. Full шифрує origin-з'єднання, не перевіряючи довіру до його
сертифіката. AAAA додавайте лише з робочим IPv6-доступом.
Порти TCP80/443 мають бути доступні з інтернету й вільні на сервері.

Склонуйте цей репозиторій або розпакуйте наданий архів, перейдіть у каталог проєкту:

```sh
cp .env.example .env
chmod 600 .env
nano .env
```

Достатньо такого `.env` (старий рядок `ACME_EMAIL` можна видалити):

```dotenv
ECHO_DOMAIN=echo.devdays.net.ua
RATE_LIMIT=60
RATE_PERIOD=60
```

Запустіть:

```sh
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
python3 verify.py https://echo.devdays.net.ua/
```

Caddy створює й оновлює локальний сертифікат без звернення до ACME. Успішний
`up --wait` підтверджує стан контейнерів. Публічний HTTPS через Cloudflare перевіряйте
командою `verify.py` без `-k` чи вимкнення TLS-перевірки.

Для перевірки обмеження запитів, після нового часового вікна:

```sh
python3 verify.py https://echo.devdays.net.ua/ --rate-test
```

Команда робить до75 послідовних запитів і очікує HTTP429 з `Retry-After`; вона
витратить поточну квоту IP. Зі стандартними налаштуваннями зачекайте60секунд перед
іншими перевірками. Фінальний результат — `PUBLIC_ECHO_CHECK PASS`.

Простий запит для перегляду відповіді:

```sh
curl --fail --silent --show-error https://echo.devdays.net.ua/ | python3 -m json.tool
```

## Перший публічний запуск: HTTP 403 замість JSON

08.09.2026 після налаштування NPM перший запуск `verify.py` завершився
`ECHO_CHECK FAILED: JSONDecodeError; no response payload displayed`.
Звичайний curl отримував HTTP200/JSON. Порівняння клієнтів показало:
стандартний `Python-urllib/3.8` отримував HTTP403 з `error code: 1010`,
а `TG-Echo-Verify/1.0` — HTTP200. Окремо вхідний підроблений
`CF-Connecting-IP` отримував HTTP403 ще на публічному маршруті.

Виправлення: власний відкрито названий User-Agent перевіряльника; окрема проба
підробленого CF-заголовка, що приймає HTTP403 як відхилення запиту або HTTP200
лише з незмінною IP. Відхилення цієї проби не доводить обробку заголовка backend;
це явно зазначено у виводі. Решта тестів, зокрема підроблений `X-TG-Peer`,
обов'язково має дійти до JSON-відповіді backend.
Помилки не-JSON тепер показують етап, HTTP-статус, обмежені метадані й код
Cloudflare, без виведення response body. Налаштування Cloudflare не змінювали.
Після виправлення публічна перевірка з ARIS пройшла, включно з HTTP429/Retry-After.
Це ще не перевірка виходу із клієнтської VM через gateway.

[Cloudflare 1010](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/).

## Відповідь і довіра до IP

`backend_peer` — клієнтська адреса з `CF-Connecting-IP`, якщо TCP-з'єднання прийшло
з офіційної мережі Cloudflare. Відповідь позначена
`peer_source: cloudflare_cf_connecting_ip` і `headers_view: after_cloudflare`.
Для прямого з'єднання повертається фактична адреса TCP-клієнта Caddy,
`peer_source: caddy_tcp_peer`; надісланим ним CF-заголовкам довіри немає.
Cloudflare Worker subrequests відхиляються через іншу семантику IP.

`request_id` генерує сервер,
і той самий ID повертається в response-header `X-Request-ID`. Вхідний `X-Request-ID`
повертається окремо в `headers`, щоб зіставити запит. `headers` містить тільки
дозволені діагностичні поля: forwarding/identity headers, host, user-agent та request ID.
Authorization, Proxy-Authorization і cookies не повертаються.

Caddy перезаписує службовий `X-TG-Peer`, тому клієнт не може задати його сам.
Отриманий Caddy `X-Forwarded-For` копіюється у службовий заголовок до зміни
Caddy й повертається як діагностичне поле; джерелом довіреної IP він не є.
Backend не має опублікованого порту та перебуває у внутрішній Docker-мережі.
Не публікуйте8080 і не додавайте в цю мережу сторонні контейнери.
Список довірених мереж у `cloudflare-ips.txt` звірений з офіційними IPv4/IPv6-списками
08.09.2026; оновлюйте його явно після перевірки змін і перебудовуйте образ.
Cloudflare може змінювати forwarding headers до передачі origin: це діагностика
заголовків **після Cloudflare**, а не повний доказ відсутності початкових IP-витоків.
Зокрема Cloudflare може прибирати `X-Real-IP`; не називайте таку перевірку повним
аудитом анонімності. Для NPM використовуйте окрему конфігурацію вище. Інші reverse proxy без окремої конфігурації довіри не підтримуються.

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
python3 verify.py https://echo.devdays.net.ua/
```

Базові образи закріплені manifest-digest. Оновлюйте їх явно після перевірки нової версії.
`.env` містить лише домен, rate settings; API credentials не потрібні.

## Тести

```sh
python3 -m unittest discover -s tests -v
```

Інтеграційний тест nginx (ізольований Compose, порт лише `127.0.0.1:18081`):

```sh
sudo docker compose -f tests/nginx/compose.yaml up -d --build --wait
sudo docker compose -f tests/nginx/compose.yaml exec -T nginx nginx -t
python3 tests/nginx/check.py
sudo docker compose -f tests/nginx/compose.yaml down
```

Тест навмисно переписує nginx remote_addr та перевіряє збереження фізичного peer,
відкидання підроблених службових/CF-заголовків, діагностичні поля, rate limit і
відсутність секретного маркера у логах. `tests/nginx/nginx.conf` — тільки тестова
конфігурація; для NPM використовуйте `npm-advanced.conf`.

Цей репозиторій перевіряє сам echo endpoint. Успіх прямого запиту до нього ще не
підтверджує публічний вихід через TransparentGateway: після розгортання потрібна
окрема перевірка з gateway та клієнтської VM.

Документація: [Cloudflare Full](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full/),
[Caddy tls internal](https://caddyserver.com/docs/caddyfile/directives/tls),
[Cloudflare HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/),
[довірені IPv4](https://www.cloudflare.com/ips-v4), [IPv6](https://www.cloudflare.com/ips-v6),
[налаштування runtime-логів](https://caddyserver.com/docs/caddyfile/options#log).

Для інсталяції з архіву замість `git pull` оновіть файли з наступного релізу,
зберігши власний `.env` та Docker volumes.
