#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════╗
║         🤖 AlgoRobi — Trading Signal Bot         ║
║         OKX + Bybit | CoT | Anthropic AI         ║
╚══════════════════════════════════════════════════╝

УСТАНОВКА:
  pip install requests python-telegram-bot anthropic

ЗАПУСК:
  python algorobi_bot.py

КОМАНДЫ:
  /start     — приветствие и список команд
  /signal    — AI-сигнал по BTC (10-шаговый CoT)
  /signal BTCUSDT  — сигнал по любой паре
  /compare   — сравнение OKX vs Bybit
  /scan      — сканировать все пары
  /status    — статус бота и рынка
  /help      — справка
"""

import os
import time
import json
import logging
import requests
from datetime import datetime
from typing import Optional

# ─── УСТАНОВКА ЗАВИСИМОСТЕЙ ───────────────────────────────────────────────────
try:
    from telegram import Update, BotCommand
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.constants import ParseMode
except ImportError:
    print("❌ Установи зависимости: pip install python-telegram-bot")
    exit(1)

try:
    import anthropic
except ImportError:
    print("❌ Установи: pip install anthropic")
    exit(1)

# ══════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ — ЗАПОЛНИ ПЕРЕД ЗАПУСКОМ
# ══════════════════════════════════════════════════
TELEGRAM_TOKEN   = "YOUR_BOT_TOKEN"        # от @BotFather
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_KEY"   # от console.anthropic.com
DEPOSIT_USDT     = 1000                    # твой депозит
RISK_PERCENT     = 1.0                     # риск на сделку %
AUTO_SCAN_HOURS  = 1                       # авто-скан каждые N часов (0 = выкл)

PAIRS = {
    "BTC":  {"okx": "BTC-USDT-SWAP",  "bybit": "BTCUSDT",  "label": "BTC/USDT"},
    "ETH":  {"okx": "ETH-USDT-SWAP",  "bybit": "ETHUSDT",  "label": "ETH/USDT"},
    "SOL":  {"okx": "SOL-USDT-SWAP",  "bybit": "SOLUSDT",  "label": "SOL/USDT"},
    "XRP":  {"okx": "XRP-USDT-SWAP",  "bybit": "XRPUSDT",  "label": "XRP/USDT"},
    "DOGE": {"okx": "DOGE-USDT-SWAP", "bybit": "DOGEUSDT", "label": "DOGE/USDT"},
    "ADA":  {"okx": "ADA-USDT-SWAP",  "bybit": "ADAUSDT",  "label": "ADA/USDT"},
}
DEFAULT_PAIR = "BTC"
TF = "15m"
CANDLE_LIMIT = 50

# ══════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("AlgoRobi")

# ─── MARKET DATA ──────────────────────────────────────────────────────────────
def okx_get(path: str) -> dict:
    url = f"https://www.okx.com/api/v5{path}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()

def bybit_get(path: str) -> dict:
    url = f"https://api.bybit.com/v5{path}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()

def fetch_okx(pair: dict) -> dict:
    sym = pair["okx"]
    tf_map = {"5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H"}
    bar = tf_map.get(TF, "15m")
    try:
        fr   = okx_get(f"/public/funding-rate?instId={sym}")
        ob   = okx_get(f"/market/books?instId={sym}&sz=20")
        cnd  = okx_get(f"/market/candles?instId={sym}&bar={bar}&limit={CANDLE_LIMIT}")
        tick = okx_get(f"/market/ticker?instId={sym}")
        oi   = okx_get(f"/market/open-interest?instId={sym}")

        bids = ob.get("data", [{}])[0].get("bids", [[0]])
        asks = ob.get("data", [{}])[0].get("asks", [[0]])
        bid = float(bids[0][0]) if bids else 0
        ask = float(asks[0][0]) if asks else 0
        spread = (ask - bid) / bid * 100 if bid else 0
        candles = cnd.get("data", [])
        price = float(tick.get("data", [{}])[0].get("last", 0))

        return {
            "exchange": "OKX", "ok": True,
            "funding_rate": fr.get("data", [{}])[0].get("fundingRate", "N/A"),
            "price": price, "bid": bid, "ask": ask, "spread": spread,
            "open_interest": oi.get("data", [{}])[0].get("oi", "N/A"),
            "volume24h": float(tick.get("data", [{}])[0].get("vol24h", 0)),
            "change24h": float(tick.get("data", [{}])[0].get("changeUtc0", 0)),
            "candles": candles,
            "maker_fee": -0.02, "taker_fee": 0.05,
        }
    except Exception as e:
        log.error(f"OKX error: {e}")
        return {"exchange": "OKX", "ok": False, "error": str(e)}

def fetch_bybit(pair: dict) -> dict:
    sym = pair["bybit"]
    iv = TF.replace("m", "")
    try:
        tick = bybit_get(f"/market/tickers?category=linear&symbol={sym}")
        ob   = bybit_get(f"/market/orderbook?category=linear&symbol={sym}&limit=20")
        kl   = bybit_get(f"/market/kline?category=linear&symbol={sym}&interval={iv}&limit={CANDLE_LIMIT}")
        oi   = bybit_get(f"/market/open-interest?category=linear&symbol={sym}&intervalTime=5min&limit=1")

        td = tick.get("result", {}).get("list", [{}])[0]
        obr = ob.get("result", {})
        bid = float(obr.get("b", [[0]])[0][0]) if obr.get("b") else 0
        ask = float(obr.get("a", [[0]])[0][0]) if obr.get("a") else 0
        spread = (ask - bid) / bid * 100 if bid else 0
        candles = kl.get("result", {}).get("list", [])

        return {
            "exchange": "Bybit", "ok": True,
            "funding_rate": td.get("fundingRate", "N/A"),
            "price": float(td.get("lastPrice", 0)),
            "bid": bid, "ask": ask, "spread": spread,
            "open_interest": oi.get("result", {}).get("list", [{}])[0].get("openInterest", "N/A"),
            "volume24h": float(td.get("volume24h", 0)),
            "change24h": float(td.get("price24hPcnt", 0)) * 100,
            "candles": candles,
            "maker_fee": -0.01, "taker_fee": 0.06,
        }
    except Exception as e:
        log.error(f"Bybit error: {e}")
        return {"exchange": "Bybit", "ok": False, "error": str(e)}

# ─── TRADING LOGIC ────────────────────────────────────────────────────────────
def calc_atr(candles: list, period: int = 14) -> float:
    if not candles or len(candles) < period:
        return 0.0
    trs = []
    for i in range(1, min(len(candles), period + 1)):
        try:
            h = float(candles[i][2])
            l = float(candles[i][3])
            pc = float(candles[i-1][4])
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        except:
            continue
    return sum(trs) / len(trs) if trs else 0.0

def detect_pin_bar(candles: list, vol_thresh: float = 0.3):
    if not candles or len(candles) < 20:
        return None
    c = candles[0]
    try:
        high = float(c[2]); low = float(c[3])
        opn  = float(c[1]); close = float(c[4])
        vol  = float(c[5])
    except:
        return None

    avg_vol = sum(float(x[5]) for x in candles[1:21] if len(x) > 5) / 20
    vol_spike = vol > avg_vol * (1 + vol_thresh)
    body = abs(close - opn)
    lower_wick = min(opn, close) - low
    upper_wick = high - max(opn, close)
    rng = high - low
    if rng == 0:
        return None

    is_long  = lower_wick > body * 2 and lower_wick > rng * 0.6
    is_short = upper_wick > body * 2 and upper_wick > rng * 0.6

    if is_long and vol_spike:
        return {"dir": "LONG",  "entry": low,  "vol_ratio": round(vol/avg_vol, 2)}
    if is_short and vol_spike:
        return {"dir": "SHORT", "entry": high, "vol_ratio": round(vol/avg_vol, 2)}
    return None

def analyze_pair(okx: dict, bybit: dict, deposit: float, risk_pct: float) -> dict:
    risk_usdt = deposit * risk_pct / 100
    results = {}

    for d, name in [(okx, "okx"), (bybit, "bybit")]:
        if not d.get("ok") or not d.get("candles"):
            results[name] = {"score": 0}
            continue

        pb = detect_pin_bar(d["candles"])
        if not pb:
            results[name] = {"score": 0}
            continue

        atr = calc_atr(d["candles"])
        if not atr:
            results[name] = {"score": 0}
            continue

        entry = pb["entry"]
        direction = pb["dir"]

        if direction == "LONG":
            stop = entry - atr * 1.5
            sl_pct = (entry - stop) / entry * 100
            tp1 = entry * (1 + sl_pct * 1.5 / 100)
            tp2 = entry * (1 + sl_pct * 3.0 / 100)
            tp3 = entry * (1 + sl_pct * 5.0 / 100)
        else:
            stop = entry + atr * 1.5
            sl_pct = (stop - entry) / entry * 100
            tp1 = entry * (1 - sl_pct * 1.5 / 100)
            tp2 = entry * (1 - sl_pct * 3.0 / 100)
            tp3 = entry * (1 - sl_pct * 5.0 / 100)

        lev = 5 if d.get("spread", 1) < 0.05 else 3
        liq = (entry - entry / lev) if direction == "LONG" else (entry + entry / lev)

        pos_size = risk_usdt / (sl_pct / 100) if sl_pct > 0 else 0
        margin   = pos_size / lev

        fr  = float(d.get("funding_rate", 0)) if d.get("funding_rate") != "N/A" else 0
        taker = d.get("taker_fee", 0.06)
        rr = round((sl_pct * 1.5 - taker) / (sl_pct + taker), 2) if sl_pct > 0 else 0

        score = 0
        if rr >= 1.5:           score += 50
        if abs(fr) > 0.0005:    score += 20
        else:                    score += 10
        if d.get("spread", 1) < 0.02:   score += 20
        elif d.get("spread", 1) < 0.05: score += 10
        if pos_size >= 20:      score += 10

        prec = 6 if entry < 1 else (4 if entry < 10 else (2 if entry < 1000 else 0))
        fmt = lambda x: round(x, prec)

        results[name] = {
            "score": score,
            "dir": direction,
            "entry": fmt(entry),
            "stop":  fmt(stop),
            "liq":   fmt(liq),
            "tps":   [fmt(tp1), fmt(tp2), fmt(tp3)],
            "sl_pct": round(sl_pct, 3),
            "rr":    rr,
            "fr":    fr,
            "spread": round(d.get("spread", 0), 4),
            "leverage": lev,
            "pos_size": round(pos_size, 2),
            "margin":   round(margin, 2),
            "risk_usdt": round(risk_usdt, 2),
            "vol_ratio": pb.get("vol_ratio", 0),
            "atr": round(atr, prec),
        }

    okx_s  = results.get("okx",  {}).get("score", 0)
    byb_s  = results.get("bybit",{}).get("score", 0)
    has_sig = okx_s > 0 or byb_s > 0
    winner  = ("OKX" if okx_s >= byb_s else "Bybit") if has_sig else None
    return {"results": results, "winner": winner, "has_signal": has_sig}

# ─── MARKET SUMMARY FOR AI ────────────────────────────────────────────────────
def build_market_block(okx: dict, bybit: dict, pair_label: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    def fmt(d):
        if not d.get("ok"):
            return f"=== {d.get('exchange','?')} ===\nОШИБКА: {d.get('error','unknown')}"
        fr = d.get("funding_rate", "N/A")
        try:
            fr_pct = f"{float(fr)*100:.4f}%"
        except:
            fr_pct = str(fr)
        last = d.get("candles", [[]])[0] if d.get("candles") else []
        return (
            f"=== {d['exchange']} ===\n"
            f"Цена: ${d.get('price',0):,.4f} | Изм.24ч: {d.get('change24h',0):.2f}%\n"
            f"Funding Rate: {fr_pct} | Спред: {d.get('spread',0):.4f}%\n"
            f"Bid: ${d.get('bid',0):,.4f} | Ask: ${d.get('ask',0):,.4f}\n"
            f"Open Interest: {d.get('open_interest','N/A')} | Объём 24ч: {d.get('volume24h',0):,.0f}\n"
            f"Свечей ({TF}): {len(d.get('candles',[]))} | Посл. свеча: {last}\n"
            f"Комиссии: мейкер {d.get('maker_fee',0)}%, тейкер {d.get('taker_fee',0)}%"
        )
    return (
        f"РЫНОЧНЫЕ ДАННЫЕ ({now}) | {pair_label}:PERP | ТФ: {TF}\n"
        f"{'═'*56}\n{fmt(okx)}\n\n{fmt(bybit)}\n{'═'*56}"
    )

# ─── AI ANALYSIS ──────────────────────────────────────────────────────────────
ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def ai_cot_signal(okx: dict, bybit: dict, pair: dict, deposit: float) -> str:
    risk_usdt = deposit * 0.01
    market = build_market_block(okx, bybit, pair["label"])
    system = f"""Ты — профессиональный AI-агент по фьючерсной торговле AlgoRobi. Биржи: OKX и Bybit.
