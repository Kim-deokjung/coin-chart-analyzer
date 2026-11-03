/* ============================================================
   core.js — 지표·판정 계산 (화면과 무관한 순수 계산만)

   웹페이지(index.html)와 자동 스캔 스크립트(scan.js)가 이 파일을 함께 쓴다.
   같은 코드를 쓰므로 두 곳의 숫자가 어긋나지 않는다.
   ============================================================ */

// 스테이블코인·법정화폐 토큰은 시세가 고정이라 추세 분석 대상이 아니다
const STABLE = /^(USDT|USDC|USD1|USDE|USDP|USDD|USDS|DAI|TUSD|BUSD|FDUSD|PYUSD|XUSD|EUR|EURI|AEUR|GBP|JPY|TRY|BRL|AUD|테더|테더유에스디)$/;

/* ---------- 지표 ---------- */
function sma(arr, p) {
  const out = new Array(arr.length).fill(null); let s = 0;
  for (let i = 0; i < arr.length; i++) { s += arr[i]; if (i >= p) s -= arr[i - p]; if (i >= p - 1) out[i] = s / p; }
  return out;
}
function ema(arr, p) {
  const out = new Array(arr.length).fill(null); const k = 2 / (p + 1); let prev = null;
  for (let i = 0; i < arr.length; i++) {
    if (arr[i] == null) { out[i] = prev; continue; }
    prev = prev == null ? arr[i] : arr[i] * k + prev * (1 - k); out[i] = prev;
  }
  return out;
}
function rsi(closes, p = 14) {
  const out = new Array(closes.length).fill(null); let g = 0, l = 0;
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1]; const up = Math.max(d, 0), dn = Math.max(-d, 0);
    if (i <= p) { g += up; l += dn; if (i === p) { g /= p; l /= p; out[i] = 100 - 100 / (1 + (l === 0 ? 100 : g / l)); } }
    else { g = (g * (p - 1) + up) / p; l = (l * (p - 1) + dn) / p; out[i] = 100 - 100 / (1 + (l === 0 ? 100 : g / l)); }
  }
  return out;
}
function macd(closes) {
  const e12 = ema(closes, 12), e26 = ema(closes, 26);
  const line = closes.map((_, i) => (e12[i] != null && e26[i] != null && i >= 25) ? e12[i] - e26[i] : null);
  const sig = ema(line.map(v => v), 9);
  const hist = line.map((v, i) => (v != null && sig[i] != null && i >= 33) ? v - sig[i] : null);
  return { line: line.map((v, i) => i >= 25 ? v : null), sig: sig.map((v, i) => i >= 33 ? v : null), hist };
}

/* ---------- 피벗(가격이 방향을 바꾼 지점) ---------- */
function findPivots(cs, k = 3) {
  const highs = [], lows = [];
  for (let i = k; i < cs.length - k; i++) {
    let ph = true, pl = true;
    for (let j = 1; j <= k; j++) {
      if (cs[i].high <= cs[i - j].high || cs[i].high < cs[i + j].high) ph = false;
      if (cs[i].low >= cs[i - j].low || cs[i].low > cs[i + j].low) pl = false;
    }
    if (ph) highs.push({ i, price: cs[i].high });
    if (pl) lows.push({ i, price: cs[i].low });
  }
  return { highs, lows };
}

/* ---------- 지지/저항: 피벗을 가격대별로 묶는다 ---------- */
function srLevels(cs, price) {
  const { highs, lows } = findPivots(cs, 3);
  const pts = [...highs, ...lows].map(p => ({ price: p.price })).sort((a, b) => a.price - b.price);
  const bin = price * 0.007;
  const clusters = [];
  for (const p of pts) {
    const c = clusters[clusters.length - 1];
    if (c && p.price - c.max <= bin) { c.sum += p.price; c.n++; c.max = p.price; }
    else clusters.push({ sum: p.price, n: 1, max: p.price });
  }
  const levels = clusters.map(c => ({ price: c.sum / c.n, touches: c.n }));
  const below = levels.filter(l => l.price < price * 0.997).sort((a, b) => b.price - a.price);
  const above = levels.filter(l => l.price > price * 1.003).sort((a, b) => a.price - b.price);
  // dir=+1 저항(위로 멀어짐), dir=-1 지지(아래로 멀어짐). 2차는 반드시 1차보다 현재가에서 먼 쪽이어야 한다.
  const pick = (arr, dir) => {
    const first = arr.filter(l => l.touches >= 2)[0] || arr[0] || null;
    let second = null;
    if (first) {
      const farther = arr.filter(l => l !== first &&
        Math.abs(l.price - first.price) > price * 0.01 &&
        (dir > 0 ? l.price > first.price : l.price < first.price));
      second = farther.filter(l => l.touches >= 2)[0] || farther[0] || null;
    }
    return [first, second];
  };
  const [s1, s2] = pick(below, -1), [r1, r2] = pick(above, +1);
  return { s1, s2, r1, r2 };
}

