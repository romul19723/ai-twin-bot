"""
🤖 AI-ДВОЙНИК — Telegram бот для привлечения партнёров RoboForex
================================================================
Автор: AI-ассистент Claude
Версия: 1.0

УСТАНОВКА:
  pip install pyTelegramBotAPI requests

ЗАПУСК:
  python roboforex_ai_twin_bot.py

НАСТРОЙКИ — измени ниже:
  BOT_TOKEN     — токен твоего бота от @BotFather
  GROQ_API_KEY  — ключ от console.groq.com (бесплатно)
  OWNER_ID      — твой Telegram ID (узнай у @userinfobot)
"""

import telebot
import requests
import json
import time
import logging
from datetime import datetime

# ─────────────────────────────────────────────
#  НАСТРОЙКИ — ЗАПОЛНИ ЗДЕСЬ
# ─────────────────────────────────────────────

BOT_TOKEN    = "8956666468:AAFdlYAJhAvSByheiAzEXQkHc00TdO_n5tc"
GROQ_API_KEY = "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"
OWNER_ID     = None  # ← ВСТАВЬ СВОЙ TELEGRAM ID (узнай у @userinfobot)

# Ссылки
LANDING_URL  = "https://romul19723.github.io/roboforex-agent"
REF_URL      = "https://rbfxdirect.com/ru/lk/?a=rgtfy"
TG_BOT_URL   = "https://t.me/GlobalSharkTopBot?start=4aa681da-f147-4229-888e-27fb4e9a58a5"

# ─────────────────────────────────────────────
#  СИСТЕМНЫЙ ПРОМТ — ЛИЧНОСТЬ ДВОЙНИКА
# ─────────────────────────────────────────────

SYSTEM_PROMPT = f"""Ты — AI-двойник успешного предпринимателя в сфере финансов, крипто-инвестиций и сетевого маркетинга.
Ты общаешься в Telegram от его имени: уверенно, экспертно, по-мужски.

ТВОЯ ЗАДАЧА:
Прогревать людей и приглашать их на лендинг партнёрской программы брокера RoboForex.
Лендинг: {LANDING_URL}
Ссылка для регистрации: {REF_URL}

ТВОЯ ЛИЧНОСТЬ:
— Уверенный мужчина, эксперт в крипто, трейдинге, пассивном доходе и партнёрских программах
— Говоришь чётко и по делу, без воды и пафоса
— Делишься личным опытом и реальными результатами
— Никогда не давишь — ты делишься возможностью, а не уговариваешь
— Отвечаешь коротко: 2-4 предложения максимум
— Используешь эмодзи умеренно — 1-2 на сообщение
— Иногда используешь юмор и самоиронию

ТВОЯ ЭКСПЕРТИЗА:
— Крипто и фьючерсная торговля (BTC, ETH, альткоины)
— Пассивный доход: копитрейдинг, аирдропы, партнёрские программы
— Сетевой маркетинг и построение команд
— RoboForex: 17 лет на рынке, 3.5 млн клиентов, до 84% комиссии, лицензия FSC

КАК ПРОГРЕВАТЬ:
1. Сначала проявляешь интерес к человеку, задаёшь 1 вопрос
2. Выявляешь его ситуацию (хочет доп. доход? ищет пассив? интересна крипта?)
3. Делишься своим опытом с RoboForex — коротко и по делу
4. Предлагаешь посмотреть лендинг: {LANDING_URL}
5. Если человек заинтересован — передаёшь наставнику

МАРКЕРЫ ГОРЯЧЕГО ЛИДА:
Если человек говорит одно из следующего — это горячий лид:
— "как начать" / "как зарегистрироваться"
— "сколько нужно вложить" / "сколько можно заработать"
— "хочу попробовать" / "я готов"
— "можно поговорить лично" / "расскажи подробнее"
— Любой конкретный вопрос о регистрации или деньгах

ДЕЙСТВИЕ при горячем лиде:
Напиши в ответ фразу содержащую: "ГОРЯЧИЙ_ЛИД" — это сигнал системе передать контакт владельцу.
Пример: "Отлично! Сейчас передам тебя моему наставнику. ГОРЯЧИЙ_ЛИД"

ЗАПРЕЩЕНО:
— Раскрывать что ты AI или бот
— Обещать гарантированный доход
— Давать конкретные инвестиционные советы
— Отвечать грубо на провокации
— Писать длинные монологи — только коротко и конкретно"""

