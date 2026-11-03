#!/usr/bin/env node
/* ============================================================
   evaluate.js — 지난 스캔 신호가 실제로 어떻게 됐는지 센다 (승률·기대값)

   자동 스캔이 30분마다 scan.json 을 커밋으로 남기므로, git 기록을 거슬러
   올라가면 "언제 어떤 종목이 무슨 가격·손절·목표로 포착됐는지"가 전부 남아 있다.
   이 스크립트는 그 신호마다 이후 1시간봉을 받아와서

     - 목표가에 먼저 닿았나 (이김)  / 손절가에 먼저 닿았나 (짐)
     - 둘 다 못 닿고 24봉이 지났나 (시간 종료 → 그 시점 종가로 정산)

   를 판정하고, 거래소·방향·점수대별 승률과 기대값(R 단위)을 낸다.

   R = 손절까지의 거리를 1로 놓은 손익. 목표 도달이면 +손익비, 손절이면 -1.
   수수료는 R 단위로 빼서 반영한다 (업비트 0.05%×2, 바이낸스 0.1%×2).

   결과: eval.json (화면이 읽음) + 표준출력 요약.
   실행: node evaluate.js            (GitHub Actions 에서 돌리는 것이 기본 — 거래소 접속 필요)
   ============================================================ */
const { execSync } = require("child_process");
const fs = require("fs");

const HOLD_BARS = +(process.env.EVAL_HOLD || 24);     // 최대 보유 봉 수 (1시간봉 기준 = 24시간)
const MAX_SIGNALS = +(process.env.EVAL_MAX || 400);   // 안전장치: 너무 많으면 최근 것부터 이만큼만
const FEE = { upbit: 0.0005, binance: 0.001 };        // 편도 수수료율
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function getJson(url, tries = 3) {
  let err;
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url, { headers: { "User-Agent": "coin-chart-analyzer-eval/1.0" } });
      if (r.status === 429) { await sleep(1500 * (i + 1)); continue; }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch (e) { err = e; await sleep(800 * (i + 1)); }
  }
  throw err;
}

/* ---------- 1) git 기록에서 신호 꺼내기 ---------- */
function loadSnapshots() {
  const shas = execSync("git log --format=%H -- scan.json", { encoding: "utf8" }).trim().split("\n").filter(Boolean).reverse();
  const snaps = [];
  for (const sha of shas) {
    try {
      const d = JSON.parse(execSync(`git show ${sha}:scan.json`, { encoding: "utf8", maxBuffer: 64 << 20 }));
      if (d && d.generatedAt && d.exchanges) snaps.push(d);
    } catch (e) { /* 깨진 커밋은 건너뜀 */ }
  }
  return snaps;
}

/* 같은 종목이 연속 스캔에 계속 떠 있으면 한 신호로 본다 — 직전 스캔에 없다가 나타난 순간만 "신호" */
function extractSignals(snaps) {
  const prev = {};            // key: ex|dir → Set(sym)
  const out = [];
  for (const s of snaps) {
    for (const [ex, v] of Object.entries(s.exchanges)) {
      for (const dir of ["long", "short"]) {
        const r = v && v[dir]; if (!r || !r.hits) continue;
        const key = `${ex}|${dir}`, before = prev[key] || new Set(), now = new Set();
        for (const h of r.hits) {
          now.add(h.sym);
          if (before.has(h.sym)) continue;
          if (!(h.price > 0 && h.stop > 0 && h.tgt > 0)) continue;
          out.push({ at: s.generatedAt, tf: s.tf || "m60", ex, dir, sym: h.sym, name: h.name, score: h.score,
                     price: h.price, stop: h.stop, tgt: h.tgt, rr: h.rr });
        }
        prev[key] = now;
      }
    }
  }
  return out;
}