/* ---------- 업비트 유의·주의 딱지 ----------
   market/all?isDetails=true 응답의 market_event 를 { warning, cautions[] } 로 바꾼다.
   warning  = 거래유의 종목 (상장폐지 심사 가능성 → 스캔에서 제외)
   cautions = 주의 종목 사유 목록 (감점). 구버전 응답(market_warning)도 받아준다. */
const CAUTION_KO = {
  PRICE_FLUCTUATIONS: "가격 급등락", TRADING_VOLUME_SOARING: "거래량 급등", DEPOSIT_AMOUNT_SOARING: "입금량 급등",
  GLOBAL_PRICE_DIFFERENCES: "해외 가격 차이", CONCENTRATION_OF_SMALL_ACCOUNTS: "소수 계정 집중",
};
function upbitRisk(m) {
  const ev = (m && m.market_event) || {};
  const warning = !!ev.warning || (m && m.market_warning === "WARNING");
  const cautions = Object.entries(ev.caution || {}).filter(([, v]) => v).map(([k]) => CAUTION_KO[k] || k);
  if (m && m.market_warning === "CAUTION" && !cautions.length) cautions.push("주의");
  return { warning, cautions };
}

/* ---------- 체결강도 (Flow 차원의 재료) ----------
   최근 체결 내역에서 "사는 쪽이 먼저 달려든 체결"과 "파는 쪽이 먼저 달려든 체결"의
   금액을 나눈다. 100이면 균형, 150이면 매수 체결이 매도의 1.5배.
   호가창과 달리 체결은 취소할 수 없는 사실이라, 가짜 주문에 속지 않는다.

   ticks: [{ price, volume, takerBuy(bool), ts(ms) }]  최근 것이 뒤에 오든 앞에 오든 무관
   windowMin: 몇 분치만 볼지 (기본 30분). 체결이 그보다 적으면 있는 만큼으로 계산.
   반환: { strength, buyKrw, sellKrw, n, minutes } 또는 체결이 없으면 null */
function tradeStrength(ticks, windowMin = 30) {
  if (!ticks || !ticks.length) return null;
  const newest = Math.max(...ticks.map(t => t.ts));
  const since = newest - windowMin * 60000;
  let buy = 0, sell = 0, n = 0, oldest = newest;
  for (const t of ticks) {
    if (t.ts < since) continue;
    const krw = t.price * t.volume;
    if (t.takerBuy) buy += krw; else sell += krw;
    n++; if (t.ts < oldest) oldest = t.ts;
  }
  if (n === 0 || buy + sell === 0) return null;
  const strength = sell === 0 ? 999 : buy / sell * 100;
  return { strength: Math.min(strength, 999), buyKrw: buy, sellKrw: sell, n, minutes: Math.max(1, Math.round((newest - oldest) / 60000)) };
}

/* ---------- 스캐너 판정 ----------
   dir: "long"(상방) / "short"(하방)
   u:   24시간 통계 { chgRate, strength?, risk? }
        strength: tradeStrength() 결과 (없으면 체결강도 항목은 "미조회"로 표시)
        risk:     { warning: bool, cautions: [문자열...] } 거래소가 붙인 유의·주의 딱지
   f:   가격 표기 함수 (원/달러 단위를 붙여준다)

   점수는 네 차원으로 나눠 낸다 (전문 분석 서비스들이 쓰는 구조와 같다):
     move  움직임   — 가격이 평소와 다르게 움직이는가 (돌파·추세·모멘텀)
     flow  자금흐름 — 돈이 실제로 들어오는가 (거래량 배수·체결강도)
     deriv 파생     — 선물 시장 상태 (아직 미연동, 빈칸)
     attn  관심     — 소셜·검색량 (아직 미연동, 빈칸)
   여기에 거래소 유의·주의 딱지를 감점으로 더한다.

   반환값이 null이면 후보 아님. 점수는 "동시에 성립한 조건의 수"일 뿐
   수익 가능성이 아니며, 매매 신호도 아니다. */
