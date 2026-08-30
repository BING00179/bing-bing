# 오르는 종목 AI 자동 분석 시스템

노션 가이드 *「코딩 몰라도 OK! Claude로 만드는 나만의 오르는 종목 AI 자동 분석 시스템」* 의
5단계를, 실제로 돌아가는 파이썬 코드와 Pine Script 로 옮긴 것입니다.

> ⚠️ **AI는 마법 지팡이가 아닙니다.**
> 이 코드는 매수 신호 후보를 찾아주는 **보조 도구**입니다. 수익을 보장하지 않고,
> 매매 권유도 아닙니다. 최종 판단은 항상 본인 기준으로 내리세요.
> 실제 돈을 넣기 전에 반드시 백테스트로 직접 검증하시기 바랍니다.

---

## 무엇을 하나요

```
① 종목 스캔  →  ② 조건 필터링  →  ③ 백테스팅  →  ④ 자동 실행  →  ⑤ 텔레그램 알림
 스캐너 A        스캐너 B         과거 검증       cron 예약        폰으로 수신
```

| 단계 | 명령 | 하는 일 |
|---|---|---|
| ② 프리마켓 스캐너 (A) | `python -m src.cli scan-a` | 장 시작 전 급등 종목 찾기 |
| ③ 전략 스캐너 (B) | `python -m src.cli scan-b` | 매수 조건 맞는 것만 필터링 |
| ④ 백테스팅 | `python -m src.cli backtest` | 전략이 과거에 통했는지 검증 |
| ⑤ 자동화 & 알림 | GitHub Actions | 매일 자동 실행 + 폰 알림 (PC 꺼져 있어도 됨) |

---

## 원문 가이드와 다른 점 (먼저 읽어주세요)

원문은 "Claude 에게 말로 시키는" 방식입니다. 이 저장소는 같은 일을 **코드로 고정**했습니다.
말로 시키면 매번 결과가 조금씩 달라지지만, 코드는 항상 같은 기준으로 판정합니다.

| 항목 | 원문 | 이 저장소 |
|---|---|---|
| MCP / TradingView 연동 | 필수 | **불필요** — Yahoo Finance 를 직접 씁니다 |
| TradingView 유료 구독 | 월 $14.95 | Pine Script 백테스트를 할 때만 필요 |
| Claude 구독 | 월 $20 | 이 코드를 돌리는 데는 불필요 |
| 뉴스 이유 | Benzinga | 무료 헤드라인(yfinance) 기본, Benzinga 키 있으면 그쪽 사용 |
| 매도 규칙 | **없음** | 손절 3% / 익절 6% / 최대보유 5일 (설정 가능) |

원문에는 **청산(매도) 규칙이 빠져 있습니다.** 진입 조건만으로는 백테스트를 할 수 없어서
`config.json` 에 손절·익절·최대보유일을 정의해 두었습니다. 이 값이 성과를 크게 좌우하므로
반드시 본인 기준으로 조정하세요.

---

## 설치

```bash
cd trading-system
pip install -r requirements.txt
```

`yfinance` 는 스캐너용입니다. 백테스트만 CSV 로 돌릴 거면 없어도 됩니다.

---

## 5분 만에 동작 확인하기 (인터넷 불필요)

```bash
python3 scripts/make_sample_data.py                    # 가짜 일봉 CSV 생성
python3 -m src.cli backtest --csv-dir data/daily       # 백테스트 실행
python3 -m pytest tests/ -q                            # 테스트 61개
```

> 합성 데이터로 나온 숫자는 **전략 성능과 무관합니다.** 배관 확인용입니다.

---

## STEP 1. 티커 목록 정하기

`data/universe.txt` 를 열어 스캔할 종목을 넣습니다. 한 줄에 하나, `#` 뒤는 주석입니다.

```
AAPL
NVDA   # 관심 종목
```

기본값은 예시 10종목입니다. 실제로는 나스닥·러셀 구성종목처럼 넓은 목록으로 바꾸세요.
다만 종목 수가 많아질수록 Yahoo 조회 시간이 길어집니다(종목당 약 1~2초).

## STEP 2. 프리마켓 갭 스캐너 (스캐너 A)

```bash
python -m src.cli scan-a
```

조건 (`config.json` → `scanner_a`):

