# 🤖 AlgoRobi — Trading Signal Bot

**OKX + Bybit | Claude AI | 10-шаговый Chain of Thought**

---

## ⚡ Быстрый старт (5 минут)

### 1. Установи Python-зависимости
```bash
pip install python-telegram-bot anthropic requests
```

### 2. Получи токены

**Telegram Bot Token:**
1. Открой Telegram → найди `@BotFather`
2. Напиши `/newbot`
3. Придумай имя: `AlgoRobi` и username: `AlgoRobiBot`
4. Скопируй токен вида `1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ`

**Anthropic API Key:**
1. Зайди на [console.anthropic.com](https://console.anthropic.com)
2. API Keys → Create Key
3. Скопируй ключ вида `sk-ant-api03-...`

### 3. Вставь токены в файл
Открой `algorobi_bot.py` и замени в начале файла:
```python
TELEGRAM_TOKEN    = "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ"  # ← сюда
ANTHROPIC_API_KEY = "sk-ant-api03-..."                         # ← и сюда
DEPOSIT_USDT      = 1000   # твой депозит
RISK_PERCENT      = 1.0    # риск на сделку %
```

### 4. Запусти
```bash
python algorobi_bot.py
```

### 5. Открой Telegram → найди своего бота → `/start`

---

## 📋 Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и список команд |
| `/signal` | Сигнал по BTC (10-шаговый CoT) |
| `/signal ETH` | Сигнал по ETH |
| `/signal SOL` | Сигнал по SOL |
| `/signal XRP` | Сигнал по XRP |
| `/signal DOGE` | Сигнал по DOGE |
| `/compare` | Сравнение OKX vs Bybit (BTC) |
| `/compare ETH` | Сравнение по ETH |
| `/scan` | Сканировать все 6 пар |
| `/status` | Цены и FR всех пар |
| `/help` | Подробная справка |
| любой текст | Свободный чат с AI |

---

## 🧠 Как работает алгоритм

### Технический анализ (авто-скан)
1. **Пин-бар:** нижний/верхний wick > 2×body И wick > 60% range
2. **Объём:** текущий объём > средний (20 свечей) × 1.3
3. **Стоп-лосс:** ATR_14 × 1.5
4. **Ликвидация:** вход ± вход/плечо (стоп должен быть на 0.5% ближе)
5. **Позиция:** Риск$ / (Стоп% / 100)
6. **Фильтр:** R/R ≥ 1.5 и позиция ≥ 20 USDT

### AI Chain of Thought (команды /signal и /compare)
Claude выполняет 10 шагов:
- Шаг 1: Данные обеих бирж
- Шаг 2: Анализ Funding Rate
- Шаг 3: Long/Short Ratio
- Шаг 4: Технический вход (пин-бар + объём)
- Шаг 5: Стоп по ATR
- Шаг 6: Ликвидация и подбор плеча
- Шаг 7: Стоп в процентах
- Шаг 8: Выбор биржи (взвешенный score)
- Шаг 9: Расчёт размера позиции с комиссиями
- Шаг 10: TP1/TP2/TP3 и проверка R/R

---

## ⚙️ Настройки

```python
DEPOSIT_USDT     = 1000   # твой депозит в USDT
RISK_PERCENT     = 1.0    # риск на сделку (1% от депозита)
AUTO_SCAN_HOURS  = 1      # авто-скан каждые N часов (0 = выкл)
TF               = "15m"  # таймфрейм (5m, 15m, 1h, 4h)
CANDLE_LIMIT     = 50     # количество свечей для анализа
```

---

## 📦 Структура файла

```
algorobi_bot.py
├── Конфигурация (TELEGRAM_TOKEN, ANTHROPIC_API_KEY, ...)
├── API (fetch_okx, fetch_bybit)
├── Торговая логика (calc_atr, detect_pin_bar, analyze_pair)
├── AI промты (ai_cot_signal, ai_compare)
├── Форматтеры сообщений
├── Обработчики команд (cmd_signal, cmd_compare, cmd_scan, cmd_status)
└── Запуск (main)
```

---

## 🚀 Запуск на сервере (24/7)

### Вариант 1: systemd (Linux)
```bash
sudo nano /etc/systemd/system/algorobi.service
```
```ini
[Unit]
Description=AlgoRobi Trading Bot
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/algorobi_bot.py
Restart=always
User=your_user

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable algorobi
sudo systemctl start algorobi
```

### Вариант 2: screen
```bash
screen -S algorobi
python algorobi_bot.py
# Ctrl+A, D — свернуть
# screen -r algorobi — вернуться
```

### Вариант 3: nohup
```bash
nohup python algorobi_bot.py > algorobi.log 2>&1 &
```

---

## ⚠️ Важно

- Бот **не торгует автоматически** — только даёт сигналы
- Не является финансовой рекомендацией
- Торговля с плечом несёт высокий риск потери средств
- Всегда проверяй сигнал вручную перед входом в позицию