Отвечай строго на русском языке. Будь конкретен, используй числа из данных.

ПАРАМЕТРЫ ПОЛЬЗОВАТЕЛЯ:
- Пара: {pair['label']}/USDT:PERP
- Депозит: {deposit} USDT | Риск 1% = {risk_usdt:.2f} USDT
- OKX: мейкер -0.02%, тейкер +0.05%
- Bybit: мейкер -0.01%, тейкер +0.06%
- Допустимое плечо: 3–8x (BTC/ETH), 3–5x (альткоины)

{market}

ЗАДАЧА: выполни 10 шагов Chain of Thought и выдай торговый сигнал.

[Шаг 1] Зафиксируй цену, FR, спред обеих бирж.
[Шаг 2] FR: <-0.05%→склонность LONG, >+0.05%→SHORT, иначе нейтрально.
[Шаг 3] L/S Ratio: Bybit ~54% LONG, OKX ~51%. >60% LONG — осторожнее.
[Шаг 4] Техника: пин-бар (wick>2×body, wick>60% range) + объём +30% к средней 20 свечей.
[Шаг 5] Стоп: LONG=вход-(ATR×1.5), SHORT=вход+(ATR×1.5). ATR_14 из свечей.
[Шаг 6] Ликвидация: LONG=вход-(вход/плечо). Стоп на 0.5% ближе к входу, иначе снижай плечо.
[Шаг 7] Стоп_% = |вход-стоп|/вход×100.
[Шаг 8] Выбор биржи: ликвидность 35%+комиссии 25%+безопасность 20%+FR 10%+доп 10%.
[Шаг 9] Позиция: {risk_usdt:.2f}USDT/(Стоп%/100). Если <20USDT→НЕ ВХОДИТЬ.
[Шаг 10] TP1=±(Стоп%×1.5), TP2=±×3, TP3=±×5. R/R≥1.5. Если нет→НЕ ВХОДИТЬ.