function scanScore(cs, dir, u, f) {
  if (!cs || cs.length < 60) return null;
  const closes = cs.map(c => c.close), vols = cs.map(c => c.volume);
  const i = cs.length - 1, j = i - 1;            // i=진행 중인 봉, j=직전 완성봉
  const price = closes[i];
  const ma20 = sma(closes, 20), ma60 = sma(closes, 60);
  const volMa = sma(vols, 20), r = rsi(closes), m = macd(closes);
  const long = dir === "long";

  // 거래유의 종목은 상장폐지 심사 단계일 수 있어 아예 후보에서 뺀다
  const risk = (u && u.risk) || { warning: false, cautions: [] };
  if (risk.warning) return null;

  // 거래량은 직전 3개 완성봉 중 최대치로 본다 — 급등은 몇 봉 전에 터졌을 수 있다
  let volRatio = 0;
  for (let b = 1; b <= 3; b++) {
    const k = i - b;
    if (k >= 0 && volMa[k]) volRatio = Math.max(volRatio, vols[k] / volMa[k]);
  }
  const win = cs.slice(-21, -1);                 // 직전 20봉 (진행 중인 봉 제외)
  const hi20 = Math.max(...win.map(c => c.high));
  const lo20 = Math.min(...win.map(c => c.low));
  const prev = cs[j];
  const kUp = cs[i].open + (prev.high - prev.low) * 0.5;   // 변동성 돌파 기준선
  const kDn = cs[i].open - (prev.high - prev.low) * 0.5;
  const chg = u ? u.chgRate : 0;

  // ── 1차 트리거: 지금 실제로 뭔가 벌어지고 있는가.
  //    하나도 없으면 이평선·RSI가 아무리 예뻐도 후보로 보지 않는다.
  const tBreak = long ? price > hi20 : price < lo20;
  const tVolty = long ? price > kUp : price < kDn;
  const tVol   = volRatio >= 2;
  const tMove  = long ? chg >= 8 : chg <= -8;
  if (!(tBreak || tVolty || tVol || tMove)) return null;

  const move  = { label: "움직임",   score: 0, reasons: [] };
  const flow  = { label: "자금흐름", score: 0, reasons: [] };
  const deriv = { label: "파생",     score: null, reasons: ["선물 데이터 미연동 (빈칸)"] };
  const attn  = { label: "관심",     score: null, reasons: ["소셜·검색량 미연동 (빈칸)"] };
  const riskD = { label: "위험",     score: 0, reasons: [] };

  // ── 움직임: 가격이 평소와 다르게 움직이는가
  if (tBreak) { move.score += 3; move.reasons.push(long ? `직전 20봉 고점 ${f(hi20)} 상향 돌파` : `직전 20봉 저점 ${f(lo20)} 하향 이탈`); }
  if (tVolty) { move.score += 2; move.reasons.push(long ? `변동성 돌파선 ${f(kUp)} 상향 (시가 + 전봉 변동폭×0.5)` : `변동성 이탈선 ${f(kDn)} 하향`); }
  if (tMove)  { move.score += 1; move.reasons.push(`24시간 ${chg >= 0 ? "+" : ""}${chg.toFixed(1)}% 변동`); }

  if (ma20[i] != null && ma60[i] != null) {
    if (long && price > ma20[i] && ma20[i] > ma60[i]) { move.score += 2; move.reasons.push(`정배열 (종가 > MA20 ${f(ma20[i])} > MA60 ${f(ma60[i])})`); }
    if (!long && price < ma20[i] && ma20[i] < ma60[i]) { move.score += 2; move.reasons.push(`역배열 (종가 < MA20 ${f(ma20[i])} < MA60 ${f(ma60[i])})`); }
  }

  for (let b = 0; b < 3; b++) {
    const a = i - b, p = a - 1;
    if (m.line[a] == null || m.line[p] == null || m.sig[p] == null) break;
    if (long && m.line[a] > m.sig[a] && m.line[p] <= m.sig[p]) { move.score += 2; move.reasons.push(`MACD 골든크로스 (${b === 0 ? "직전 봉" : b + "봉 전"})`); break; }
    if (!long && m.line[a] < m.sig[a] && m.line[p] >= m.sig[p]) { move.score += 2; move.reasons.push(`MACD 데드크로스 (${b === 0 ? "직전 봉" : b + "봉 전"})`); break; }
  }

  const rv = r[i];
  if (rv != null) {
    if (long) {
      if (rv >= 80) { move.score -= 2; move.reasons.push(`!RSI ${rv.toFixed(0)} 과열 — 이미 많이 간 자리, 추격 위험`); }
      else if (rv >= 55) { move.score += 1; move.reasons.push(`RSI ${rv.toFixed(0)} 상승 우위`); }
    } else {
      if (rv <= 20) { move.score -= 2; move.reasons.push(`!RSI ${rv.toFixed(0)} 침체 — 반등 위험`); }
      else if (rv <= 45) { move.score += 1; move.reasons.push(`RSI ${rv.toFixed(0)} 하락 우위`); }
    }
  }

  // ── 자금흐름: 돈이 실제로 들어오는가
  if (volRatio >= 4) { flow.score += 3; flow.reasons.push(`거래량 폭증 ${volRatio.toFixed(1)}배 (20봉 평균 대비, 최근 3봉 최대)`); }
  else if (volRatio >= 2) { flow.score += 2; flow.reasons.push(`거래량 급증 ${volRatio.toFixed(1)}배`); }
  else if (volRatio >= 1.3) { flow.score += 1; flow.reasons.push(`거래량 ${volRatio.toFixed(1)}배`); }
  else flow.reasons.push(`!거래량 ${volRatio.toFixed(1)}배 — 뒷받침이 약한 움직임`);

  // 체결강도: 매수 체결 금액 ÷ 매도 체결 금액 × 100. 취소 불가능한 "사실" 기반.
  const st = u && u.strength;
  let strength = null;
  if (st && st.strength != null) {
    strength = st.strength;
    const v = strength.toFixed(0), w = `최근 ${st.minutes}분·${st.n}건`;
    // 상방이면 매수 우위(>100)가 힘, 하방이면 매도 우위(<100)가 힘 — 같은 기준을 뒤집어 쓴다
    const s = long ? strength : (strength === 0 ? 999 : 10000 / strength);
    if (s >= 150)      { flow.score += 2; flow.reasons.push(`체결강도 ${v} — ${long ? "매수" : "매도"} 체결이 1.5배 이상 (${w})`); }
    else if (s >= 120) { flow.score += 1; flow.reasons.push(`체결강도 ${v} — ${long ? "매수" : "매도"} 체결 우위 (${w})`); }
    else if (s < 80)   { flow.score -= 1; flow.reasons.push(`!체결강도 ${v} — ${long ? "매도" : "매수"} 체결이 더 많음, 움직임과 반대 방향 (${w})`); }
    else flow.reasons.push(`체결강도 ${v} — 균형 (${w})`);
  } else flow.reasons.push(`체결강도 미조회`);

  // ── 위험: 거래소가 붙인 주의 딱지는 감점. (거래유의는 위에서 이미 제외)
  if (risk.cautions && risk.cautions.length) {
    riskD.score -= 2;
    riskD.reasons.push(`!거래소 주의 종목 — ${risk.cautions.join(", ")}`);
  }

  const score = move.score + flow.score + riskD.score;
  if (score < 5) return null;   // 조건 한둘 걸친 정도는 후보로 치지 않는다

  // 손절 기준과 손익비 — 진입 논리보다 먼저 나와야 하는 숫자
  const { s1, r1 } = srLevels(cs, price);
  const stop = long ? (s1 ? s1.price : lo20) : (r1 ? r1.price : hi20);
  const tgt  = long ? (r1 ? r1.price : hi20) : (s1 ? s1.price : lo20);
  const risk_ = Math.abs(price - stop), reward = Math.abs(tgt - price);
  const rr = risk_ > 0 ? reward / risk_ : null;
  if (rr == null || rr < 1) return null;   // 목표보다 손절이 먼 자리는 검토 가치가 없다

  const dims = { move, flow, deriv, attn, risk: riskD };
  // reasons는 예전 형식과의 호환용 — 차원 순서대로 평평하게 펼친다
  const reasons = [...move.reasons, ...flow.reasons, ...riskD.reasons];
  return { score, dims, reasons, price, rsi: rv, volRatio, strength, stop, tgt, rr };
}

// Node(scan.js)에서 쓸 때만 내보낸다. 브라우저에서는 그냥 전역 함수로 남는다.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { STABLE, sma, ema, rsi, macd, findPivots, srLevels, upbitRisk, tradeStrength, scanScore };
}