| 항목 | 기본값 |
|---|---|
| 전일 종가 대비 상승률 | 5% 이상 |
| 주가 | $3 이상 |
| 프리마켓 누적 거래량 | 50,000주 이상 |

출력: `티커 / 현재가 / 갭 비율(%) / 상승 이유(뉴스 한 줄)`
결과는 `output/scan_a_<날짜>_<시각>.csv` 로 저장됩니다.

**갭(Gap)이란** 전날 마감가와 오늘 시작가 사이에 가격이 껑충 뛰어 거래되지 않은
구간이 생기는 현상입니다. 예: 전일 종가 $10.00 → 오늘 시가 $10.75 이면 갭 상승 +7.5%.

## STEP 3. 전략 스캐너 (스캐너 B) — Trend Join Long

```bash
python -m src.cli scan-b            # 스캐너 A 최신 결과를 대상으로
python -m src.cli scan-b --universe data/universe.txt   # 전체 목록 대상으로
```

ET 오전 10시 이후에만 실행됩니다(`--force` 로 무시 가능). 5가지 조건을 **전부** 만족해야
매수 신호입니다.

| # | 조건 | 이 저장소의 구현 |
|---|---|---|
| 1 | 전날 일봉 고가보다 위 | `현재가 >= 전일 고가` |
| 2 | 전날 종가가 200일선 위 | `전일 종가 > SMA200` |
| 3 | 오늘 프리마켓 고가보다 위 | `현재가 >= 프리마켓 고가` |
| 4 | 오늘 일봉 고가보다 위 | `현재가 >= 오늘 장중 고가 × 99.5%` (신고가권) |
| 5 | 상승 추세와 일치 | `종가 > SMA20 > SMA50 > SMA200` (정배열) |

조건 5는 원문 문장만으로는 계산할 수 없어 **정배열**로 구체화했습니다. 정의를 바꾸려면
`config.json` 의 `sma_fast` / `sma_mid` / `sma_slow` 를 조정하세요.

조건 4에는 `close_near_high_pct`(기본 0.5%) 만큼의 여유가 있습니다. '오늘 고가'는 현재가가
계속 갱신하는 값이라, 완전 일치를 요구하면 신호가 사실상 나오지 않기 때문입니다.

프리마켓 데이터가 없으면 조건 3은 **"판정 불가"**로 처리하고 통과시키지 **않습니다**.
데이터가 없는 것을 통과로 치면 신호가 부풀려지기 때문입니다.

## STEP 4. 백테스팅

**방법 A. Pine Script (간단)**
`pine/trend_join_long.pine` 를 TradingView Pine 에디터에 붙여넣고 "차트에 추가" →
"전략 테스터" 탭에서 확인합니다.

**방법 B. Python (대규모)**

```bash
python -m src.cli backtest                       # 야후에서 2년치 내려받아 검증
python -m src.cli backtest --csv-dir data/daily  # CSV 폴더로 검증
```

결과는 `output/backtest_trades.csv`(매매 내역)와 `output/backtest_by_ticker.csv`(종목별 요약)
로 저장됩니다.

### 백테스트가 결과를 부풀리지 않도록 한 것들

- **신호는 D일 종가로, 진입은 D+1일 시가로.** 같은 날 종가로 판정해서 같은 날 사는 것은
  미래를 미리 본 것(look-ahead bias)이라 실거래에서 재현되지 않습니다.
- **수수료와 슬리피지를 왕복으로 차감.** 갭 상승 종목은 호가 스프레드가 넓어서
  이 항목을 빼면 결과가 크게 낙관적으로 나옵니다.
- **손절과 익절이 같은 날 둘 다 닿으면 손절 처리.** 일봉만으로는 어느 쪽이 먼저였는지
  알 수 없으므로 불리한 쪽을 택합니다.
- **한 종목에서 포지션이 겹치지 않음.** 청산 전 재진입 없음.

### 백테스트의 한계 (숫자를 믿기 전에)

- **조건 3(프리마켓 고가 돌파)은 검증에서 빠져 있습니다.** 일봉 데이터에 프리마켓
  정보가 없기 때문입니다. 즉 실시간 스캐너보다 느슨한 조건으로 검증된 결과입니다.
- **조건 4는 근사입니다.** 일봉에는 '장중 신고가 갱신' 정보가 없어서 "종가가 그날
  고가에서 0.5% 이내"로 대신했습니다.