[РАСЧЁТ] — покажи цифры шагов 5–10.

Финальный ответ — JSON в блоке ```json ... ```:
{{"exchange":"...","pair":"{pair['label']}/USDT:PERP","direction":"LONG/SHORT","funding_rate":"...","leverage":0,"entry_price":0,"stop_loss":0,"liquidation_price":0,"take_profits":[0,0,0],"position_size_usdt":0,"margin_usdt":0,"risk_usdt":0,"risk_percent_of_deposit":1.0,"risk_reward_ratio_tp1":"X:1","okx_score":0,"bybit_score":0,"winner_reason":"...","verdict":"Приемлемо/Не входить","reason_if_reject":null}}"""

    resp = ai_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[{"role": "user", "content": "Дай торговый сигнал по текущим данным."}],
        system=system,
    )
    return resp.content[0].text

def ai_compare(okx: dict, bybit: dict, pair: dict, deposit: float) -> str:
    market = build_market_block(okx, bybit, pair["label"])
    system = f"""Ты — AlgoRobi, AI-агент сравнительного анализа бирж. Отвечай на русском.

ПАРАМЕТРЫ: Пара {pair['label']} | Депозит {deposit} USDT | Риск 1%

{market}

ЗАДАЧА: 6-шаговое сравнение OKX vs Bybit.

