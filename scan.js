#!/usr/bin/env node
/* ============================================================
   scan.js — 브라우저 없이 도는 자동 스캔

   GitHub Actions가 정해진 주기로 이 스크립트를 실행하고, 결과를
   scan.json 으로 저장한다. 웹페이지는 그 파일을 읽어 "최근 자동 스캔"
   을 보여준다. 맥이 꺼져 있어도 클라우드에서 돌아간다.

   판정은 core.js 를 그대로 쓴다 — 웹 화면과 같은 숫자가 나온다.
   조회 전용이며 주문 기능은 없다.
   ============================================================ */

const fs = require("fs");
const { STABLE, scanScore } = require("./core.js");

const TF = process.env.SCAN_TF || "m60";           // 기준 봉
const TOP = +(process.env.SCAN_TOP || 40);         // 거래대금 상위 몇 개까지 정밀 분석할지

const TFS = {
  day:  { label: "일봉",  upbit: "/candles/days",        binance: "1d" },
  m240: { label: "4시간", upbit: "/candles/minutes/240", binance: "4h" },
  m60:  { label: "1시간", upbit: "/candles/minutes/60",  binance: "1h" },
  m15:  { label: "15분",  upbit: "/candles/minutes/15",  binance: "15m" },
};

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function getJson(url, tries = 3) {
  let err;
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url, { headers: { "User-Agent": "coin-chart-analyzer/1.0" } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch (e) { err = e; await sleep(800 * (i + 1)); }
  }
  throw err;
}

const won = p => (Math.abs(p) >= 1000 ? Math.round(p).toLocaleString("en-US")
  : Math.abs(p) >= 1 ? p.toFixed(2) : Number(p.toPrecision(4)).toString());
const fmtKRW = p => won(p) + "원";
const fmtUSD = p => "$" + won(p);

/* ---------- 거래소별 조회 ---------- */
const EX = {
  upbit: {
    label: "업비트", minVol: 3e9, fmt: fmtKRW, gap: 130,
    async universe() {
      const all = await getJson("https://api.upbit.com/v1/market/all?isDetails=false");
      const krw = all.filter(m => m.market.startsWith("KRW-"));
      const name = Object.fromEntries(krw.map(m => [m.market, m.korean_name]));
      const out = [];
      for (let i = 0; i < krw.length; i += 100) {
        const codes = krw.slice(i, i + 100).map(m => m.market).join(",");
        const rows = await getJson(`https://api.upbit.com/v1/ticker?markets=${codes}`);
        rows.forEach(t => out.push({
          sym: t.market, name: name[t.market] || t.market, price: t.trade_price,
          chgRate: t.signed_change_rate * 100, quoteVol: t.acc_trade_price_24h,
        }));
        await sleep(150);
      }
      return out;
    },
    candles: sym => getJson(`https://api.upbit.com/v1${TFS[TF].upbit}?market=${sym}&count=120`)
      .then(raw => raw.reverse().map(c => ({
        open: c.opening_price, high: c.high_price, low: c.low_price,
        close: c.trade_price, volume: c.candle_acc_trade_volume,
      }))),
  },
  binance: {
    label: "바이낸스", minVol: 1e7, fmt: fmtUSD, gap: 60,
    async universe() {
      const rows = await getJson("https://api.binance.com/api/v3/ticker/24hr");
      return rows
        .filter(t => t.symbol.endsWith("USDT") && !/(UP|DOWN|BULL|BEAR)USDT$/.test(t.symbol))
        .map(t => ({
          sym: t.symbol, name: t.symbol.slice(0, -4), price: +t.lastPrice,
          chgRate: +t.priceChangePercent, quoteVol: +t.quoteVolume,
        }));
    },
    candles: sym => getJson(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${TFS[TF].binance}&limit=120`)
      .then(raw => raw.map(k => ({ open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5] }))),
  },
};

// 캔들은 종목당 한 번만 받고 상방·하방을 같이 판정한다 (요청 수 절반)
async function scanExchange(key) {
  const ex = EX[key];
  const uni = (await ex.universe())
    .filter(u => u.quoteVol >= ex.minVol && !STABLE.test(u.name.toUpperCase()) && !STABLE.test(u.sym.replace(/^KRW-/, "")))
    .sort((a, b) => b.quoteVol - a.quoteVol)
    .slice(0, TOP);

  const res = { long: { scanned: uni.length, hits: [] }, short: { scanned: uni.length, hits: [] } };
  for (const u of uni) {
    try {
      const cs = await ex.candles(u.sym);
      for (const dir of ["long", "short"]) {
        const s = scanScore(cs, dir, u, ex.fmt);
        if (s) res[dir].hits.push({
          sym: u.sym, name: u.name, chgRate: +u.chgRate.toFixed(2),
          score: s.score, reasons: s.reasons,
          price: s.price, stop: s.stop, tgt: s.tgt, rr: +s.rr.toFixed(2),
        });
      }
    } catch (e) {
      process.stderr.write(`  ${u.sym} 건너뜀: ${e.message}\n`);
    }
    await sleep(ex.gap);
  }
  for (const dir of ["long", "short"]) {
    res[dir].hits.sort((a, b) => b.score - a.score);
    console.log(`${ex.label} ${dir}: ${uni.length}개 중 ${res[dir].hits.length}개 포착`);
  }
  return res;
}

(async () => {
  const out = {
    generatedAt: new Date().toISOString(),
    tf: TF, tfLabel: TFS[TF].label,
    note: "조건 검색 결과이며 매매 추천이 아닙니다. 점수는 동시에 성립한 조건의 수입니다.",
    exchanges: {},
  };
  for (const key of ["upbit", "binance"]) {
    try {
      out.exchanges[key] = await scanExchange(key);
    } catch (e) {
      console.error(`${key} 실패: ${e.message}`);
      const empty = { scanned: 0, hits: [], error: e.message };
      out.exchanges[key] = { long: empty, short: empty };
    }
  }
  fs.writeFileSync("scan.json", JSON.stringify(out, null, 2) + "\n");
  console.log("scan.json 저장 완료");
})();