# ─────────────────────────────────────────────
#  ЛОГИРОВАНИЕ
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("AITwin")

# ─────────────────────────────────────────────
#  ИНИЦИАЛИЗАЦИЯ БОТА
# ─────────────────────────────────────────────

bot = telebot.TeleBot(BOT_TOKEN)

# Хранение истории диалогов (в памяти)
chat_histories = {}
hot_leads_notified = set()

# ─────────────────────────────────────────────
#  GROQ AI — ПОЛУЧЕНИЕ ОТВЕТА
# ─────────────────────────────────────────────

def get_ai_response(user_id: int, user_message: str, user_name: str = "") -> str:
    """Получает ответ от Groq AI с учётом истории диалога."""

    # Инициализируем историю если нет
    if user_id not in chat_histories:
        chat_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Добавляем сообщение пользователя
    chat_histories[user_id].append({
        "role": "user",
        "content": f"[{user_name}]: {user_message}" if user_name else user_message
    })

    # Ограничиваем историю до 20 сообщений (экономия токенов)
    if len(chat_histories[user_id]) > 21:
        system_msg = chat_histories[user_id][0]
        chat_histories[user_id] = [system_msg] + chat_histories[user_id][-20:]

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": chat_histories[user_id],
                "max_tokens": 300,
                "temperature": 0.75
            },
            timeout=30
        )

        data = response.json()

        if "choices" in data and data["choices"]:
            reply = data["choices"][0]["message"]["content"].strip()
            # Сохраняем ответ в историю
            chat_histories[user_id].append({"role": "assistant", "content": reply})
            return reply
        else:
            log.error(f"Groq ошибка: {data}")
            return "Секунду, обработаю твой вопрос... Напиши ещё раз 🙏"

    except requests.Timeout:
        return "Задержка связи — напиши ещё раз 👌"
    except Exception as e:
        log.error(f"Ошибка AI: {e}")
        return "Технический сбой, попробуй через минуту 🔧"


# ─────────────────────────────────────────────
#  ОПРЕДЕЛЕНИЕ ГОРЯЧЕГО ЛИДА
# ─────────────────────────────────────────────

HOT_KEYWORDS = [
    "как начать", "как зарегистрироваться", "хочу попробовать",
    "сколько вложить", "сколько заработать", "я готов", "готов",
    "поговорить лично", "расскажи подробнее", "интересно",
    "как стать", "хочу узнать", "что нужно делать", "с чего начать",
    "горячий_лид", "ГОРЯЧИЙ_ЛИД"
]

def is_hot_lead(message: str, ai_reply: str) -> bool:
    """Проверяет является ли диалог горячим лидом."""
    msg_lower = message.lower()
    reply_lower = ai_reply.lower()

    # Проверяем ключевые слова в сообщении пользователя
    for kw in HOT_KEYWORDS:
        if kw.lower() in msg_lower or kw.lower() in reply_lower:
            return True
    return False


def notify_owner(user_info: dict, message: str, ai_reply: str):
    """Уведомляет владельца о горячем лиде."""
    if not OWNER_ID:
        log.warning("OWNER_ID не задан — уведомления не отправляются!")
        return

    user_id = user_info.get("id")
    if user_id in hot_leads_notified:
        return  # Уже уведомляли об этом лиде

    hot_leads_notified.add(user_id)

    first_name = user_info.get("first_name", "")
    last_name  = user_info.get("last_name", "")
    username   = user_info.get("username", "нет username")
    name       = f"{first_name} {last_name}".strip()

    notify_text = (
        f"🔥 ГОРЯЧИЙ ЛИД!\n\n"
        f"👤 Имя: {name}\n"
        f"📱 Username: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"💬 Написал: «{message[:200]}»\n\n"
        f"📲 Напиши ему: tg://user?id={user_id}\n\n"
        f"✅ Человек готов к разговору — звони!"
    )

    try:
        bot.send_message(OWNER_ID, notify_text)
        log.info(f"🔥 Владелец уведомлён о лиде: {name} @{username}")
    except Exception as e:
        log.error(f"Ошибка отправки уведомления: {e}")


