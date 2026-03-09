# Развёртывание бота на сервере

Все файлы подготовлены для запуска на сервере.

## Файлы для деплоя

| Файл | Назначение |
|------|------------|
| `main.py` | Точка входа |
| `bot/` | Код бота |
| `requirements.txt` | Зависимости Python |
| `amvera.yaml` | Конфиг для Amvera Cloud |
| `Dockerfile` | Сборка Docker-образа |
| `docker-compose.yml` | Запуск через Docker Compose |
| `.env.example` | Шаблон переменных окружения |

## Важно: не загружайте на сервер

- `.env` — содержит секреты (в .gitignore)
- `bot.db` — локальная БД (в .gitignore)
- `debug_*.txt`, `*.log` — логи (в .gitignore)

## Способы запуска

### 1. Amvera Cloud

1. Загрузите проект (через GitHub или интерфейс)
2. Задайте переменные окружения в панели
3. Обязательно: `DATABASE_PATH=/data/bot.db`
4. Сборка и запуск — автоматически

Подробнее: `DEPLOY_AMVERA.md`, `AMVERA_ИНСТРУКЦИЯ.md`

### 2. Docker (VPS, свой сервер)

```bash
# Сборка и запуск
docker-compose up -d

# Или без compose
docker build -t mirage-bot .
docker run -d --restart unless-stopped \
  -e BOT_TOKEN=xxx \
  -e ADMIN_IDS=xxx \
  -e GROUP_ID=xxx \
  -e DATABASE_PATH=/data/bot.db \
  -v bot_data:/data \
  mirage-bot
```

### 3. Обычный Python (VPS)

```bash
pip install -r requirements.txt
export BOT_TOKEN=xxx
export ADMIN_IDS=xxx
export GROUP_ID=xxx
export DATABASE_PATH=/data/bot.db  # или путь к папке с правами записи
python main.py
```

Для фонового запуска: `nohup python main.py &` или systemd/supervisor.

## Переменные окружения (обязательные)

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Токен от @BotFather |
| `ADMIN_IDS` | ID админов через запятую |
| `GROUP_ID` | ID группы или /setgroup |
| `DATABASE_PATH` | На сервере: `/data/bot.db` |

Полный список — в `.env.example`.
