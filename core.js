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

/* ---------- 스캐너 판정 ----------
   dir: "long"(상방) / "short"(하방)
   u:   24시간 통계 { chgRate }
   f:   가격 표기 함수 (원/달러 단위를 붙여준다)

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

  let score = 0; const reasons = [];

  if (tBreak) { score += 3; reasons.push(long ? `직전 20봉 고점 ${f(hi20)} 상향 돌파` : `직전 20봉 저점 ${f(lo20)} 하향 이탈`); }
  if (tVolty) { score += 2; reasons.push(long ? `변동성 돌파선 ${f(kUp)} 상향 (시가 + 전봉 변동폭×0.5)` : `변동성 이탈선 ${f(kDn)} 하향`); }

  if (volRatio >= 4) { score += 3; reasons.push(`거래량 폭증 ${volRatio.toFixed(1)}배 (20봉 평균 대비, 최근 3봉 최대)`); }
  else if (volRatio >= 2) { score += 2; reasons.push(`거래량 급증 ${volRatio.toFixed(1)}배`); }
  else if (volRatio >= 1.3) { score += 1; reasons.push(`거래량 ${volRatio.toFixed(1)}배`); }
  else reasons.push(`!거래량 ${volRatio.toFixed(1)}배 — 뒷받침이 약한 움직임`);

  if (tMove) { score += 1; reasons.push(`24시간 ${chg >= 0 ? "+" : ""}${chg.toFixed(1)}% 변동`); }

  if (ma20[i] != null && ma60[i] != null) {
    if (long && price > ma20[i] && ma20[i] > ma60[i]) { score += 2; reasons.push(`정배열 (종가 > MA20 ${f(ma20[i])} > MA60 ${f(ma60[i])})`); }
    if (!long && price < ma20[i] && ma20[i] < ma60[i]) { score += 2; reasons.push(`역배열 (종가 < MA20 ${f(ma20[i])} < MA60 ${f(ma60[i])})`); }
  }

  for (let b = 0; b < 3; b++) {
    const a = i - b, p = a - 1;
    if (m.line[a] == null || m.line[p] == null || m.sig[p] == null) break;
    if (long && m.line[a] > m.sig[a] && m.line[p] <= m.sig[p]) { score += 2; reasons.push(`MACD 골든크로스 (${b === 0 ? "직전 봉" : b + "봉 전"})`); break; }
    if (!long && m.line[a] < m.sig[a] && m.line[p] >= m.sig[p]) { score += 2; reasons.push(`MACD 데드크로스 (${b === 0 ? "직전 봉" : b + "봉 전"})`); break; }
  }

  const rv = r[i];
  if (rv != null) {
    if (long) {
      if (rv >= 80) { score -= 2; reasons.push(`!RSI ${rv.toFixed(0)} 과열 — 이미 많이 간 자리, 추격 위험`); }
      else if (rv >= 55) { score += 1; reasons.push(`RSI ${rv.toFixed(0)} 상승 우위`); }
    } else {
      if (rv <= 20) { score -= 2; reasons.push(`!RSI ${rv.toFixed(0)} 침체 — 반등 위험`); }
      else if (rv <= 45) { score += 1; reasons.push(`RSI ${rv.toFixed(0)} 하락 우위`); }
    }
  }

  if (score < 5) return null;   // 조건 한둘 걸친 정도는 후보로 치지 않는다

  // 손절 기준과 손익비 — 진입 논리보다 먼저 나와야 하는 숫자
  const { s1, r1 } = srLevels(cs, price);
  const stop = long ? (s1 ? s1.price : lo20) : (r1 ? r1.price : hi20);
  const tgt  = long ? (r1 ? r1.price : hi20) : (s1 ? s1.price : lo20);
  const risk = Math.abs(price - stop), reward = Math.abs(tgt - price);
  const rr = risk > 0 ? reward / risk : null;
  if (rr == null || rr < 1) return null;   // 목표보다 손절이 먼 자리는 검토 가치가 없다

  return { score, reasons, price, rsi: rv, volRatio, stop, tgt, rr };
}

// Node(scan.js)에서 쓸 때만 내보낸다. 브라우저에서는 그냥 전역 함수로 남는다.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { STABLE, sma, ema, rsi, macd, findPivots, srLevels, scanScore };
}
