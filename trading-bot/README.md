# Upbit 자동매매 봇

업비트(KRW 마켓) 대상 자동매매 프로그램. 전략 교체 가능, 모의투자(paper) 기본, 백테스트와 웹 대시보드 포함.

## 구조

```
main.py                 CLI (run / backtest / dashboard / reset-paper)
config.yaml             모드·종목·전략·리스크 설정
.env                    실거래용 API 키 (.env.example 참고)
bot/
  engine.py             매매 루프 (시세 -> 리스크 -> 전략 -> 주문 -> 기록)
  backtest.py           캔들 기반 백테스트
  store.py              SQLite 기록 (체결·자산추이·로그·모의잔고)
  data.py               업비트 공개 시세
  exchange/paper.py     모의투자 (실시세 + 가상잔고)
  exchange/upbit_live.py 실거래 (pyupbit)
  strategies/           전략 (volatility_breakout, ma_cross, rsi)
dashboard/              FastAPI 웹 대시보드
tests/                  pytest
```

## 설치

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 가장 쉬운 사용법: 관리자 화면

Finder 에서 `start.command` 를 더블클릭하거나 터미널에서 `.venv/bin/python main.py dashboard` 를 실행하면
브라우저에 http://127.0.0.1:8000 이 열립니다. 여기서 터미널 없이 전부 할 수 있습니다.

- **대시보드**: 총자산·수익률·자산 추이·포지션·체결·로그 (5초 갱신)
- **상단 ▶ 시작 / ■ 정지**: 봇을 서버 안에서 실행/중지. 실거래 모드는 확인창 + "LIVE" 입력 필요
- **설정**: 모드·종목·전략·파라미터·리스크를 수정해 저장 (config.yaml 에 반영, 다음 시작부터 적용)
- **백테스트**: 전략·종목·기간·파라미터를 골라 실행, 자산 곡선과 체결 내역 확인, 모든 전략 비교

창을 닫거나 Ctrl+C 하면 봇도 같이 멈춥니다. 계속 돌리려면 서버를 켜 둔 채로 두세요.

## 터미널 사용 (선택)

```bash
# 백테스트 (전략 비교)
.venv/bin/python main.py backtest --all --ticker KRW-BTC --days 365

# 특정 전략 + 파라미터
.venv/bin/python main.py backtest --strategy volatility_breakout --param k=0.6 --trades

# 모의투자 봇 실행 (config.yaml mode: paper)
.venv/bin/python main.py run

# 대시보드 (별도 터미널)
.venv/bin/python main.py dashboard     # http://127.0.0.1:8000

# 모의투자 초기화
.venv/bin/python main.py reset-paper
```

## 실거래 전환

1. 업비트 > 마이페이지 > Open API 관리 에서 키 발급 (자산조회 + 주문 권한, IP 등록).
2. `.env.example` 을 `.env` 로 복사하고 키 입력.
3. `config.yaml` 의 `mode: live` 로 변경.
4. `python main.py run` — 10초 경고 후 시작. **실제 돈이 나갑니다.** 반드시 소액으로 먼저 검증하세요.

## 전략 추가

`bot/strategies/` 에 파일을 만들고 `Strategy` 를 상속해 `@register` 로 등록하면 `config.yaml` 의 `strategy:` 에서 이름으로 선택할 수 있습니다.

```python
@register
class MyStrategy(Strategy):
    name = "my_strategy"
    interval = "minute60"   # 캔들 단위
    candles = 50            # 필요한 캔들 수
    threshold: float = 1.0  # config 의 strategy_params 로 덮어쓰기 가능

    def decide(self, df, position, now):
        if position is None and <매수 조건>:
            return Order(Side.BUY, reason="...")
        if position is not None and <매도 조건>:
            return Order(Side.SELL, reason="...")
        return None
```

- `Order(price=X)` 를 주면 "현재가가 X 에 도달하면" 체결되는 트리거 주문이 됩니다 (변동성 돌파가 사용).
- 백테스트는 마지막 캔들의 `close/high/low` 를 보지 않는 전략이어야 미래 참조가 없습니다. 트리거 가격이나 `open` 만 쓰면 안전합니다.

## 주의

- 암호화폐 매매는 원금 손실 위험이 큽니다. 백테스트 수익이 미래 수익을 보장하지 않습니다.
- 본 코드는 학습·실험 목적이며, 실거래 손실에 대한 책임은 사용자에게 있습니다.
