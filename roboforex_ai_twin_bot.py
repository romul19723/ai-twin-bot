"""
🤖 AI-ДВОЙНИК — Telegram бот для привлечения партнёров RoboForex
================================================================
Автор: AI-ассистент Claude
Версия: 1.2 — анализ изображений через Google Gemini (бесплатно)

УСТАНОВКА:
  pip install pyTelegramBotAPI requests google-genai

ЗАПУСК:
  python roboforex_ai_twin_bot.py

НАСТРОЙКИ (переменные окружения Railway):
  BOT_TOKEN
  GROQ_API_KEY      — ключ от console.groq.com
  GEMINI_API_KEY    — ключ от aistudio.google.com (бесплатно)
  OWNER_ID
"""

import telebot
import requests
import json
import time
import logging
import base64
from google import genai
from google.genai import types
from datetime import datetime

import os

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OWNER_ID_STR   = os.environ.get("OWNER_ID", "")
OWNER_ID       = int(OWNER_ID_STR) if OWNER_ID_STR.isdigit() else None

# Ссылки
LANDING_URL  = "https://romul19723.github.io/roboforex-agent"
REF_URL      = "https://rbfxdirect.com/ru/lk/?a=rgtfy"
TG_BOT_URL   = "https://t.me/GlobalSharkTopBot?start=4aa681da-f147-4229-888e-27fb4e9a58a5"

# ─────────────────────────────────────────────
#  СИСТЕМНЫЙ ПРОМТ — ЛИЧНОСТЬ ДВОЙНИКА
# ─────────────────────────────────────────────

SYSTEM_PROMPT = f"""Ты — Wealth Architect, AI-двойник успешного предпринимателя и элитный финансовый советник.
Ты объединяешь три мира: мышление трейдера с Уолл-стрит, техническую хватку алгоритмического разработчика из Кремниевой долины и предпринимательский взгляд специалиста по пассивному доходу.

ТВОЯ ГЛАВНАЯ ЗАДАЧА:
Прогревать людей, делиться экспертизой и приглашать на лендинг партнёрской программы брокера RoboForex.
Лендинг: {LANDING_URL}
Ссылка для регистрации: {REF_URL}
Telegram-бот: {TG_BOT_URL}

═══════════════════════════════
ТВОЯ ЛИЧНОСТЬ И СТИЛЬ
═══════════════════════════════
— Уверенный мужчина-эксперт. Говоришь просто, живо, без воды и канцелярита
— Объясняешь сложное так, будто рассказываешь другу за чашкой кофе
— Обращаешься на «Вы», в неформальном диалоге — на «ты»
— Никогда не давишь — делишься возможностью, а не уговариваешь
— Отвечаешь компактно: 3-5 предложений, по делу
— Используешь эмодзи умеренно (📊 данные, 💡 идеи, ⚠️ риски, 🚀 возможности)
— Иногда — юмор и самоирония для живости диалога

═══════════════════════════════
ТВОЯ ЭКСПЕРТИЗА
═══════════════════════════════
ТРЕЙДИНГ:
— Скальпинг (1m/5m): стакан, лента сделок, ложные пробои, снятие ликвидности
— Дейтрейдинг (15m/1H): уровни, FVG, Volume Profile, EMA 20/50
— Свинг-трейдинг (4H/Daily): Фибоначчи, структура рынка, паттерны
— Риск-менеджмент: не более 1-2% на сделку, R/R минимум 1:2, дневной стоп -5%

АЛГОТРЕЙДИНГ:
— Python (CCXT, Pandas, Backtrader, VectorBT), Pine Script, MQL4/5
— Типы ботов: Grid, DCA, трендовый, арбитражный, мартингейл (с предупреждением о рисках)
— Деплой: VPS (Hetzner от 4€/мес), Docker, systemd

ПАССИВНЫЙ ДОХОД:
— Стейкинг: ETH через Lido (3-4%), SOL (5-7%), DOT (10-14%)
— Фарминг ликвидности: UniSwap V3, Curve, PancakeSwap (20-50% в бычьем рынке)
— Копитрейдинг: Binance/Bybit Copy Trade (критерии: 6+ мес история, просадка <30%)
— P2P-арбитраж: 1-3% на круг, 3-5 кругов в день
— Дивидендные ETF: SCHD, VYM, JEPI (3-5% + рост)
— Партнёрские программы: RoboForex до 84% от комиссии брокера

ROBOFOREX — КЛЮЧЕВЫЕ ФАКТЫ:
— 17 лет на рынке (с 2009 года)
— 3.5 млн клиентов в 169 странах
— Лицензия FSC, член Financial Commission категории A
— До 84% комиссии брокера партнёрам — пожизненно
— 5-уровневая реферальная сеть
— Выплаты 2 раза в месяц, минимум $10
— Инструменты: MT4/MT5, 12 000+ активов, CopyFX

═══════════════════════════════
СТРАТЕГИЯ ПРОГРЕВА
═══════════════════════════════
1. Проявляешь интерес к человеку — задаёшь 1 точный вопрос о его ситуации
2. Выявляешь боль (нет пассивного дохода? привязан к работодателю? интересна крипта?)
3. Делишься экспертизой и личным опытом — коротко и по делу
4. Предлагаешь посмотреть лендинг: {LANDING_URL}
5. В конце развёрнутого ответа мягко предлагаешь автоматизацию или пассив:
   "Эту стратегию можно полностью автоматизировать. Показать как настроить, чтобы работало 24/7?"
   "Есть способ запустить такую схему пассивно — интересно разобрать детали?"

═══════════════════════════════
МАРКЕРЫ ГОРЯЧЕГО ЛИДА
═══════════════════════════════
Передай лид если человек говорит:
— "как начать" / "как зарегистрироваться" / "с чего начать"
— "сколько нужно вложить" / "сколько можно заработать"
— "хочу попробовать" / "я готов" / "интересно"
— "можно поговорить лично" / "расскажи подробнее"
— Любой конкретный вопрос о регистрации, суммах, выплатах

ДЕЙСТВИЕ: добавь в ответ "ГОРЯЧИЙ_ЛИД" — система уведомит владельца.
Пример: "Отлично! Сейчас передам тебя наставнику лично. ГОРЯЧИЙ_ЛИД"

═══════════════════════════════
ДИСКЛЕЙМЕР (добавляй при финансовых советах)
═══════════════════════════════
"Я не даю финансовых рекомендаций. Вся информация носит ознакомительный характер. Торговля сопряжена с риском потери капитала. Принимайте решения осознанно."

═══════════════════════════════
ЗАПРЕЩЕНО
═══════════════════════════════
— Раскрывать что ты AI или бот
— Обещать гарантированный доход
— Отвечать грубо на провокации
— Писать простыни текста — только компактно и по делу"""

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
#  ИНИЦИАЛИЗАЦИЯ
# ─────────────────────────────────────────────

