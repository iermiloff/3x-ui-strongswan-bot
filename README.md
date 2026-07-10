# 🚀 Hybrid VPN Telegram Bot (3x-ui + StrongSwan)

Асинхронный Telegram-бот на **aiogram 3.x** и **PostgreSQL** для автоматизации продаж и управления подписками VPN. Поддерживает гибридную работу с панелью 3x-ui (мульти-выдача любых протоколов: VLESS Reality, Trojan gRPC, Shadowsocks) и нативным протоколом IKEv2 (StrongSwan) для Apple-устройств и роутеров.

## ✨ Ключевые фичи
- **Динамическая админка инбаундов:** Назначение и переключение портов 3x-ui по тарифам прямо из Telegram-интерфейса без правки `.env`.
- **Мульти-протокольная выдача:** Привязка нескольких ключей к одной подписке (клиент получает VLESS + Trojan одновременно одной пачкой).
- **Идемпотентность (Продление):** Безопасное продление тарифов без генерации дубликатов UUID и без ошибок уникальности базы данных.
- **Умный триал:** Выдача бесплатного теста на 1 день строго раз в 30 дней и только на базовых протоколах 3x-ui (без дергания StrongSwan).
- **Автоматизация оплаты:** Интеграция с CryptoBot API (поддержка Testnet/Mainnet).
- **Защита продакшна (Race Condition):** Атомарная блокировка повторных кликов через FSM aiogram и сетевые таймауты (`asyncio.wait_for`) для всех внешних API и SSH.
- **Автоматическое ночное отключение:** Ежесуточный фоновый скрипт (APScheduler в 03:00 UTC) отключает протухшие подписки пачкой, минимизируя перезапуски StrongSwan.
- **Удобный UX:** Автоматическая генерация QR-кодов в оперативной памяти (без нагрузки на SSD) с защитой от лимитов длины описания Telegram API.

---

## 🛠 Пошаговая установка на удаленный Linux-сервер (Ubuntu 22.04 / 24.04)

### 1. Подготовка системы
Обновите пакеты и установите Docker с Docker Compose:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose git
sudo systemctl enable --now docker
```

### 2. Клонирование репозитория
Склонируйте проект и перейдите в его директорию:
```bash
git clone https://github.com/iermiloff/3x-ui-strongswan-bot
cd 3x-ui-strongswan-bot
```

### 3. Настройка конфигурации (`.env`)
Создайте файл `.env` на основе шаблона:
```bash
cp .env.example .env
nano .env
```
Заполните обязательные поля (токен бота, ID админов, доступы к 3x-ui и SSH для StrongSwan).

> **Важно для StrongSwan:** Убедитесь, что на сервере VPN создана директория `/etc/swanctl/conf.d/` для изолированных конфигураций пользователей, а у пользователя SSH есть права root/sudo на перезапуск.

### 4. Создание Docker Compose манифеста
Создайте в корне проекта файл `docker-compose.yml`:
```bash
nano docker-compose.yml
```

Вставьте в него следующую конфигурацию:
```yaml
version: '3.8'

services:
  postgres_db:
    image: postgres:15-alpine
    container_name: vpn_postgres_db
    restart: always
    environment:
      POSTGRES_USER: \${DB_USER}
      POSTGRES_PASSWORD: \${DB_PASSWORD}
      POSTGRES_DB: \${DB_NAME}
      TZ: UTC
    volumes:
      - postgres_vpn_data:/var/lib/postgresql/data
    ports:
      - "\${DB_PORT}:5432"

  bot:
    build: .
    container_name: vpn_telegram_bot
    restart: always
    depends_on:
      - postgres_db
    environment:
      TZ: UTC
    volumes:
      - ./.env:/app/bot/.env
      # Если SSH-ключ для StrongSwan лежит локально, пробросьте его в контейнер:
      # - /root/.ssh/id_rsa:/root/.ssh/id_rsa:ro

volumes:
  postgres_vpn_data:
```

### 5. Запуск всей экосистемы
Запустите сборку и старт контейнеров в фоновом режиме (демон):
```bash
docker-compose up -d --build
```
*Контейнер бота при первом запуске автоматически применит миграции Alembic (ревизии 001 и 002) и создаст таблицы `users`, `subscriptions`, `vpn_keys` и `tariff_inbounds`.*

### 6. Первый запуск и привязка портов
1. Откройте вашего бота в Telegram и напишите ему команду `/start`.
2. Перейдите в меню **📊 Статистика** (доступно админам, указанным в `ADMIN_IDS`).
3. Нажмите кнопку **⚙️ Настройка инбаундов 3x-ui**. Бот выведет реальную сетку портов из вашей панели.
4. Кликайте по кнопкам портов, распределяя их между тарифами (`BASE` или `PREMIUM`). 
5. Всё готово! Бот готов автоматически генерировать и выдавать ключи пользователям.

### 7. Проверка логов
Посмотреть логи работы бота в реальном времени:
```bash
docker-compose logs -f bot
```

