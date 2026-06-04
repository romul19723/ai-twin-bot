import { useState, useEffect, useCallback, useRef } from "react";

// ─── CONFIG ───────────────────────────────────────────────────────────────────
const PAIRS = [
  { label: "BTC/USDT", okx: "BTC-USDT-SWAP", bybit: "BTCUSDT" },
  { label: "ETH/USDT", okx: "ETH-USDT-SWAP", bybit: "ETHUSDT" },
  { label: "SOL/USDT", okx: "SOL-USDT-SWAP", bybit: "SOLUSDT" },
  { label: "XRP/USDT", okx: "XRP-USDT-SWAP", bybit: "XRPUSDT" },
  { label: "DOGE/USDT", okx: "DOGE-USDT-SWAP", bybit: "DOGEUSDT" },
  { label: "ADA/USDT", okx: "ADA-USDT-SWAP", bybit: "ADAUSDT" },
];
const TIMEFRAMES = ["5m", "15m", "1h", "4h"];
const PROXY = "https://api.allorigins.win/raw?url=";

// ─── API HELPERS ──────────────────────────────────────────────────────────────
async function pget(url) {
  const r = await fetch(PROXY + encodeURIComponent(url));
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function fetchOKX(pair, tf) {
  const base = "https://www.okx.com/api/v5";
  const sym = pair.okx;
  try {
    const [fr, ob, candles, ticker, oi] = await Promise.allSettled([
      pget(`${base}/public/funding-rate?instId=${sym}`),
      pget(`${base}/market/books?instId=${sym}&sz=20`),
      pget(`${base}/market/candles?instId=${sym}&bar=${tf}&limit=50`),
      pget(`${base}/market/ticker?instId=${sym}`),
      pget(`${base}/market/open-interest?instId=${sym}`),
    ]);
    const frD = fr.value; const obD = ob.value; const cD = candles.value;
    const tD = ticker.value; const oiD = oi.value;
    const bid = obD?.data?.[0]?.bids?.[0]?.[0] ? +obD.data[0].bids[0][0] : 0;
    const ask = obD?.data?.[0]?.asks?.[0]?.[0] ? +obD.data[0].asks[0][0] : 0;
    const cList = cD?.data || [];
    return {
      exchange: "OKX", ok: true,
      funding_rate: frD?.data?.[0]?.fundingRate ?? "N/A",
      price: +(tD?.data?.[0]?.last || 0),
      bid, ask,
      spread: bid > 0 ? ((ask - bid) / bid * 100) : 0,
      open_interest: oiD?.data?.[0]?.oi ?? "N/A",
      volume24h: +(tD?.data?.[0]?.vol24h || 0),
      change24h: +(tD?.data?.[0]?.changeUtc0 || 0),
      candles: cList,
      maker_fee: -0.02, taker_fee: 0.05,
    };
  } catch (e) { return { exchange: "OKX", ok: false, error: e.message }; }
}

async function fetchBybit(pair, tf) {
  const base = "https://api.bybit.com/v5";
  const sym = pair.bybit;
  const iv = tf.replace("m", "");
  try {
    const [ticker, ob, kline, oi] = await Promise.allSettled([
      pget(`${base}/market/tickers?category=linear&symbol=${sym}`),
      pget(`${base}/market/orderbook?category=linear&symbol=${sym}&limit=20`),
      pget(`${base}/market/kline?category=linear&symbol=${sym}&interval=${iv}&limit=50`),
      pget(`${base}/market/open-interest?category=linear&symbol=${sym}&intervalTime=5min&limit=1`),
    ]);
    const tD = ticker.value?.result?.list?.[0] || {};
    const obR = ob.value?.result || {};
    const bid = obR.b?.[0]?.[0] ? +obR.b[0][0] : 0;
    const ask = obR.a?.[0]?.[0] ? +obR.a[0][0] : 0;
    const kList = kline.value?.result?.list || [];
    return {
      exchange: "Bybit", ok: true,
      funding_rate: tD.fundingRate ?? "N/A",
      price: +(tD.lastPrice || 0),
      bid, ask,
      spread: bid > 0 ? ((ask - bid) / bid * 100) : 0,
      open_interest: oi.value?.result?.list?.[0]?.openInterest ?? "N/A",
      volume24h: +(tD.volume24h || 0),
      change24h: +(tD.price24hPcnt || 0) * 100,
      candles: kList,
      maker_fee: -0.01, taker_fee: 0.06,
    };
  } catch (e) { return { exchange: "Bybit", ok: false, error: e.message }; }
}

// ─── TRADING LOGIC (from bot) ─────────────────────────────────────────────────
function calcATR(candles, period = 14) {
  if (!candles || candles.length < period) return 0;
  const trs = [];
  for (let i = 1; i < Math.min(candles.length, period + 1); i++) {
    const high = +candles[i][2], low = +candles[i][3], prevClose = +candles[i - 1][4];
    trs.push(Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose)));
  }
  return trs.length ? trs.reduce((a, b) => a + b, 0) / trs.length : 0;
}

function detectPinBar(candles, threshold = 0.3) {
  if (!candles || candles.length < 20) return { found: false };
  const c = candles[0];
  const high = +c[2], low = +c[3], open = +c[1], close = +c[4], volume = +c[5];
  const avgVol = candles.slice(1, 21).reduce((s, x) => s + +x[5], 0) / 20;
  const volSpike = volume > avgVol * (1 + threshold);
  const body = Math.abs(close - open);
  const lowerWick = Math.min(open, close) - low;
  const upperWick = high - Math.max(open, close);
  const range = high - low;
  const isLong = lowerWick > body * 2 && lowerWick > range * 0.6;
  const isShort = upperWick > body * 2 && upperWick > range * 0.6;
  if (isLong && volSpike) return { found: true, dir: "LONG", entry: low };
  if (isShort && volSpike) return { found: true, dir: "SHORT", entry: high };
  return { found: false };
}

function calcPosition(riskUsdt, slPct, leverage) {
  if (slPct <= 0) return { position_size_usdt: 0, margin_usdt: 0 };
  const pos = riskUsdt / (slPct / 100);
  return { position_size_usdt: +pos.toFixed(2), margin_usdt: +(pos / leverage).toFixed(2) };
}