- **상장폐지 종목이 빠진 편향(survivorship bias)** 이 있습니다. 지금 존재하는 티커만
  조회되므로, 망한 종목의 손실이 통계에 안 잡힙니다.
- 표본이 적으면(매매 30건 미만) 승률·손익비는 사실상 우연입니다.

## STEP 5. 자동 실행 + 텔레그램 알림

### 텔레그램 봇 만들기

1. 텔레그램에서 **@BotFather** 에게 `/newbot` → 이름 정하면 토큰이 나옵니다.
2. 만든 봇에게 아무 메시지나 보냅니다.
3. `https://api.telegram.org/bot<토큰>/getUpdates` 를 열어 `chat.id` 를 확인합니다.

```bash
cp .env.example .env      # 파일을 열어 토큰과 chat id 입력
set -a && source .env && set +a
python -m src.cli test-telegram
```

> 🔐 토큰은 **환경변수로만** 넘깁니다. 코드나 `config.json` 에 적어서 깃허브에 올리면
> 즉시 탈취당합니다. `.env` 는 `.gitignore` 에 들어 있습니다.

### 자동 실행 예약 — 세 가지 방법

| 방법 | PC 를 켜둬야 하나 | 설정 난이도 | 비용 |
|---|---|---|---|
| **① GitHub Actions (권장)** | **아니오** | 쉬움 | 공개 저장소는 무료 |
| ② 윈도우 작업 스케줄러 | 예 | 보통 | 무료 |
| ③ cron (Mac / Linux) | 예 | 보통 | 무료 |

#### ① GitHub Actions — 내 PC 없이 깃허브 서버가 대신 실행

가장 권장하는 방법입니다. 컴퓨터가 꺼져 있어도 스캔이 돌고 폰으로 알림이 옵니다.

1. 저장소 **Settings → Secrets and variables → Actions → New repository secret** 에서
   `TELEGRAM_BOT_TOKEN` 과 `TELEGRAM_CHAT_ID` 를 등록합니다.
2. `.github/workflows/stock-scan.yml` 이 **기본 브랜치(default branch)** 에 있어야 합니다.
   깃허브는 **기본 브랜치의 예약 작업만 실행**합니다. 다른 브랜치에 워크플로 파일이
   있으면 예약이 절대 돌지 않습니다.
3. **Actions** 탭 → `종목 스캔` → **Run workflow** 로 손으로 한 번 돌려 확인합니다.

> 🔐 공개 저장소에서는 **토큰을 코드에 절대 적지 마세요.** 커밋하는 순간 전 세계에
> 공개되고 자동 수집 봇이 몇 분 안에 가져갑니다. 반드시 Secrets 를 쓰세요.
> Secrets 는 암호화되어 저장되고 로그에도 가려져 나옵니다.

알아둘 점:
- 깃허브 예약은 **정시에 정확히 돌지 않습니다.** 서버가 붐비면 5~15분 늦을 수 있습니다.
- 저장소에 **60일간 아무 커밋이 없으면 예약이 자동 정지**됩니다. 메일이 오면 다시 켜주세요.
- 깃허브 서버는 미국 IP 라 야후 조회가 간헐적으로 제한될 수 있습니다. 실패하면 리포트에
  '조회 실패 N종목' 으로 표시됩니다.