/* ---------- 2) 신호 이후 캔들 ---------- */
const TF_MIN = { m15: 15, m60: 60, m240: 240, day: 1440 };
const EX = {
  upbit: {
    gap: 120,
    async after(sym, tf, fromMs, n) {
      const min = TF_MIN[tf], path = tf === "day" ? "/candles/days" : `/candles/minutes/${min}`;
      const to = new Date(fromMs + (n + 1) * min * 60000).toISOString().replace(/\.\d{3}Z$/, "Z");
      const raw = await getJson(`https://api.upbit.com/v1${path}?market=${sym}&to=${to}&count=${n + 1}`);
      return raw.map(c => ({ t: Date.parse(c.candle_date_time_utc + "Z"), o: c.opening_price, h: c.high_price, l: c.low_price, c: c.trade_price }))
                .filter(c => c.t > fromMs).sort((a, b) => a.t - b.t).slice(0, n);
    },
  },
  binance: {
    gap: 60, hosts: ["https://api.binance.com", "https://data-api.binance.vision"], host: null,
    async pick() {
      if (this.host) return this.host;
      for (const h of this.hosts) { try { const r = await fetch(`${h}/api/v3/ping`); if (r.ok) return (this.host = h); } catch (e) {} }
      throw new Error("바이낸스 접속 불가");
    },
    async after(sym, tf, fromMs, n) {
      const iv = { m15: "15m", m60: "1h", m240: "4h", day: "1d" }[tf], h = await this.pick();
      const raw = await getJson(`${h}/api/v3/klines?symbol=${sym}&interval=${iv}&startTime=${fromMs}&limit=${n + 1}`);
      return raw.map(k => ({ t: +k[0], o: +k[1], h: +k[2], l: +k[3], c: +k[4] })).filter(c => c.t > fromMs).slice(0, n);
    },
  },
};

/* ---------- 3) 한 신호의 결과 ----------
   신호 봉(진행 중이던 봉)은 건너뛰고 그다음 봉부터 본다. 같은 봉에서 손절·목표를 둘 다 건드리면
   어느 쪽이 먼저인지 알 수 없으므로 보수적으로 "손절"로 친다. */
function settle(sig, bars) {
  const long = sig.dir === "long";
  const risk = Math.abs(sig.price - sig.stop);
  if (!(risk > 0) || !bars.length) return null;
  const fee2 = FEE[sig.ex] * 2;                     // 진입+청산
  const feeR = fee2 * sig.price / risk;            // 수수료를 R 단위로
  let outcome = "time", exit = bars[bars.length - 1].c, barsHeld = bars.length;
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const hitStop = long ? b.l <= sig.stop : b.h >= sig.stop;
    const hitTgt  = long ? b.h >= sig.tgt  : b.l <= sig.tgt;
    if (hitStop) { outcome = "stop"; exit = sig.stop; barsHeld = i + 1; break; }   // 둘 다면 손절 우선(보수적)
    if (hitTgt)  { outcome = "target"; exit = sig.tgt; barsHeld = i + 1; break; }
  }
  const raw = (long ? exit - sig.price : sig.price - exit) / risk;
  const ret4 = bars[3] ? (long ? bars[3].c / sig.price - 1 : 1 - bars[3].c / sig.price) * 100 : null;
  const ret24 = bars[23] ? (long ? bars[23].c / sig.price - 1 : 1 - bars[23].c / sig.price) * 100 : null;
  return { outcome, barsHeld, R: raw - feeR, rawR: raw, ret4, ret24, bars: bars.length };
}

/* ---------- 4) 집계 ---------- */
function summarize(rows) {
  const g = {};
  const add = (key, r) => {
    const s = g[key] || (g[key] = { n: 0, target: 0, stop: 0, time: 0, sumR: 0, wins: 0, sumRet24: 0, nRet24: 0 });
    s.n++; s[r.outcome]++; s.sumR += r.R; if (r.R > 0) s.wins++;
    if (r.ret24 != null) { s.sumRet24 += r.ret24; s.nRet24++; }
  };
  for (const r of rows) {
    add("전체", r); add(`${r.ex}|${r.dir}`, r);
    add(`점수 ${r.score >= 9 ? "9+" : r.score >= 7 ? "7-8" : "5-6"}`, r);
  }
  const order = ["전체", "upbit|long", "upbit|short", "binance|long", "binance|short", "점수 5-6", "점수 7-8", "점수 9+"];
  const out = {};
  for (const k of order) if (g[k]) { const s = g[k]; out[k] = {
    n: s.n, 목표도달: s.target, 손절: s.stop, 시간종료: s.time,
    승률: +(s.wins / s.n * 100).toFixed(1),
    기대값R: +(s.sumR / s.n).toFixed(3),
    누적R: +s.sumR.toFixed(2),
    평균24봉수익률: s.nRet24 ? +(s.sumRet24 / s.nRet24).toFixed(2) : null,
  }; }
  return out;
}