function analyzePairBot(okx, bybit, deposit, riskPct) {
  const riskUsdt = deposit * riskPct / 100;
  const results = {};
  for (const [d, name] of [[okx, "okx"], [bybit, "bybit"]]) {
    if (!d?.ok || !d.candles?.length) { results[name] = { score: 0 }; continue; }
    const pb = detectPinBar(d.candles);
    if (!pb.found) { results[name] = { score: 0 }; continue; }
    const atr = calcATR(d.candles);
    if (!atr) { results[name] = { score: 0 }; continue; }
    const { dir, entry } = pb;
    let stop, slPct, tp1, tp2, tp3;
    if (dir === "LONG") {
      stop = entry - atr * 1.5;
      slPct = (entry - stop) / entry * 100;
      tp1 = entry * (1 + slPct * 1.5 / 100);
      tp2 = entry * (1 + slPct * 3 / 100);
      tp3 = entry * (1 + slPct * 5 / 100);
    } else {
      stop = entry + atr * 1.5;
      slPct = (stop - entry) / entry * 100;
      tp1 = entry * (1 - slPct * 1.5 / 100);
      tp2 = entry * (1 - slPct * 3 / 100);
      tp3 = entry * (1 - slPct * 5 / 100);
    }
    const lev = (name === "okx" && d.spread < 0.05) ? 5 : 3;
    const liqPrice = dir === "LONG" ? entry - entry / lev : entry + entry / lev;
    const pos = calcPosition(riskUsdt, slPct, lev);
    const fr = parseFloat(d.funding_rate) || 0;
    const rr = slPct > 0 ? +((slPct * 1.5 - d.taker_fee) / (slPct + d.taker_fee)).toFixed(2) : 0;
    let score = 0;
    if (rr >= 1.5) score += 50;
    if (Math.abs(fr) > 0.0005) score += 20; else score += 10;
    if (d.spread < 0.02) score += 20; else if (d.spread < 0.05) score += 10;
    if (pos.position_size_usdt >= 20) score += 10;
    results[name] = {
      score, dir, entry: +entry.toFixed(4), stop: +stop.toFixed(4),
      liqPrice: +liqPrice.toFixed(4), tps: [+tp1.toFixed(4), +tp2.toFixed(4), +tp3.toFixed(4)],
      slPct: +slPct.toFixed(3), rr, fr, spread: +d.spread.toFixed(4),
      leverage: lev, ...pos, riskUsdt: +riskUsdt.toFixed(2),
    };
  }
  const okxScore = results.okx?.score || 0;
  const bybitScore = results.bybit?.score || 0;
  const hasSignal = okxScore > 0 || bybitScore > 0;
  const winner = !hasSignal ? null : okxScore >= bybitScore ? "OKX" : "Bybit";
  return { results, winner, hasSignal, riskUsdt };
}

// ─── PROMPT BUILDERS ──────────────────────────────────────────────────────────
function buildMarketBlock(okx, bybit, pair, tf) {
  const now = new Date().toLocaleString("ru-RU");
  const fmt = (d) => {
    if (!d?.ok) return `=== ${d?.exchange || "?"} ===\nОШИБКА: ${d?.error}`;
    const fr = parseFloat(d.funding_rate);
    const frPct = isNaN(fr) ? d.funding_rate : (fr * 100).toFixed(4) + "%";
    return `=== ${d.exchange} ===
Цена: $${d.price?.toLocaleString()} | Изм.24ч: ${d.change24h?.toFixed(2)}%
Funding Rate: ${frPct} | Спред: ${d.spread?.toFixed(4)}%
Bid: $${d.bid?.toLocaleString()} | Ask: $${d.ask?.toLocaleString()}
Open Interest: ${d.open_interest} | Объём 24ч: ${d.volume24h?.toLocaleString()}
Свечей (${tf}): ${d.candles?.length ?? 0}
Последняя свеча [t,O,H,L,C,V]: ${JSON.stringify(d.candles?.[0] ?? [])}
Комиссии: мейкер ${d.maker_fee}%, тейкер ${d.taker_fee}%`;
  };
  return `РЫНОЧНЫЕ ДАННЫЕ (${now}) | ${pair.label}:PERP | ТФ: ${tf}
${"═".repeat(56)}
${fmt(okx)}

${fmt(bybit)}
${"═".repeat(56)}`;
}

function buildSystem(okx, bybit, pair, tf, deposit, mode) {
  const market = okx && bybit ? buildMarketBlock(okx, bybit, pair, tf) : "";
  const riskUsdt = (deposit * 0.01).toFixed(2);
  const base = `Ты — профессиональный AI-агент по фьючерсной торговле. Биржи: OKX и Bybit. Отвечай на русском языке. Будь конкретен, используй числа из данных.

ПАРАМЕТРЫ:
- Пара: ${pair.label}/USDT:PERP | Депозит: ${deposit} USDT | Риск 1% = ${riskUsdt} USDT
- OKX: мейкер -0.02%, тейкер +0.05% | Bybit: мейкер -0.01%, тейкер +0.06%
- Плечо: 3–8x (BTC/ETH), 3–5x (альткоины)

${market}`;

  if (mode === "signal") return base + `

ЗАДАЧА: 10-шаговый Chain of Thought → торговый сигнал.

[Шаг 1] Данные: зафиксируй цену, FR, спред обеих бирж из предоставленных данных.
[Шаг 2] Funding Rate: FR<-0.05%→LONG, FR>+0.05%→SHORT, иначе→нейтрально. Сравни оба.
[Шаг 3] Long/Short Ratio: Bybit ~54% LONG, OKX ~51% LONG. >60% LONG → осторожнее с лонгами.
[Шаг 4] Техника: по свечам найди пин-бар (wick>2×body, wick>60% range) + объём +30% к средней 20 свечей. Цена входа.
[Шаг 5] Стоп-лосс: LONG = вход-(ATR×1.5), SHORT = вход+(ATR×1.5). ATR_14 по свечам. Число.
[Шаг 6] Ликвидация: LONG = вход-(вход/плечо). SHORT = вход+(вход/плечо). Стоп должен быть на 0.5% ближе к входу чем ликвидация, иначе уменьши плечо.
[Шаг 7] Стоп_% = |вход-стоп|/вход×100.
[Шаг 8] Выбор биржи (ликвидность 35%+комиссии 25%+безопасность 20%+FR 10%+доп 10%). Score OKX и Bybit.
[Шаг 9] Позиция: МаксУбыток=${riskUsdt}USDT. РазмерПозиции=МаксУбыток/(Стоп%/100). Залог=Позиция/Плечо. Если позиция<20USDT→НЕ ВХОДИТЬ.
[Шаг 10] TP: TP1=вход±(Стоп%×1.5), TP2=±×3, TP3=±×5. R/R=(TP1%-taker)/(Стоп%+taker)≥1.5. Если нет→НЕ ВХОДИТЬ.

[РАСЧЁТ] — покажи числа шагов 5–10.

Финальный ответ строго в формате:
\`\`\`json
{"exchange":"OKX или Bybit","pair":"${pair.label}/USDT:PERP","direction":"LONG или SHORT","funding_rate":"","leverage":0,"entry_price":0,"stop_loss":0,"liquidation_price":0,"take_profits":[0,0,0],"position_size_usdt":0,"margin_usdt":0,"risk_usdt":0,"risk_percent_of_deposit":1.0,"risk_reward_ratio_tp1":"X:1","okx_score":0,"bybit_score":0,"winner_reason":"","verdict":"Приемлемо или Не входить","reason_if_reject":null}
\`\`\``;

  if (mode === "compare") return base + `

ЗАДАЧА: 12-шаговое сравнение OKX vs Bybit.

[Шаг 1-2] Данные обеих бирж. [Шаг 3] Ликвидность: спред, OI, объём. [Шаг 4] FR сравнение. [Шаг 5] Вход по технике. [Шаг 6] Стоп ATR. [Шаг 7] Ликвидация 5x на каждой. [Шаг 8] Комиссии и чистая прибыль TP1. [Шаг 9] Позиция с комиссиями. [Шаг 10] Доп. факторы. [Шаг 11] Взвешенный score. [Шаг 12] Победитель.

\`\`\`json
{"pair":"${pair.label}/USDT:PERP","direction":"LONG или SHORT","comparison":{"okx":{"funding_rate":"","spread":"","open_interest":"","liquidation_price":0,"net_profit_tp1_usdt":0,"score":0},"bybit":{"funding_rate":"","spread":"","open_interest":"","liquidation_price":0,"net_profit_tp1_usdt":0,"score":0}},"winner":"OKX или Bybit","winner_reason":"","entry_price":0,"stop_loss":0,"take_profits":[0,0,0],"leverage":0,"position_size_usdt":0,"margin_usdt":0,"risk_usdt":0,"risk_reward_ratio_tp1":"X:1","verdict":"Приемлемо или Не входить"}
\`\`\``;

  return base + `\n\nТы опытный крипто-советник. Отвечай конкретно, используй данные. Указывай риски.`;
}