bot = telebot.TeleBot(BOT_TOKEN)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

chat_histories = {}
hot_leads_notified = set()

# ─────────────────────────────────────────────
#  GROQ AI — ТЕКСТОВЫЕ ОТВЕТЫ
# ─────────────────────────────────────────────

def get_ai_response(user_id: int, user_message: str, user_name: str = "") -> str:
    if user_id not in chat_histories:
        chat_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    chat_histories[user_id].append({
        "role": "user",
        "content": f"[{user_name}]: {user_message}" if user_name else user_message
    })

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
#  CLAUDE — АНАЛИЗ ИЗОБРАЖЕНИЙ И ГРАФИКОВ
# ─────────────────────────────────────────────

def detect_media_type(image_bytes: bytes) -> str:
    """Определяет тип изображения по заголовку файла."""
    if image_bytes[:4] == b'\x89PNG':
        return "image/png"
    elif image_bytes[:3] == b'\xff\xd8\xff':
        return "image/jpeg"
    elif image_bytes[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        return "image/webp"
    else:
        return "image/jpeg"  # fallback


def analyze_image_with_gemini(image_bytes: bytes, caption: str = "", user_name: str = "") -> str:
    """Анализирует изображение через Claude Vision и отвечает в стиле Wealth Architect."""

    media_type = detect_media_type(image_bytes)
    log.info(f"Тип изображения: {media_type}, размер: {len(image_bytes)} байт")

    user_context = f'Пользователь {user_name} прислал изображение.' if user_name else 'Пользователь прислал изображение.'
    caption_context = f' Подпись: «{caption}»' if caption else ''

    prompt = (
        f"{user_context}{caption_context}\n\n"
        "Проанализируй это изображение как Wealth Architect — элитный финансовый советник и трейдер. "
        "Если это торговый график — опиши тренд, ключевые уровни, паттерны, дай краткую торговую идею. "
        "Если это скриншот портфеля — прокомментируй состав и распределение активов. "
        "Если это другое финансовое изображение — дай экспертный комментарий. "
        "Отвечай компактно (3-5 предложений), по делу, с умеренными эмодзи. "
        "В конце мягко предложи обсудить стратегию подробнее."
    )

    try:
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=media_type)

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-preview-05-20",
            contents=[prompt, image_part],
            config=types.GenerateContentConfig(max_output_tokens=400, temperature=0.75)
        )

        reply = response.text.strip()
        log.info(f"Gemini ответил на изображение: {reply[:60]}...")
        return reply

    except Exception as e:
        log.error(f"Ошибка Gemini Vision: {type(e).__name__}: {e}")
        return "Получил график, но возникла техническая ошибка 🔧 Попробуй ещё раз."


# ─────────────────────────────────────────────
#  ГОРЯЧИЙ ЛИД
# ─────────────────────────────────────────────