[Шаг 1] Ликвидность: спред, OI, объём — кто лидирует?
[Шаг 2] Funding Rate: у кого лучше для направления входа?
[Шаг 3] Комиссии: OKX(-0.02%/+0.05%) vs Bybit(-0.01%/+0.06%). Чистая прибыль TP1.
[Шаг 4] Безопасность: ликвидация при 5x на каждой бирже. Где стоп дальше?
[Шаг 5] Взвешенный score (ликвидность 35%+комиссии 25%+безопасность 20%+FR 10%+доп 10%).
[Шаг 6] Победитель и рекомендация.

Финальный ответ — JSON в блоке ```json ... ```:
{{"pair":"{pair['label']}/USDT:PERP","direction":"LONG/SHORT","okx":{{"score":0,"spread":"","funding_rate":"","oi":"","liq_5x":0,"net_tp1_usdt":0}},"bybit":{{"score":0,"spread":"","funding_rate":"","oi":"","liq_5x":0,"net_tp1_usdt":0}},"winner":"OKX/Bybit","winner_reason":"...","entry_price":0,"stop_loss":0,"take_profits":[0,0,0],"leverage":0,"position_size_usdt":0,"verdict":"Приемлемо/Не входить"}}"""

    resp = ai_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1200,
        messages=[{"role": "user", "content": "Сравни OKX и Bybit для входа по текущим данным."}],
        system=system,
    )
    return resp.content[0].text

# ─── MESSAGE FORMATTERS ───────────────────────────────────────────────────────
def parse_json_from_ai(text: str) -> Optional[dict]:
    import re
    m = re.search(r"```json\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except:
            pass
    m = re.search(r"\{[\s\S]*?\"verdict\"[\s\S]*?\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except:
            pass
    return None

def format_signal_msg(sig: dict, cot_text: str) -> str:
    if not sig:
        return f"🤖 <b>AlgoRobi</b>\n\n{cot_text[:3000]}"

    verdict = sig.get("verdict", "")
    direction = sig.get("direction", "")
    is_ok = verdict == "Приемлемо"
    dir_emoji = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    verdict_emoji = "✅" if is_ok else "❌"

    # Extract CoT reasoning (text before JSON block)
    import re
    cot_part = re.sub(r"```json[\s\S]*?```", "", cot_text).strip()
    cot_short = cot_part[:800] + "..." if len(cot_part) > 800 else cot_part

    msg = (
        f"🤖 <b>AlgoRobi — Торговый сигнал</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Пара:</b> {sig.get('pair','')}\n"
        f"🏆 <b>Биржа:</b> {sig.get('exchange','')}\n"
        f"📈 <b>Направление:</b> {dir_emoji}\n"
        f"💰 <b>Funding Rate:</b> {sig.get('funding_rate','')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if is_ok:
        tps = sig.get("take_profits", [0,0,0])
        msg += (
            f"🎯 <b>Вход:</b> <code>{sig.get('entry_price',0)}</code>\n"
            f"🛑 <b>Стоп-лосс:</b> <code>{sig.get('stop_loss',0)}</code>\n"
            f"💥 <b>Ликвидация:</b> <code>{sig.get('liquidation_price',0)}</code>\n"
            f"🎯 <b>TP1:</b> <code>{tps[0] if len(tps)>0 else 0}</code>\n"
            f"🎯 <b>TP2:</b> <code>{tps[1] if len(tps)>1 else 0}</code>\n"
            f"🎯 <b>TP3:</b> <code>{tps[2] if len(tps)>2 else 0}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ <b>Плечо:</b> {sig.get('leverage',0)}x\n"
            f"💵 <b>Позиция:</b> ${sig.get('position_size_usdt',0):.2f}\n"
            f"🔒 <b>Залог:</b> ${sig.get('margin_usdt',0):.2f}\n"
            f"📊 <b>R/R TP1:</b> {sig.get('risk_reward_ratio_tp1','')}\n"
            f"📉 <b>OKX/Bybit score:</b> {sig.get('okx_score',0)}/{sig.get('bybit_score',0)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>⚠️ Риск: ${sig.get('risk_usdt',0):.2f} ({sig.get('risk_percent_of_deposit',1)}% депозита)</code>\n"
        )
    else:
        msg += (
            f"{verdict_emoji} <b>Вердикт:</b> {verdict}\n"
            f"📝 <b>Причина:</b> {sig.get('reason_if_reject','нет сигнала')}\n"
        )

    if sig.get("winner_reason"):
        msg += f"\n💡 <i>{sig['winner_reason'][:200]}</i>\n"

    msg += f"\n<details><summary>📋 Анализ CoT</summary>\n<pre>{cot_short}</pre></details>"
    return msg

def format_compare_msg(sig: dict, text: str) -> str:
    if not sig:
        return f"🤖 <b>AlgoRobi — Сравнение</b>\n\n{text[:3000]}"

    okx  = sig.get("okx",  {})
    bybt = sig.get("bybit",{})
    winner = sig.get("winner","?")
    w_emoji = "🥇"

    def bar(score):
        filled = int(score / 10)
        return "█" * filled + "░" * (10 - filled) + f" {score}/100"

    msg = (
        f"🤖 <b>AlgoRobi — OKX vs Bybit</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Пара:</b> {sig.get('pair','')}\n"
        f"📈 <b>Направление:</b> {sig.get('direction','')}\n\n"
        f"<b>{'🥇 OKX' if winner=='OKX' else 'OKX'}</b>\n"
        f"<code>{bar(okx.get('score',0))}</code>\n"
        f"FR: {okx.get('funding_rate','')} | Спред: {okx.get('spread','')}\n"
        f"OI: {okx.get('oi','')} | Ликв.5x: {okx.get('liq_5x',0)}\n"
        f"Чистая прибыль TP1: ${okx.get('net_tp1_usdt',0):.2f}\n\n"
        f"<b>{'🥇 Bybit' if winner=='Bybit' else 'Bybit'}</b>\n"
        f"<code>{bar(bybt.get('score',0))}</code>\n"
        f"FR: {bybt.get('funding_rate','')} | Спред: {bybt.get('spread','')}\n"
        f"OI: {bybt.get('oi','')} | Ликв.5x: {bybt.get('liq_5x',0)}\n"
        f"Чистая прибыль TP1: ${bybt.get('net_tp1_usdt',0):.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{w_emoji} <b>Победитель: {winner}</b>\n"
        f"💡 <i>{sig.get('winner_reason','')[:200]}</i>\n\n"
    )

    if sig.get("entry_price"):
        tps = sig.get("take_profits", [0,0,0])
        msg += (
            f"🎯 Вход: <code>{sig['entry_price']}</code> | "
            f"Стоп: <code>{sig.get('stop_loss',0)}</code>\n"
            f"TP: <code>{tps[0]}</code> / <code>{tps[1] if len(tps)>1 else 0}</code> / <code>{tps[2] if len(tps)>2 else 0}</code>\n"
            f"Плечо: {sig.get('leverage',0)}x | Позиция: ${sig.get('position_size_usdt',0):.2f}\n"
            f"<b>Вердикт: {sig.get('verdict','')}</b>\n"
        )
    return msg

def format_status_msg(market_data: dict) -> str:
    lines = [
        "🤖 <b>AlgoRobi — Статус рынка</b>",
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for pair_key, pair in PAIRS.items():
        d = market_data.get(pair_key)
        if not d:
            continue
        okx_d  = d.get("okx",  {})
        byb_d  = d.get("bybit",{})

        def price_line(ex_d):
            if not ex_d.get("ok"):
                return f"❌ {ex_d.get('error','err')[:30]}"
            p = ex_d.get("price", 0)
            chg = ex_d.get("change24h", 0)
            fr = ex_d.get("funding_rate", "N/A")
            try:
                fr_pct = f"{float(fr)*100:.3f}%"
            except:
                fr_pct = str(fr)
            arrow = "▲" if chg >= 0 else "▼"
            return f"${p:,.4f} {arrow}{abs(chg):.2f}% | FR:{fr_pct}"

        lines.append(f"\n<b>{pair['label']}</b>")
        lines.append(f"  OKX:   {price_line(okx_d)}")
        lines.append(f"  Bybit: {price_line(byb_d)}")

        # arbitrage
        if okx_d.get("ok") and byb_d.get("ok"):
            diff = abs(okx_d.get("price",0) - byb_d.get("price",0))
            if diff > 0:
                lines.append(f"  ↔ Расхождение: ${diff:.2f}")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"⚙️ Депозит: ${DEPOSIT_USDT} | Риск: {RISK_PERCENT}%")
    lines.append("📱 Команды: /signal /compare /scan /help")
    return "\n".join(lines)

# ─── BOT HANDLERS ─────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 <b>AlgoRobi — Крипто советник</b>\n\n"
        "Я анализирую OKX и Bybit с помощью AI и технического анализа.\n"
        "Использую 10-шаговый Chain of Thought для каждого сигнала.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>Команды:</b>\n\n"
        "🎯 /signal — сигнал по BTC\n"
        "🎯 /signal ETH — сигнал по ETH\n"
        "🎯 /signal SOL — сигнал по SOL\n\n"
        "⚖️ /compare — сравнить OKX vs Bybit (BTC)\n"
        "⚖️ /compare ETH — сравнить по ETH\n\n"
        "🔍 /scan — сканировать все пары\n"
        "📊 /status — статус рынка\n"
        "❓ /help — подробная справка\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ Депозит: <b>${DEPOSIT_USDT}</b> | Риск: <b>{RISK_PERCENT}%</b>\n\n"
        "<i>⚠️ Не является финансовой рекомендацией</i>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "❓ <b>AlgoRobi — Справка</b>\n\n"
        "<b>Как работает бот:</b>\n"
        "1. Загружает данные с OKX и Bybit (цена, funding rate, стакан, свечи, OI)\n"
        "2. Запускает 10-шаговый Chain of Thought через Claude AI\n"
        "3. Алгоритм: пин-бар + объём +30% → ATR-стоп → ликвидация → позиция → R/R\n"
        "4. Выдаёт сигнал только если R/R ≥ 1.5 и позиция ≥ 20 USDT\n\n"
        "<b>Доступные пары:</b>\n"
        + "\n".join(f"  • /signal {k}" for k in PAIRS.keys()) +
        "\n\n<b>Алгоритм пин-бара:</b>\n"
        "  • Wick > 2×body\n"
        "  • Wick > 60% range\n"
        "  • Объём > средний×1.3\n\n"
        "<b>Риск-менеджмент:</b>\n"
        f"  • Риск на сделку: {RISK_PERCENT}% от ${DEPOSIT_USDT} = ${DEPOSIT_USDT*RISK_PERCENT/100:.2f}\n"
        "  • Позиция = Риск$ / Стоп%\n"
        "  • Залог = Позиция / Плечо\n\n"
        "<i>⚠️ Торговля с плечом несёт высокий риск</i>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    pair_key = args[0].upper().replace("USDT","").replace("/","").strip() if args else DEFAULT_PAIR
    pair = PAIRS.get(pair_key)
    if not pair:
        available = ", ".join(PAIRS.keys())
        await update.message.reply_text(
            f"❌ Пара <b>{pair_key}</b> не найдена.\nДоступные: {available}",
            parse_mode=ParseMode.HTML
        )
        return

    wait_msg = await update.message.reply_text(
        f"⏳ <b>Анализирую {pair['label']}...</b>\n"
        f"Загружаю данные с OKX и Bybit → 10 шагов CoT → генерирую сигнал\n"
        f"<i>Обычно занимает 10-20 секунд</i>",
        parse_mode=ParseMode.HTML
    )

    try:
        log.info(f"Signal requested: {pair['label']}")
        okx  = fetch_okx(pair)
        bybt = fetch_bybit(pair)
        ai_text = ai_cot_signal(okx, bybt, pair, DEPOSIT_USDT)
        sig = parse_json_from_ai(ai_text)
        msg = format_signal_msg(sig, ai_text)
        await wait_msg.delete()
        # Telegram limit 4096 chars
        if len(msg) > 4000:
            msg = msg[:3990] + "\n<i>...обрезано</i>"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.error(f"Signal error: {e}")
        await wait_msg.delete()
        await update.message.reply_text(
            f"❌ Ошибка: <code>{str(e)[:200]}</code>",
            parse_mode=ParseMode.HTML
        )

async def cmd_compare(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    pair_key = args[0].upper().replace("USDT","").replace("/","").strip() if args else DEFAULT_PAIR
    pair = PAIRS.get(pair_key, PAIRS[DEFAULT_PAIR])

    wait_msg = await update.message.reply_text(
        f"⏳ <b>Сравниваю OKX vs Bybit по {pair['label']}...</b>\n"
        f"<i>Занимает 10-20 секунд</i>",
        parse_mode=ParseMode.HTML
    )

    try:
        okx  = fetch_okx(pair)
        bybt = fetch_bybit(pair)
        ai_text = ai_compare(okx, bybt, pair, DEPOSIT_USDT)
        sig = parse_json_from_ai(ai_text)
        msg = format_compare_msg(sig, ai_text)
        await wait_msg.delete()
        if len(msg) > 4000:
            msg = msg[:3990] + "\n<i>...обрезано</i>"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.error(f"Compare error: {e}")
        await wait_msg.delete()
        await update.message.reply_text(
            f"❌ Ошибка: <code>{str(e)[:200]}</code>",
            parse_mode=ParseMode.HTML
        )

async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wait_msg = await update.message.reply_text(
        f"🔍 <b>Сканирую {len(PAIRS)} пар...</b>\n"
        f"Ищу пин-бары с объёмным всплеском на 15м\n"
        f"<i>Займёт около {len(PAIRS)*3} секунд</i>",
        parse_mode=ParseMode.HTML
    )

    found = []
    no_signal = []

    for pk, pair in PAIRS.items():
        try:
            okx  = fetch_okx(pair)
            bybt = fetch_bybit(pair)
            analysis = analyze_pair(okx, bybt, DEPOSIT_USDT, RISK_PERCENT)

            if analysis["has_signal"] and analysis["winner"]:
                w = analysis["winner"]
                wd = analysis["results"]["okx" if w=="OKX" else "bybit"]
                if wd.get("rr", 0) >= 1.5 and wd.get("pos_size", 0) >= 20:
                    found.append({
                        "pair": pair["label"], "winner": w, "dir": wd["dir"],
                        "entry": wd["entry"], "rr": wd["rr"],
                        "score": wd["score"], "leverage": wd["leverage"],
                        "pos": wd["pos_size"],
                    })
                else:
                    no_signal.append(f"{pair['label']}: слабый сигнал R/R={wd.get('rr',0)}")
            else:
                no_signal.append(f"{pair['label']}: нет паттерна")
            time.sleep(0.5)
        except Exception as e:
            no_signal.append(f"{pair['label']}: ошибка ({str(e)[:30]})")

    await wait_msg.delete()

    if found:
        lines = ["🔍 <b>AlgoRobi — Результаты скана</b>\n"]
        lines.append(f"✅ <b>Найдено сигналов: {len(found)}</b>\n")
        for s in found:
            dir_e = "🟢" if s["dir"]=="LONG" else "🔴"
            lines.append(
                f"{dir_e} <b>{s['pair']}</b> — {s['winner']} {s['dir']}\n"
                f"   Вход: <code>{s['entry']}</code> | R/R: {s['rr']} | Плечо: {s['leverage']}x\n"
                f"   Позиция: ${s['pos']} | Score: {s['score']}\n"
                f"   → /signal {s['pair'].replace('/USDT','')}\n"
            )
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⚪ Без сигнала: {len(no_signal)} пар")
    else:
        lines = [
            "🔍 <b>AlgoRobi — Результаты скана</b>\n",
            "⚪ <b>Сигналов не найдено</b>\n",
            "Нет пин-баров с подтверждением объёма на 15м.\n",
            "<i>Попробуй позже или проверь отдельные пары через /signal</i>\n",
            "━━━━━━━━━━━━━━━━━━━━━━\n",
        ] + [f"• {x}" for x in no_signal]

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3990] + "\n<i>...обрезано</i>"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wait_msg = await update.message.reply_text(
        "📊 <b>Загружаю рыночные данные...</b>",
        parse_mode=ParseMode.HTML
    )

    market_data = {}
    for pk, pair in PAIRS.items():
        try:
            okx  = fetch_okx(pair)
            bybt = fetch_bybit(pair)
            market_data[pk] = {"okx": okx, "bybit": bybt}
            time.sleep(0.3)
        except Exception as e:
            market_data[pk] = {"okx": {"ok": False, "error": str(e)}, "bybit": {"ok": False, "error": str(e)}}

    await wait_msg.delete()
    msg = format_status_msg(market_data)
    if len(msg) > 4000:
        msg = msg[:3990] + "\n<i>...обрезано</i>"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка обычных сообщений — лёгкий чат-режим"""
    text = update.message.text.strip()
    if not text:
        return

    wait_msg = await update.message.reply_text(
        "💭 <b>Обрабатываю...</b>",
        parse_mode=ParseMode.HTML
    )

    try:
        # Быстрый ответ через AI без рыночных данных
        resp = ai_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=(
                "Ты — AlgoRobi, профессиональный крипто-советник в Telegram. "
                "Отвечай коротко (до 300 слов), по делу, на русском языке. "
                "Если спрашивают про сигнал — скажи использовать /signal. "
                "Если про сравнение — /compare. Если про рынок — /status."
            ),
            messages=[{"role": "user", "content": text}],
        )
        reply = resp.content[0].text
        await wait_msg.delete()
        await update.message.reply_text(reply[:4000], parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_msg.delete()
        await update.message.reply_text(
            f"❌ Ошибка: {str(e)[:200]}\n\nИспользуй команды: /signal /compare /status",
            parse_mode=ParseMode.HTML
        )

# ─── AUTO SCAN JOB ────────────────────────────────────────────────────────────
async def auto_scan_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Автоматический скан — запускается по расписанию"""
    chat_id = ctx.job.data
    log.info("Auto scan started")
    found = []
    for pk, pair in PAIRS.items():
        try:
            okx  = fetch_okx(pair)
            bybt = fetch_bybit(pair)
            analysis = analyze_pair(okx, bybt, DEPOSIT_USDT, RISK_PERCENT)
            if analysis["has_signal"] and analysis["winner"]:
                w = analysis["winner"]
                wd = analysis["results"]["okx" if w=="OKX" else "bybit"]
                if wd.get("rr",0) >= 1.5 and wd.get("pos_size",0) >= 20:
                    found.append((pair, w, wd))
            time.sleep(0.5)
        except Exception as e:
            log.error(f"Auto scan {pk}: {e}")

    if found:
        for pair, winner, wd in found:
            dir_e = "🟢" if wd["dir"]=="LONG" else "🔴"
            msg = (
                f"🚨 <b>АВТО-СИГНАЛ AlgoRobi</b>\n\n"
                f"{dir_e} <b>{pair['label']}</b> — {winner} {wd['dir']}\n"
                f"🎯 Вход: <code>{wd['entry']}</code>\n"
                f"🛑 Стоп: <code>{wd['stop']}</code> ({wd['sl_pct']}%)\n"
                f"🎯 TP1/TP2/TP3: <code>{wd['tps'][0]}</code> / <code>{wd['tps'][1]}</code> / <code>{wd['tps'][2]}</code>\n"
                f"⚙️ Плечо: {wd['leverage']}x | Позиция: ${wd['pos_size']}\n"
                f"📊 R/R: {wd['rr']}:1 | Score: {wd['score']}\n\n"
                f"<code>⚠️ Риск: ${wd['risk_usdt']} USDT</code>\n"
                f"🔎 Подробный анализ: /signal {pair['label'].replace('/USDT','')}"
            )
            await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)
    else:
        log.info("Auto scan: no signals found")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("""
╔══════════════════════════════════════════════════╗
║         🤖 AlgoRobi — Trading Signal Bot         ║
║         OKX + Bybit | 10-Step CoT | Claude AI    ║
╚══════════════════════════════════════════════════╝
    """)

    # Проверка конфигурации
    if TELEGRAM_TOKEN == "YOUR_BOT_TOKEN":
        print("❌ ОШИБКА: Заполни TELEGRAM_TOKEN")
        print("   1. Напиши @BotFather → /newbot → скопируй токен")
        print("   2. Вставь в переменную TELEGRAM_TOKEN в начале файла")
        return

    if ANTHROPIC_API_KEY == "YOUR_ANTHROPIC_KEY":
        print("❌ ОШИБКА: Заполни ANTHROPIC_API_KEY")
        print("   1. Зайди на console.anthropic.com")
        print("   2. API Keys → Create Key → скопируй")
        print("   3. Вставь в переменную ANTHROPIC_API_KEY в начале файла")
        return

    print(f"✅ Конфигурация:")
    print(f"   Депозит: ${DEPOSIT_USDT} | Риск: {RISK_PERCENT}%")
    print(f"   Пар для мониторинга: {len(PAIRS)}")
    print(f"   Авто-скан: {'каждые ' + str(AUTO_SCAN_HOURS) + ' ч' if AUTO_SCAN_HOURS > 0 else 'выкл'}")
    print(f"   Таймфрейм: {TF} | Свечей: {CANDLE_LIMIT}")
    print()

    # Создаём приложение
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Регистрируем команды
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("signal",  cmd_signal))
    app.add_handler(CommandHandler("compare", cmd_compare))
    app.add_handler(CommandHandler("scan",    cmd_scan))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    print("🚀 Бот запущен! Нажми Ctrl+C для остановки.")
    print("📱 Найди своего бота в Telegram и напиши /start\n")

    # Запускаем
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