// ─── TELEGRAM BOT LOGIC ───────────────────────────────────────────────────────
async function sendTelegram(token, chatId, text) {
  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML", disable_web_page_preview: true }),
  });
  if (!r.ok) { const e = await r.json(); throw new Error(e.description || `HTTP ${r.status}`); }
  return r.json();
}

function formatTgSignal(pair, winner, data, riskPct, deposit) {
  const dir = data.dir === "LONG" ? "🟢 LONG" : "🔴 SHORT";
  return `🚨 <b>ТОРГОВЫЙ СИГНАЛ</b> 🚨

<b>📊 Пара:</b> ${pair.label}/USDT:PERP
<b>🏆 Биржа:</b> ${winner}
<b>📈 Направление:</b> ${dir}
<b>💰 Funding Rate:</b> ${(data.fr * 100).toFixed(4)}%

<b>🎯 Вход:</b> ${data.entry}
<b>🛑 Стоп-лосс:</b> ${data.stop} (${data.slPct}%)
<b>💥 Ликвидация:</b> ${data.liqPrice}
<b>🎯 TP1 / TP2 / TP3:</b> ${data.tps[0]} / ${data.tps[1]} / ${data.tps[2]}

<b>⚙️ Плечо:</b> ${data.leverage}x
<b>💵 Размер позиции:</b> ${data.position_size_usdt} USDT
<b>🔒 Залог:</b> ${data.margin_usdt} USDT
<b>📊 Risk/Reward TP1:</b> ${data.rr}:1
<b>📏 Спред:</b> ${data.spread}%

<code>⚠️ Риск: ${riskPct}% депозита = $${data.riskUsdt} USDT</code>`;
}

// ─── JSON SIGNAL CARD ─────────────────────────────────────────────────────────
function extractJSON(text) {
  try { const m = text.match(/```json\s*([\s\S]*?)```/); if (m) return JSON.parse(m[1].trim()); } catch {}
  try { const m = text.match(/\{[\s\S]*?"verdict"[\s\S]*?\}/); if (m) return JSON.parse(m[0]); } catch {}
  return null;
}