# ─────────────────────────────────────────────
#  ОБРАБОТЧИКИ СООБЩЕНИЙ
# ─────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def handle_start(message):
    """Обработка команды /start."""
    user = message.from_user
    name = user.first_name or "друг"

    log.info(f"Новый пользователь: {name} (@{user.username}) ID:{user.id}")

    # Инициализируем историю
    chat_histories[user.id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    greeting = (
        f"Привет, {name}! 👋\n\n"
        f"Занимаюсь крипто-инвестициями и партнёрскими программами. "
        f"Помогаю людям выстраивать пассивный доход без постоянного присутствия у монитора.\n\n"
        f"Чем могу помочь? 🤝"
    )

    bot.send_message(message.chat.id, greeting)


@bot.message_handler(commands=["reset"])
def handle_reset(message):
    """Сброс истории диалога."""
    if message.from_user.id == OWNER_ID:
        target_id = message.from_user.id
        if target_id in chat_histories:
            chat_histories[target_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        bot.send_message(message.chat.id, "✅ История диалога сброшена")
    else:
        bot.send_message(message.chat.id, "Эта команда недоступна 🤷")


@bot.message_handler(commands=["stats"])
def handle_stats(message):
    """Статистика для владельца."""
    if message.from_user.id == OWNER_ID:
        total_users = len(chat_histories)
        total_leads = len(hot_leads_notified)
        stats = (
            f"📊 Статистика бота:\n\n"
            f"👥 Пользователей в памяти: {total_users}\n"
            f"🔥 Горячих лидов найдено: {total_leads}\n"
            f"⏰ Время работы: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        bot.send_message(message.chat.id, stats)
    else:
        bot.send_message(message.chat.id, "Команда недоступна 🤷")


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_message(message):
    """Главный обработчик всех текстовых сообщений."""
    user = message.from_user
    user_text = message.text
    user_name = user.first_name or ""

    log.info(f"Сообщение от {user_name} (@{user.username}): {user_text[:50]}...")

    # Показываем что бот печатает
    bot.send_chat_action(message.chat.id, "typing")

    # Получаем ответ от AI
    ai_reply = get_ai_response(user.id, user_text, user_name)

    # Небольшая пауза для реалистичности (имитация набора текста)
    words = len(ai_reply.split())
    typing_delay = min(words * 0.08, 3.0)  # Макс 3 секунды
    time.sleep(typing_delay)

    # Отправляем ответ
    bot.send_message(message.chat.id, ai_reply)

    # Проверяем горячий лид
    if is_hot_lead(user_text, ai_reply):
        notify_owner(
            {"id": user.id, "first_name": user.first_name,
             "last_name": user.last_name or "", "username": user.username or ""},
            user_text, ai_reply
        )

    log.info(f"Ответ отправлен: {ai_reply[:60]}...")


# ─────────────────────────────────────────────
#  ЗАПУСК
# ─────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("  AI-Двойник RoboForex — бот запущен!")
    log.info("=" * 50)

    if not OWNER_ID:
        log.warning("⚠️  OWNER_ID не задан! Узнай свой ID у @userinfobot и вставь в настройки.")

    log.info(f"Бот: {BOT_TOKEN[:20]}...")
    log.info(f"Лендинг: {LANDING_URL}")
    log.info("Ожидаю сообщения...\n")

    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=30)
        except Exception as e:
            log.error(f"Ошибка polling: {e}")
            log.info("Перезапуск через 5 секунд...")
            time.sleep(5)