#### ② 윈도우 작업 스케줄러

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1          # 미리보기
powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -Apply   # 등록
powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -Remove  # 삭제
```

#### ③ cron (Mac / Linux)

```bash
bash scripts/install_cron.sh            # 등록될 내용 미리보기
bash scripts/install_cron.sh --apply    # 실제 등록
```

#### 실행 시간대

| 스캐너 | 실행 시간 (미국 동부시간) |
|---|---|
| 프리마켓 갭 (A) | 오전 8:30 ~ 오후 2:00 |
| 전략 (B) | 오전 10:00 ~ 오후 3:05 |

예약은 넉넉하게 걸어두고 **실제 실행 여부는 파이썬이 ET 를 직접 보고 판단**합니다
(`src/market_time.py`). 미국 서머타임 때문에 한국시간과의 차이가 14시간과 16시간을
오가는데, 이 방식이면 서머타임이 바뀌어도 예약을 손볼 필요가 없습니다. 주말도 알아서
건너뜁니다. 시간대 밖이면 한 줄 찍고 즉시 끝나므로 부담이 없습니다.

`--force` 를 붙이면 시간대와 상관없이 강제로 실행합니다.

> ⚠️ ②·③ 은 **컴퓨터가 켜져 있고 잠들지 않아야** 실행됩니다. 노트북을 덮으면 그 시간
> 스캔은 건너뜁니다. 그래서 ① GitHub Actions 를 권합니다.

> 💡 **저장소를 OneDrive·Dropbox 동기화 폴더 안에 두지 마세요.** git 내부 파일과
> 가상환경을 실시간 동기화하려다 파일 잠김·충돌로 저장소가 깨집니다.
> `C:\dev\` 처럼 동기화되지 않는 폴더에 두세요.

---

## 설정 (`config.json`)

```jsonc
{
  "scanner_a": {
    "min_gap_pct": 5.0,            // 전일 대비 상승률 하한 (%)
    "min_price": 3.0,              // 주가 하한 ($)
    "min_premarket_volume": 50000  // 프리마켓 거래량 하한 (주)
  },
  "scanner_b": {
    "sma_slow": 200,               // 조건 2 의 장기 이동평균
    "sma_fast": 20, "sma_mid": 50, // 조건 5 정배열 판정
    "close_near_high_pct": 0.5,    // 백테스트 조건 4 허용 폭
    "earliest_hour_et": 10         // 이 시각 이후에만 신호 인정
  },
  "backtest": {
    "stop_loss_pct": 3.0,          // 손절
    "take_profit_pct": 6.0,        // 익절
    "max_hold_days": 5,            // 최대 보유 거래일
    "commission_per_trade": 1.0,   // 편도 수수료 ($)
    "slippage_pct": 0.1,           // 편도 슬리피지 (%)
    "capital_per_trade": 10000.0   // 1회 투입금 ($)
  }
}
```

> 실제 `config.json` 은 표준 JSON 이라 주석을 넣을 수 없습니다. 위는 설명용입니다.

---

## 폴더 구조

```
.github/workflows/
├── stock-scan.yml                 깃허브 서버에서 스캐너 자동 실행
└── tests.yml                      코드 변경 시 테스트 자동 실행

trading-system/
├── src/
│   ├── config.py      설정 로딩
│   ├── data.py        시세 조회 (yfinance / CSV)
│   ├── indicators.py  이동평균 등
│   ├── strategy.py    Trend Join Long 5조건 판정
│   ├── scanner_a.py   프리마켓 갭 스캐너
│   ├── scanner_b.py   전략 스캐너
│   ├── backtest.py    백테스트 엔진
│   ├── market_time.py 실행 시간대 판정 (서머타임 자동 처리)
│   ├── news.py        뉴스 헤드라인
│   ├── notify.py      텔레그램 알림
│   └── cli.py         명령줄 진입점
├── pine/trend_join_long.pine      TradingView 백테스트용
├── scripts/
│   ├── install_cron.sh            자동 실행 예약 (Mac / Linux)
│   ├── install_task_windows.ps1   자동 실행 예약 (Windows)
│   └── make_sample_data.py        동작 확인용 합성 데이터
├── tests/                         테스트 61개
├── config.json
├── .env.example
└── data/universe.txt              스캔 대상 티커
```

---

## 여기서 한 걸음 더

원문이 언급한 대로 Interactive Brokers 같은 증권사 API 와 연결하면 신호가 뜰 때
실제 매매까지 자동화할 수 있습니다. 다만 **그 전에** 최소한 이것들은 갖추세요.

- 충분한 표본(수백 건)의 백테스트와 **워크포워드 검증**
- 페이퍼 트레이딩으로 최소 수개월 실거래 검증
- 주문 실패·중복 주문·네트워크 끊김에 대한 방어 로직
- 하루 최대 손실 한도와 자동 정지(kill switch)

신호를 보는 것과 돈을 넣는 것 사이에는 큰 간격이 있습니다. 서두르지 마세요.

---

## 라이선스 / 면책

교육 목적의 예시 코드입니다. 투자 자문이 아니며, 이 코드를 사용해 발생한 손실에 대해
작성자는 책임지지 않습니다.