/* ---------- main ---------- */
(async () => {
  const snaps = loadSnapshots();
  let signals = extractSignals(snaps);
  const now = Date.now();
  // 아직 HOLD_BARS 봉이 다 지나지 않은 최근 신호는 결과가 확정되지 않았으므로 제외
  signals = signals.filter(s => now - Date.parse(s.at) >= (HOLD_BARS + 1) * TF_MIN[s.tf] * 60000);
  if (signals.length > MAX_SIGNALS) signals = signals.slice(-MAX_SIGNALS);
  console.log(`스냅샷 ${snaps.length}개 (${snaps[0] && snaps[0].generatedAt.slice(0, 10)} ~ ${snaps.length && snaps[snaps.length - 1].generatedAt.slice(0, 10)}) → 신호 ${signals.length}개 평가`);

  const rows = [], failed = [];
  for (let i = 0; i < signals.length; i++) {
    const s = signals[i], ex = EX[s.ex];
    if (!ex) continue;
    try {
      const bars = await ex.after(s.sym, s.tf, Date.parse(s.at), HOLD_BARS);
      const r = settle(s, bars);
      if (r) rows.push({ ...s, ...r }); else failed.push(`${s.sym}: 캔들 없음`);
    } catch (e) { failed.push(`${s.sym}: ${e.message}`); }
    if ((i + 1) % 25 === 0) console.log(`  ${i + 1}/${signals.length}`);
    await sleep(ex.gap);
  }

  const summary = summarize(rows);
  const out = {
    generatedAt: new Date().toISOString(),
    holdBars: HOLD_BARS, snapshots: snaps.length,
    period: snaps.length ? [snaps[0].generatedAt, snaps[snaps.length - 1].generatedAt] : null,
    evaluated: rows.length, failed: failed.length,
    note: "R = 손절 거리를 1로 본 손익(수수료 차감). 승률은 R>0 비율. 같은 봉에서 손절·목표 동시 접촉은 손절로 간주(보수적). 표본이 적을수록 숫자를 믿지 마세요.",
    summary,
    signals: rows.map(r => ({ at: r.at, ex: r.ex, dir: r.dir, sym: r.sym, name: r.name, score: r.score, rr: r.rr,
                              outcome: r.outcome, barsHeld: r.barsHeld, R: +r.R.toFixed(3), ret24: r.ret24 == null ? null : +r.ret24.toFixed(2) })),
  };
  fs.writeFileSync("eval.json", JSON.stringify(out, null, 2) + "\n");

  // 사람이 읽는 요약
  const line = (k, s) => `| ${k} | ${s.n} | ${s.목표도달} / ${s.손절} / ${s.시간종료} | ${s.승률}% | ${s.기대값R > 0 ? "+" : ""}${s.기대값R} | ${s.누적R > 0 ? "+" : ""}${s.누적R} | ${s.평균24봉수익률 == null ? "-" : (s.평균24봉수익률 > 0 ? "+" : "") + s.평균24봉수익률 + "%"} |`;
  const md = [
    `## 스캔 신호 사후 평가 (${HOLD_BARS}봉 보유 기준)`,
    `기간 ${out.period ? out.period[0].slice(0, 10) + " ~ " + out.period[1].slice(0, 10) : "-"} · 신호 ${rows.length}개 평가, ${failed.length}개 실패`,
    "", "| 구분 | 신호 수 | 목표 / 손절 / 시간종료 | 승률 | 기대값(R) | 누적(R) | 24봉 평균 수익률 |", "|---|---|---|---|---|---|---|",
    ...Object.entries(summary).map(([k, s]) => line(k, s)),
    "", `> ${out.note}`,
  ].join("\n");
  console.log("\n" + md);
  if (failed.length) console.log("\n실패:", failed.slice(0, 10).join(" · "), failed.length > 10 ? `… 외 ${failed.length - 10}` : "");
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, md + "\n");
})();