function SignalCard({ sig }) {
  const isLong = sig.direction === "LONG";
  const isOk = sig.verdict === "Приемлемо";
  const dc = isLong ? "#1D9E75" : "#e24b4a";
  const row = (l, v, c) => (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
      <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{l}</span>
      <span style={{ fontSize: 12, fontWeight: 500, color: c || "var(--color-text-primary)" }}>{v}</span>
    </div>
  );
  return (
    <div style={{ background: "var(--color-background-primary)", border: `2px solid ${isOk ? "#1D9E75" : "#e24b4a"}`, borderRadius: "var(--border-radius-lg)", padding: "0.75rem", margin: "4px 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ fontSize: 13, fontWeight: 500 }}>{sig.exchange} · {sig.pair}</span>
          <span style={{ fontSize: 11, fontWeight: 500, color: dc, background: isLong ? "#E1F5EE" : "#FCEBEB", padding: "2px 7px", borderRadius: 20 }}>{sig.direction} {sig.leverage}x</span>
        </div>
        <span style={{ fontSize: 11, fontWeight: 500, color: isOk ? "var(--color-text-success)" : "var(--color-text-danger)", background: isOk ? "var(--color-background-success)" : "var(--color-background-danger)", padding: "2px 9px", borderRadius: 20 }}>{sig.verdict}</span>
      </div>
      {sig.reason_if_reject && <div style={{ background: "var(--color-background-danger)", border: "0.5px solid var(--color-border-danger)", borderRadius: "var(--border-radius-md)", padding: "5px 9px", fontSize: 11, color: "var(--color-text-danger)", marginBottom: 6 }}>{sig.reason_if_reject}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 1rem" }}>
        <div>
          {row("Вход", `$${sig.entry_price?.toLocaleString()}`)}
          {row("Стоп-лосс", `$${sig.stop_loss?.toLocaleString()}`, "#e24b4a")}
          {row("Ликвидация", `$${sig.liquidation_price?.toLocaleString()}`, "#e24b4a")}
          {row("Funding Rate", sig.funding_rate)}
          {row("R/R TP1", sig.risk_reward_ratio_tp1, "#1D9E75")}
        </div>
        <div>
          {row("Позиция", `$${sig.position_size_usdt?.toFixed(2)}`)}
          {row("Залог", `$${sig.margin_usdt?.toFixed(2)}`)}
          {row("Риск $", `$${sig.risk_usdt?.toFixed(2)}`, "#e24b4a")}
          {row("Риск %", `${sig.risk_percent_of_deposit}%`, "#e24b4a")}
          {sig.okx_score !== undefined && row("OKX/Bybit", `${sig.okx_score}/${sig.bybit_score}`)}
        </div>
      </div>
      {sig.take_profits && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginBottom: 4 }}>ТЕЙК-ПРОФИТЫ</div>
          <div style={{ display: "flex", gap: 5 }}>
            {sig.take_profits.map((tp, i) => (
              <div key={i} style={{ flex: 1, background: "#E1F5EE", borderRadius: "var(--border-radius-md)", padding: "4px 6px", textAlign: "center" }}>
                <div style={{ fontSize: 9, color: "#0F6E56" }}>TP{i + 1}</div>
                <div style={{ fontSize: 11, fontWeight: 500, color: "#085041" }}>${tp?.toLocaleString()}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {sig.winner_reason && <div style={{ marginTop: 6, fontSize: 11, color: "var(--color-text-secondary)", fontStyle: "italic" }}>{sig.winner_reason}</div>}
    </div>
  );
}

function CompareCard({ sig }) {
  const okx = sig.comparison?.okx, bybit = sig.comparison?.bybit;
  if (!okx || !bybit) return <SignalCard sig={sig} />;
  const w = sig.winner;
  const bar = (s) => <div style={{ height: 3, background: "var(--color-background-secondary)", borderRadius: 2, marginTop: 3 }}><div style={{ width: `${s}%`, height: "100%", background: "#1D9E75", borderRadius: 2 }} /></div>;
  const col = (name, d) => (
    <div style={{ flex: 1, background: "var(--color-background-primary)", border: `${name === w ? "2px" : "0.5px"} solid ${name === w ? "#1D9E75" : "var(--color-border-tertiary)"}`, borderRadius: "var(--border-radius-md)", padding: "0.625rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 500 }}>{name}</span>
        {name === w && <span style={{ fontSize: 9, background: "#E1F5EE", color: "#0F6E56", padding: "1px 6px", borderRadius: 10 }}>✓ Победитель</span>}
      </div>
      <div style={{ fontSize: 13, fontWeight: 500 }}>Счёт: {d.score}/100</div>
      {bar(d.score)}
      <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 6 }}>
        <div>FR: {d.funding_rate}</div>
        <div>Спред: {d.spread}</div>
        <div>Прибыль TP1: ${d.net_profit_tp1_usdt?.toFixed(2)}</div>
        <div>Ликвидация: ${d.liquidation_price?.toLocaleString()}</div>
      </div>
    </div>
  );
  return (
    <div style={{ margin: "4px 0" }}>
      <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>{col("OKX", okx)}{col("Bybit", bybit)}</div>
      <SignalCard sig={sig} />
    </div>
  );
}

function ChatMsg({ msg }) {
  const isUser = msg.role === "user";
  const sig = !isUser ? extractJSON(msg.content) : null;
  const txt = msg.content.replace(/```json[\s\S]*?```/g, "").trim();
  return (
    <div style={{ marginBottom: "0.75rem" }}>
      {isUser
        ? <div style={{ display: "flex", justifyContent: "flex-end" }}><div style={{ maxWidth: "80%", background: "var(--color-background-info)", borderRadius: "14px 14px 4px 14px", padding: "0.5rem 0.75rem", fontSize: 13, lineHeight: 1.6, color: "var(--color-text-info)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{msg.content}</div></div>
        : <div>{txt && <div style={{ maxWidth: "92%", background: "var(--color-background-secondary)", borderRadius: "14px 14px 14px 4px", padding: "0.5rem 0.75rem", fontSize: 13, lineHeight: 1.7, color: "var(--color-text-primary)", whiteSpace: "pre-wrap", wordBreak: "break-word", marginBottom: sig ? 4 : 0 }}>{txt}</div>}{sig && (sig.comparison ? <CompareCard sig={sig} /> : <SignalCard sig={sig} />)}</div>
      }
    </div>
  );
}

// ─── STAT CARD ────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, color }) {
  return (
    <div style={{ background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-md)", padding: "0.5rem 0.625rem", minWidth: 0 }}>
      <div style={{ fontSize: 9, color: "var(--color-text-tertiary)", marginBottom: 2, textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 500, color: color || "var(--color-text-primary)", lineHeight: 1.2 }}>{value}</div>
      {sub && <div style={{ fontSize: 9, color: "var(--color-text-secondary)", marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

function ExchangePanel({ data }) {
  if (!data) return <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", padding: "0.25rem" }}>—</div>;
  if (!data.ok) return <div style={{ fontSize: 11, color: "var(--color-text-danger)", padding: "0.25rem" }}>Ошибка: {data.error?.slice(0, 40)}</div>;
  const fr = parseFloat(data.funding_rate);
  const frStr = isNaN(fr) ? data.funding_rate : `${(fr * 100).toFixed(4)}%`;
  const frColor = isNaN(fr) ? undefined : fr > 0 ? "#e24b4a" : "#1D9E75";
  const chColor = (data.change24h || 0) >= 0 ? "#1D9E75" : "#e24b4a";
  const oi = parseFloat(data.open_interest);
  const oiStr = !isNaN(oi) && oi > 0 ? `${(oi / 1e9).toFixed(2)}B` : data.open_interest;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 4 }}>
      <StatCard label="Цена" value={`$${data.price?.toLocaleString()}`} sub={`${data.change24h >= 0 ? "▲" : "▼"} ${Math.abs(data.change24h || 0).toFixed(2)}%`} color={chColor} />
      <StatCard label="Funding" value={frStr} color={frColor} />
      <StatCard label="Спред" value={`${data.spread?.toFixed(4)}%`} />
      <StatCard label="OI" value={oiStr} />
    </div>
  );
}

// ─── TELEGRAM PANEL ───────────────────────────────────────────────────────────
function TelegramPanel({ deposit }) {
  const [tgToken, setTgToken] = useState("");
  const [tgChatId, setTgChatId] = useState("");
  const [riskPct, setRiskPct] = useState(1);
  const [monitorPairs, setMonitorPairs] = useState(["BTC/USDT", "ETH/USDT", "SOL/USDT"]);
  const [intervalMin, setIntervalMin] = useState(60);
  const [botRunning, setBotRunning] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [botLog, setBotLog] = useState([]);
  const [sendStatus, setSendStatus] = useState("");
  const [signalHistory, setSignalHistory] = useState([]);
  const [checkCount, setCheckCount] = useState(0);
  const [countdown, setCountdown] = useState(0);
  const [lastSignalKeys] = useState(new Set());
  const intervalRef = useRef(null);
  const countdownRef = useRef(null);
  const logRef = useRef(null);
  const checkCountRef = useRef(0);

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [botLog]);

  // countdown timer
  useEffect(() => {
    if (botRunning && countdown > 0) {
      countdownRef.current = setInterval(() => setCountdown(c => Math.max(0, c - 1)), 1000);
    } else {
      clearInterval(countdownRef.current);
    }
    return () => clearInterval(countdownRef.current);
  }, [botRunning, countdown]);

  const addLog = (msg, type = "info") => {
    const time = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setBotLog(prev => [...prev.slice(-79), { time, msg, type }]);
  };

  const testSend = async () => {
    if (!tgToken || !tgChatId) { setSendStatus("❌ Введи токен и Chat ID"); return; }
    setSendStatus("Отправка...");
    try {
      await sendTelegram(tgToken, tgChatId,
        `✅ <b>Крипто советник подключён!</b>\n\n🤖 Мониторинг: ${monitorPairs.join(", ")}\n⏱ Интервал: ${intervalMin} мин\n💰 Депозит: $${deposit} | Риск: ${riskPct}%\n\nОжидаю сигналов...`
      );
      setSendStatus("✅ Отправлено!");
    } catch (e) { setSendStatus(`❌ ${e.message.slice(0, 40)}`); }
    setTimeout(() => setSendStatus(""), 3000);
  };

  const runCheck = useCallback(async (isManual = false) => {
    if (scanning) return;
    setScanning(true);
    checkCountRef.current += 1;
    setCheckCount(checkCountRef.current);
    const activePairs = PAIRS.filter(p => monitorPairs.includes(p.label));
    addLog(`── Проверка #${checkCountRef.current} (${activePairs.length} пар) ──`, "info");

    for (const p of activePairs) {
      addLog(`⟳ Загрузка ${p.label}...`, "muted");
      try {
        const [o, b] = await Promise.all([fetchOKX(p, "15m"), fetchBybit(p, "15m")]);
        const analysis = analyzePairBot(o, b, deposit, riskPct);

        if (analysis.hasSignal && analysis.winner) {
          const wd = analysis.winner === "OKX" ? analysis.results.okx : analysis.results.bybit;
          const rival = analysis.winner === "OKX" ? analysis.results.bybit : analysis.results.okx;
          const rivalName = analysis.winner === "OKX" ? "Bybit" : "OKX";

          if (wd.rr >= 1.5 && wd.position_size_usdt >= 20) {
            const signalKey = `${p.label}_${analysis.winner}_${wd.entry}`;
            if (!lastSignalKeys.has(signalKey)) {
              lastSignalKeys.add(signalKey);
              // send to telegram
              const msg = formatTgSignal(p, analysis.winner, wd, riskPct, deposit);
              if (tgToken && tgChatId) {
                try {
                  await sendTelegram(tgToken, tgChatId, msg);
                  addLog(`✅ Сигнал отправлен: ${p.label} ${analysis.winner} ${wd.dir}`, "success");
                } catch (e) {
                  addLog(`❌ Ошибка отправки: ${e.message.slice(0, 50)}`, "error");
                }
              }
              // save to history
              setSignalHistory(prev => [{
                id: Date.now(),
                time: new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }),
                pair: p.label,
                winner: analysis.winner,
                winnerScore: wd.score,
                rivalName,
                rivalScore: rival?.score || 0,
                dir: wd.dir,
                entry: wd.entry,
                stop: wd.stop,
                liqPrice: wd.liqPrice,
                tps: wd.tps,
                rr: wd.rr,
                slPct: wd.slPct,
                leverage: wd.leverage,
                posSize: wd.position_size_usdt,
                margin: wd.margin_usdt,
                riskUsdt: wd.riskUsdt,
                fr: wd.fr,
                spread: wd.spread,
              }, ...prev].slice(0, 20));
            } else {
              addLog(`${p.label}: дубликат сигнала (пропущен)`, "muted");
            }
          } else {
            addLog(`${p.label}: слабый сигнал R/R=${wd.rr} поз=${wd.position_size_usdt}$`, "warn");
          }
        } else {
          addLog(`${p.label}: нет паттерна → пропуск`, "muted");
        }
      } catch (e) {
        addLog(`❌ Ошибка ${p.label}: ${e.message.slice(0, 50)}`, "error");
      }
      await new Promise(r => setTimeout(r, 600));
    }

    addLog(`── Готово. Следующая через ${intervalMin} мин ──`, "info");
    setCountdown(intervalMin * 60);
    setScanning(false);
  }, [scanning, monitorPairs, deposit, riskPct, intervalMin, tgToken, tgChatId, lastSignalKeys]);

  const startBot = () => {
    if (!tgToken || !tgChatId) { addLog("❌ Введи токен и Chat ID перед запуском", "error"); return; }
    setBotRunning(true);
    addLog("🚀 Бот запущен! Начинаю первую проверку...", "success");
    runCheck();
    intervalRef.current = setInterval(() => runCheck(), intervalMin * 60 * 1000);
  };

  const stopBot = () => {
    clearInterval(intervalRef.current);
    clearInterval(countdownRef.current);
    setBotRunning(false);
    setCountdown(0);
    addLog("🛑 Бот остановлен", "warn");
  };

  useEffect(() => () => { clearInterval(intervalRef.current); clearInterval(countdownRef.current); }, []);

  const logColor = { info: "var(--color-text-secondary)", success: "#1D9E75", error: "#e24b4a", warn: "#BA7517", muted: "var(--color-text-tertiary)" };

  const fmtCountdown = (s) => {
    const m = Math.floor(s / 60), sec = s % 60;
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  const numInput = (val, set, min, max, step) => (
    <input type="number" value={val} min={min} max={max} step={step} onChange={e => set(+e.target.value)}
      style={{ width: "100%", background: "var(--color-background-secondary)", border: "0.5px solid var(--color-border-secondary)", borderRadius: "var(--border-radius-md)", padding: "5px 8px", fontSize: 12, color: "var(--color-text-primary)", outline: "none", boxSizing: "border-box" }} />
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>

      {/* ── HOW TO SETUP ── */}
      <div style={{ background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-lg)", padding: "0.625rem 0.75rem", fontSize: 11, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
        <div style={{ fontWeight: 500, color: "var(--color-text-primary)", marginBottom: 4 }}>
          <i className="ti ti-help-circle" style={{ fontSize: 12, marginRight: 4 }} aria-hidden="true" />
          Как настроить Telegram бот
        </div>
        <div>1. Напиши <code style={{ background: "var(--color-background-primary)", padding: "1px 4px", borderRadius: 3 }}>@BotFather</code> → <code style={{ background: "var(--color-background-primary)", padding: "1px 4px", borderRadius: 3 }}>/newbot</code> → скопируй токен</div>
        <div>2. Напиши <code style={{ background: "var(--color-background-primary)", padding: "1px 4px", borderRadius: 3 }}>@userinfobot</code> → скопируй свой Chat ID</div>
        <div>3. Вставь токен и ID ниже → «Тест» → «Запустить»</div>
      </div>

      {/* ── CONNECTION ── */}
      <div style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "0.75rem" }}>
        <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 8, display: "flex", alignItems: "center", gap: 5 }}>
          <i className="ti ti-brand-telegram" style={{ fontSize: 14, color: "#229ED9" }} aria-hidden="true" />
          Подключение
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", width: 64, flexShrink: 0 }}>Bot Token</span>
            <input value={tgToken} onChange={e => setTgToken(e.target.value)} placeholder="110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
              style={{ flex: 1, background: "var(--color-background-secondary)", border: "0.5px solid var(--color-border-secondary)", borderRadius: "var(--border-radius-md)", padding: "5px 9px", fontSize: 12, color: "var(--color-text-primary)", outline: "none" }} />
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", width: 64, flexShrink: 0 }}>Chat ID</span>
            <input value={tgChatId} onChange={e => setTgChatId(e.target.value)} placeholder="123456789"
              style={{ flex: 1, background: "var(--color-background-secondary)", border: "0.5px solid var(--color-border-secondary)", borderRadius: "var(--border-radius-md)", padding: "5px 9px", fontSize: 12, color: "var(--color-text-primary)", outline: "none" }} />
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <button onClick={testSend} style={{ flex: 1, background: "transparent", border: "0.5px solid var(--color-border-secondary)", borderRadius: "var(--border-radius-md)", padding: "6px", fontSize: 12, cursor: "pointer", color: "var(--color-text-secondary)" }}>
              <i className="ti ti-send" style={{ fontSize: 12, marginRight: 4 }} aria-hidden="true" />Тест соединения
            </button>
            {sendStatus && <span style={{ fontSize: 11, color: sendStatus.startsWith("✅") ? "#1D9E75" : "#e24b4a", flexShrink: 0 }}>{sendStatus}</span>}
          </div>
        </div>
      </div>

      {/* ── SETTINGS ── */}
      <div style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "0.75rem" }}>
        <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 8 }}>
          <i className="ti ti-adjustments" style={{ fontSize: 13, marginRight: 4 }} aria-hidden="true" />
          Параметры
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginBottom: 3 }}>Интервал (мин)</div>
            {numInput(intervalMin, setIntervalMin, 5, 720, 5)}
          </div>
          <div>
            <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginBottom: 3 }}>Риск % депозита</div>
            {numInput(riskPct, setRiskPct, 0.1, 5, 0.1)}
          </div>
        </div>
        <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginBottom: 5 }}>Пары для мониторинга</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {PAIRS.map(p => {
            const active = monitorPairs.includes(p.label);
            return (
              <button key={p.label} onClick={() => !botRunning && setMonitorPairs(prev => active ? prev.filter(x => x !== p.label) : [...prev, p.label])}
                style={{ padding: "3px 10px", fontSize: 11, borderRadius: 20, border: `0.5px solid ${active ? "#1D9E75" : "var(--color-border-tertiary)"}`, background: active ? "#E1F5EE" : "transparent", color: active ? "#085041" : "var(--color-text-secondary)", cursor: botRunning ? "default" : "pointer", opacity: botRunning && !active ? 0.5 : 1 }}>
                {p.label}
              </button>
            );
          })}
        </div>
        <div style={{ marginTop: 8, fontSize: 10, color: "var(--color-text-tertiary)" }}>
          Депозит: <strong style={{ color: "var(--color-text-primary)" }}>${deposit}</strong> · Риск на сделку: <strong style={{ color: "#e24b4a" }}>${(deposit * riskPct / 100).toFixed(2)}</strong>
        </div>
      </div>

      {/* ── CONTROLS ── */}
      <div style={{ display: "flex", gap: 6 }}>
        <button onClick={botRunning ? stopBot : startBot}
          style={{ flex: 2, padding: "9px", fontSize: 13, fontWeight: 500, border: "none", borderRadius: "var(--border-radius-md)", cursor: "pointer", background: botRunning ? "#e24b4a" : "#1D9E75", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, transition: "opacity 0.15s" }}>
          <i className={`ti ti-${botRunning ? "player-stop-filled" : "player-play-filled"}`} style={{ fontSize: 14 }} aria-hidden="true" />
          {botRunning ? "Остановить бот" : "Запустить бот"}
        </button>
        <button onClick={() => runCheck(true)} disabled={scanning || botRunning}
          style={{ flex: 1, padding: "9px", fontSize: 12, border: "0.5px solid var(--color-border-secondary)", borderRadius: "var(--border-radius-md)", cursor: (scanning || botRunning) ? "default" : "pointer", background: "transparent", color: "var(--color-text-secondary)", opacity: (scanning || botRunning) ? 0.4 : 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 4 }}>
          <i className="ti ti-search" style={{ fontSize: 13, animation: scanning ? "spin 1s linear infinite" : "none" }} aria-hidden="true" />
          {scanning ? "Сканирую..." : "Проверить"}
        </button>
      </div>

      {/* ── STATUS BAR ── */}
      {(checkCount > 0 || botRunning) && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 5 }}>
          <StatCard label="Статус" value={botRunning ? (scanning ? "Скан..." : "Активен") : "Стоп"} color={botRunning ? "#1D9E75" : "var(--color-text-tertiary)"} />
          <StatCard label="Проверок" value={checkCount} />
          <StatCard label="Сигналов" value={signalHistory.length} color="#1D9E75" />
          <StatCard label="До след." value={countdown > 0 ? fmtCountdown(countdown) : "—"} />
        </div>
      )}

      {/* ── SIGNAL HISTORY ── */}
      {signalHistory.length > 0 && (
        <div style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "0.625rem 0.75rem" }}>
          <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span><i className="ti ti-history" style={{ fontSize: 12, marginRight: 4 }} aria-hidden="true" />История сигналов</span>
            <button onClick={() => setSignalHistory([])} style={{ fontSize: 10, background: "none", border: "none", cursor: "pointer", color: "var(--color-text-tertiary)" }}>очистить</button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 300, overflowY: "auto" }}>
            {signalHistory.map(s => {
              const isLong = s.dir === "LONG";
              const dc = isLong ? "#1D9E75" : "#e24b4a";
              return (
                <div key={s.id} style={{ background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-md)", padding: "0.5rem 0.625rem", borderLeft: `3px solid ${dc}` }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <span style={{ fontSize: 12, fontWeight: 500 }}>{s.pair}</span>
                      <span style={{ fontSize: 10, fontWeight: 500, color: dc, background: isLong ? "#E1F5EE" : "#FCEBEB", padding: "1px 6px", borderRadius: 10 }}>{s.dir} {s.leverage}x</span>
                      <span style={{ fontSize: 10, background: "var(--color-background-primary)", padding: "1px 6px", borderRadius: 10, color: "var(--color-text-secondary)" }}>{s.winner} ({s.winnerScore})</span>
                    </div>
                    <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>{s.time}</span>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 4, fontSize: 10 }}>
                    <div><span style={{ color: "var(--color-text-tertiary)" }}>Вход </span><strong>${s.entry}</strong></div>
                    <div><span style={{ color: "var(--color-text-tertiary)" }}>Стоп </span><strong style={{ color: "#e24b4a" }}>${s.stop}</strong></div>
                    <div><span style={{ color: "var(--color-text-tertiary)" }}>TP1 </span><strong style={{ color: "#1D9E75" }}>${s.tps?.[0]}</strong></div>
                    <div><span style={{ color: "var(--color-text-tertiary)" }}>R/R </span><strong>{s.rr}:1</strong></div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 4, fontSize: 10, marginTop: 3 }}>
                    <div><span style={{ color: "var(--color-text-tertiary)" }}>Позиция </span><strong>${s.posSize}</strong></div>
                    <div><span style={{ color: "var(--color-text-tertiary)" }}>Залог </span><strong>${s.margin}</strong></div>
                    <div><span style={{ color: "var(--color-text-tertiary)" }}>Риск </span><strong style={{ color: "#e24b4a" }}>${s.riskUsdt}</strong></div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── LOG ── */}
      <div style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "0.625rem 0.75rem" }}>
        <div style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)", marginBottom: 5, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span><i className="ti ti-terminal-2" style={{ fontSize: 11, marginRight: 4 }} aria-hidden="true" />Лог</span>
          <button onClick={() => setBotLog([])} style={{ fontSize: 10, background: "none", border: "none", cursor: "pointer", color: "var(--color-text-tertiary)" }}>очистить</button>
        </div>
        <div ref={logRef} style={{ height: 150, overflowY: "auto", fontFamily: "monospace", fontSize: 11, display: "flex", flexDirection: "column", gap: 1 }}>
          {botLog.length === 0
            ? <div style={{ color: "var(--color-text-tertiary)", padding: "0.25rem" }}>Лог пуст. Нажми «Проверить» или «Запустить».</div>
            : botLog.map((l, i) => (
              <div key={i} style={{ color: logColor[l.type] }}>
                <span style={{ color: "var(--color-text-tertiary)", marginRight: 6, userSelect: "none" }}>{l.time}</span>{l.msg}
              </div>
            ))
          }
        </div>
      </div>

      {/* ── WHAT BOT DOES ── */}
      <div style={{ background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-md)", padding: "0.5rem 0.625rem", fontSize: 10, color: "var(--color-text-tertiary)", lineHeight: 1.6 }}>
        <strong style={{ color: "var(--color-text-secondary)" }}>Алгоритм бота:</strong> Пин-бар (wick &gt; 2×body, wick &gt; 60% range) + объём +30% на 15м → ATR-стоп → ликвидация → позиция → R/R ≥ 1.5 и позиция ≥ 20$ → сигнал в Telegram. Дублирующиеся входы не отправляются.
      </div>
    </div>
  );
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────
export default function CryptoAdvisor() {
  const [pair, setPair] = useState(PAIRS[0]);
  const [tf, setTf] = useState("15m");
  const [deposit, setDeposit] = useState(1000);
  const [tab, setTab] = useState("advisor");
  const [mode, setMode] = useState("signal");
  const [okxData, setOkxData] = useState(null);
  const [bybitData, setBybitData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [lastFetch, setLastFetch] = useState(null);
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Добро пожаловать в крипто-советник!\n\nВыберите пару и таймфрейм, нажмите «Обновить» для загрузки рыночных данных.\n\n• Сигнал CoT — 10-шаговый анализ с точкой входа и JSON-сигналом\n• OKX vs Bybit — 12-шаговое сравнение бирж\n• Чат — свободные вопросы с данными в контексте\n• Telegram — автоматические сигналы в мессенджер" }
  ]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const chatRef = useRef(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [o, b] = await Promise.all([fetchOKX(pair, tf), fetchBybit(pair, tf)]);
    setOkxData(o); setBybitData(b); setLastFetch(new Date());
    setLoading(false);
  }, [pair, tf]);

  useEffect(() => { refresh(); }, [pair, tf]);
  useEffect(() => { if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight; }, [messages, thinking]);

  const sendMsg = async (override) => {
    const text = (override || input).trim();
    if (!text || thinking) return;
    setInput("");
    const history = [...messages, { role: "user", content: text }];
    setMessages(history);
    setThinking(true);
    try {
      const sys = buildSystem(okxData, bybitData, pair, tf, deposit, mode);
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "claude-sonnet-4-20250514", max_tokens: 1000,
          system: sys,
          messages: history.map(m => ({ role: m.role, content: m.content })),
        }),
      });
      const data = await res.json();
      const reply = data.content?.find(b => b.type === "text")?.text || "Нет ответа.";
      setMessages([...history, { role: "assistant", content: reply }]);
    } catch (e) { setMessages([...history, { role: "assistant", content: `Ошибка: ${e.message}` }]); }
    setThinking(false);
  };

  const quickByMode = {
    signal: [`Дай сигнал по ${pair.label}`, "Можно войти в LONG?", "Анализируй и дай точку входа"],
    compare: ["Сравни OKX и Bybit", "Где лучше открыть?", "Полное сравнение бирж"],
    chat: ["Объясни funding rate", "Оцени сентимент", "Риски для LONG", "Анализ спреда"],
  };

  const bothOk = okxData?.ok && bybitData?.ok;
  const priceDiff = bothOk ? Math.abs(okxData.price - bybitData.price) : 0;

  const tabBtn = (id, label, icon) => (
    <button onClick={() => setTab(id)} style={{ flex: 1, padding: "7px 4px", fontSize: 12, fontWeight: tab === id ? 500 : 400, background: tab === id ? "var(--color-background-primary)" : "transparent", border: tab === id ? "0.5px solid var(--color-border-secondary)" : "0.5px solid transparent", borderRadius: "var(--border-radius-md)", cursor: "pointer", color: tab === id ? "var(--color-text-primary)" : "var(--color-text-secondary)", display: "flex", alignItems: "center", justifyContent: "center", gap: 4, transition: "all 0.15s" }}>
      <i className={`ti ti-${icon}`} style={{ fontSize: 13 }} aria-hidden="true" />{label}
    </button>
  );

  const modeBtn = (m, l, ic) => (
    <button onClick={() => setMode(m)} style={{ flex: 1, padding: "6px 4px", fontSize: 11, fontWeight: mode === m ? 500 : 400, background: mode === m ? "var(--color-background-primary)" : "transparent", border: mode === m ? "0.5px solid var(--color-border-secondary)" : "0.5px solid transparent", borderRadius: "var(--border-radius-md)", cursor: "pointer", color: mode === m ? "var(--color-text-primary)" : "var(--color-text-secondary)", display: "flex", alignItems: "center", justifyContent: "center", gap: 4 }}>
      <i className={`ti ti-${ic}`} style={{ fontSize: 12 }} aria-hidden="true" />{l}
    </button>
  );

  return (
    <div style={{ fontFamily: "var(--font-sans)", maxWidth: 700, margin: "0 auto", padding: "0.75rem 0" }}>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.35}}.ci{width:100%;background:var(--color-background-secondary);border:0.5px solid var(--color-border-secondary);border-radius:var(--border-radius-lg);padding:0.5rem 0.75rem;font-size:13px;font-family:var(--font-sans);color:var(--color-text-primary);resize:none;outline:none;box-sizing:border-box}.ci:focus{border-color:var(--color-border-primary)}.sb{background:var(--color-text-primary);color:var(--color-background-primary);border:none;border-radius:10px;padding:7px 13px;font-size:13px;font-weight:500;cursor:pointer;flex-shrink:0}.sb:hover{opacity:0.85}.sb:disabled{opacity:0.35;cursor:default}.qb{background:var(--color-background-secondary);border:0.5px solid var(--color-border-tertiary);border-radius:20px;padding:3px 10px;font-size:11px;color:var(--color-text-secondary);cursor:pointer;white-space:nowrap;flex-shrink:0}.qb:hover{border-color:var(--color-border-primary);color:var(--color-text-primary)}`}</style>

      <h2 className="sr-only">Крипто советник OKX Bybit с Telegram ботом</h2>

      {/* HEADER */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.625rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <i className="ti ti-chart-candle" style={{ fontSize: 20 }} aria-hidden="true" />
          <div>
            <div style={{ fontSize: 14, fontWeight: 500 }}>Крипто советник</div>
            <div style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>OKX + Bybit · CoT · Telegram</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
          {lastFetch && <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>{lastFetch.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</span>}
          <button onClick={refresh} disabled={loading} style={{ display: "flex", alignItems: "center", gap: 4, background: "transparent", border: "0.5px solid var(--color-border-secondary)", borderRadius: "var(--border-radius-md)", padding: "5px 9px", fontSize: 11, color: "var(--color-text-secondary)", cursor: "pointer" }}>
            <i className="ti ti-refresh" style={{ fontSize: 12, animation: loading ? "spin 1s linear infinite" : "none" }} aria-hidden="true" />
            {loading ? "Загрузка..." : "Обновить"}
          </button>
        </div>
      </div>

      {/* CONTROLS */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: "0.625rem", padding: "0.5rem 0.625rem", background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-lg)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>Пара</span>
          <select value={pair.label} onChange={e => setPair(PAIRS.find(p => p.label === e.target.value))} style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-secondary)", borderRadius: "var(--border-radius-md)", padding: "4px 7px", fontSize: 11, color: "var(--color-text-primary)", cursor: "pointer", outline: "none" }}>
            {PAIRS.map(p => <option key={p.label}>{p.label}</option>)}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>ТФ</span>
          <select value={tf} onChange={e => setTf(e.target.value)} style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-secondary)", borderRadius: "var(--border-radius-md)", padding: "4px 7px", fontSize: 11, color: "var(--color-text-primary)", cursor: "pointer", outline: "none" }}>
            {TIMEFRAMES.map(t => <option key={t}>{t}</option>)}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>Депозит $</span>
          <input type="number" value={deposit} min={20} step={100} onChange={e => setDeposit(+e.target.value)} style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-secondary)", borderRadius: "var(--border-radius-md)", padding: "4px 7px", fontSize: 11, color: "var(--color-text-primary)", width: 72, outline: "none" }} />
        </div>
        <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginLeft: "auto" }}>
          Риск 1%: <strong style={{ color: "var(--color-text-primary)" }}>${(deposit * 0.01).toFixed(2)}</strong>
        </div>
      </div>

      {/* MARKET DATA */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: "0.5rem" }}>
        {["OKX", "Bybit"].map(name => {
          const d = name === "OKX" ? okxData : bybitData;
          return (
            <div key={name} style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "0.5rem 0.625rem" }}>
              <div style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)", marginBottom: 5, display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: d?.ok ? "#1D9E75" : "#e24b4a", display: "inline-block" }} />
                {name}
                {loading && <i className="ti ti-refresh" style={{ fontSize: 10, marginLeft: "auto", animation: "spin 1s linear infinite", color: "var(--color-text-tertiary)" }} aria-hidden="true" />}
              </div>
              <ExchangePanel data={d} />
            </div>
          );
        })}
      </div>

      {priceDiff > 5 && (
        <div style={{ background: "var(--color-background-warning)", border: "0.5px solid var(--color-border-warning)", borderRadius: "var(--border-radius-md)", padding: "4px 9px", fontSize: 11, color: "var(--color-text-warning)", marginBottom: "0.5rem", display: "flex", alignItems: "center", gap: 5 }}>
          <i className="ti ti-alert-triangle" style={{ fontSize: 11 }} aria-hidden="true" />
          Расхождение цен: <strong>${priceDiff.toFixed(2)}</strong> — возможен арбитраж
        </div>
      )}

      {/* MAIN TABS */}
      <div style={{ display: "flex", gap: 4, background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-lg)", padding: 4, marginBottom: "0.5rem" }}>
        {tabBtn("advisor", "AI Советник", "brain")}
        {tabBtn("telegram", "Telegram Бот", "brand-telegram")}
      </div>

      {/* ── ADVISOR TAB ── */}
      {tab === "advisor" && (
        <>
          <div style={{ display: "flex", gap: 3, background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-md)", padding: 3, marginBottom: "0.5rem" }}>
            {modeBtn("signal", "Сигнал CoT", "bolt")}
            {modeBtn("compare", "OKX vs Bybit", "scale")}
            {modeBtn("chat", "Чат", "message-circle")}
          </div>
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginBottom: "0.5rem", padding: "0 2px" }}>
            {mode === "signal" && "10 шагов CoT: биржа → техника → ATR-стоп → ликвидация → позиция с комиссиями → TP/RR ≥ 1.5 → JSON-сигнал"}
            {mode === "compare" && "12 шагов: детальный анализ OKX vs Bybit по ликвидности, комиссиям, безопасности, FR"}
            {mode === "chat" && "Свободный чат — все рыночные данные включены в контекст автоматически"}
          </div>
          <div style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", overflow: "hidden" }}>
            <div ref={chatRef} style={{ height: 360, overflowY: "auto", padding: "0.75rem", display: "flex", flexDirection: "column" }}>
              {messages.map((m, i) => <ChatMsg key={i} msg={m} />)}
              {thinking && (
                <div style={{ display: "flex", gap: 3, padding: "0.25rem 0", alignItems: "center" }}>
                  <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginRight: 4 }}>
                    {mode === "signal" ? "Выполняю 10 шагов CoT..." : mode === "compare" ? "Сравниваю биржи (12 шагов)..." : "Анализирую..."}
                  </span>
                  {[0, 0.2, 0.4].map((d, i) => <span key={i} style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--color-text-tertiary)", display: "inline-block", animation: `pulse 1.2s ${d}s ease-in-out infinite` }} />)}
                </div>
              )}
            </div>
            <div style={{ borderTop: "0.5px solid var(--color-border-tertiary)", padding: "0.5rem 0.625rem" }}>
              <div style={{ display: "flex", gap: 4, overflowX: "auto", paddingBottom: 5, marginBottom: 5, scrollbarWidth: "none" }}>
                {quickByMode[mode].map((q, i) => <button key={i} className="qb" onClick={() => sendMsg(q)}>{q}</button>)}
              </div>
              <div style={{ display: "flex", gap: 5 }}>
                <textarea className="ci" rows={2} value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); } }} placeholder={mode === "signal" ? "Запросить сигнал... (Enter)" : mode === "compare" ? "Сравнить биржи... (Enter)" : "Вопрос по рынку... (Enter)"} />
                <button className="sb" onClick={() => sendMsg()} disabled={thinking || !input.trim()}>
                  <i className="ti ti-send" style={{ fontSize: 14 }} aria-hidden="true" />
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* ── TELEGRAM TAB ── */}
      {tab === "telegram" && (
        <TelegramPanel deposit={deposit} />
      )}

      <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", textAlign: "center", marginTop: "0.5rem" }}>
        Не является финансовой рекомендацией · Торговля с плечом несёт высокий риск потери средств
      </div>
    </div>
  );
}