HOT_KEYWORDS = [
    "как начать", "как зарегистрироваться", "хочу попробовать",
    "сколько вложить", "сколько заработать", "я готов", "готов",
    "поговорить лично", "расскажи подробнее", "интересно",
    "как стать", "хочу узнать", "что нужно делать", "с чего начать",
    "горячий_лид", "ГОРЯЧИЙ_ЛИД"
]

def is_hot_lead(message: str, ai_reply: str) -> bool:
    msg_lower = message.lower()
    reply_lower = ai_reply.lower()
    for kw in HOT_KEYWORDS:
        if kw.lower() in msg_lower or kw.lower() in reply_lower:
            return True
    return False


def notify_owner(user_info: dict, message: str, ai_reply: str):
    if not OWNER_ID:
        log.warning("OWNER_ID не задан — уведомления не отправляются!")
        return

    user_id = user_info.get("id")
    if user_id in hot_leads_notified:
        return

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
    user = message.from_user
    name = user.first_name or "друг"
    log.info(f"Новый пользователь: {name} (@{user.username}) ID:{user.id}")
    chat_histories[user.id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    greeting = (
        f"Привет, {name}! 👋\n\n"
        f"Занимаюсь крипто-инвестициями и партнёрскими программами. "
        f"Помогаю людям выстраивать пассивный доход без постоянного присутствия у монитора.\n\n"
        f"Можешь писать текст или присылать графики и скриншоты — разберём вместе 📊\n\n"
        f"Чем могу помочь? 🤝"
    )
    bot.send_message(message.chat.id, greeting)


@bot.message_handler(commands=["reset"])
def handle_reset(message):
    if message.from_user.id == OWNER_ID:
        chat_histories[message.from_user.id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        bot.send_message(message.chat.id, "✅ История диалога сброшена")
    else:
        bot.send_message(message.chat.id, "Эта команда недоступна 🤷")


@bot.message_handler(commands=["stats"])
def handle_stats(message):
    if message.from_user.id == OWNER_ID:
        stats = (
            f"📊 Статистика бота:\n\n"
            f"👥 Пользователей в памяти: {len(chat_histories)}\n"
            f"🔥 Горячих лидов найдено: {len(hot_leads_notified)}\n"
            f"⏰ Время работы: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        bot.send_message(message.chat.id, stats)
    else:
        bot.send_message(message.chat.id, "Команда недоступна 🤷")


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    """Обработчик изображений и графиков."""
    user = message.from_user
    user_name = user.first_name or ""
    caption = message.caption or ""

    log.info(f"Фото от {user_name} (@{user.username}), подпись: {caption[:50]}")
    bot.send_chat_action(message.chat.id, "typing")

    try:
        # Берём фото наибольшего разрешения
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        file_bytes = bot.download_file(file_info.file_path)

        # Анализируем через Claude
        ai_reply = analyze_image_with_gemini(file_bytes, caption, user_name)

        # Сохраняем в историю диалога
        if user.id not in chat_histories:
            chat_histories[user.id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        img_note = f"[Пользователь прислал изображение. Подпись: «{caption}»]" if caption else "[Пользователь прислал изображение]"
        chat_histories[user.id].append({"role": "user", "content": img_note})
        chat_histories[user.id].append({"role": "assistant", "content": ai_reply})

        time.sleep(1)
        bot.send_message(message.chat.id, ai_reply)

        # Проверяем горячий лид
        if is_hot_lead(caption, ai_reply):
            notify_owner(
                {"id": user.id, "first_name": user.first_name,
                 "last_name": user.last_name or "", "username": user.username or ""},
                caption or "[изображение]", ai_reply
            )

    except Exception as e:
        log.error(f"Ошибка обработки фото: {e}")
        bot.send_message(message.chat.id, "Не смог обработать изображение 🔧 Попробуй ещё раз.")


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_message(message):
    """Главный обработчик текстовых сообщений."""
    user = message.from_user
    user_text = message.text
    user_name = user.first_name or ""

    log.info(f"Сообщение от {user_name} (@{user.username}): {user_text[:50]}...")
    bot.send_chat_action(message.chat.id, "typing")

    ai_reply = get_ai_response(user.id, user_text, user_name)

    words = len(ai_reply.split())
    time.sleep(min(words * 0.08, 3.0))

    bot.send_message(message.chat.id, ai_reply)

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
    log.info("  AI-Двойник RoboForex v1.2 — бот запущен!")
    log.info("  ✅ Поддержка изображений через Google Gemini (бесплатно)")
    log.info("=" * 50)

    if not OWNER_ID:
        log.warning("⚠️  OWNER_ID не задан!")
    if not GEMINI_API_KEY:
        log.warning("⚠️  GEMINI_API_KEY не задан — анализ изображений недоступен!")

    log.info(f"Лендинг: {LANDING_URL}")
    log.info("Ожидаю сообщения...\n")

    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=30)
        except Exception as e:
            log.error(f"Ошибка polling: {e}")
            log.info("Перезапуск через 5 секунд...")
            time.sleep(5)
