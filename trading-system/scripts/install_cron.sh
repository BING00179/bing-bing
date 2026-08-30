#!/usr/bin/env bash
# 자동 실행 예약(cron) 등록 도우미 — macOS / Linux 용
#
# 원문 가이드의 스케줄을 그대로 옮긴 것입니다.
#   프리마켓 갭 스캐너(A)  오전 8:30 ~ 오후 2:00, 30분 간격
#   전략 스캐너(B)         오전 10:00 ~ 오후 3:00 (A 결과 5분 뒤)
#
# 시간은 모두 '미국 동부시간(ET)' 기준입니다. 한국에서 쓰는 PC 라면
# 시스템 시간대가 KST 이므로, 아래 CRON_TZ 로 ET 를 강제 지정합니다.
#
# ⚠️ 컴퓨터가 켜져 있고 잠들지 않아야 실행됩니다. 노트북을 덮으면
#    그 시간대 스캔은 건너뜁니다.
#
# 사용법:
#   bash scripts/install_cron.sh          # 등록할 내용 미리보기
#   bash scripts/install_cron.sh --apply  # 실제로 crontab 에 등록

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
LOG_DIR="$PROJECT_DIR/output/logs"

read -r -d '' CRON_BLOCK <<CRONEOF || true
# >>> trading-system (자동 생성) >>>
CRON_TZ=America/New_York
# 프리마켓 갭 스캐너(A): 평일 08:30~13:30 매 30분
30,0 9,10,11,12,13 * * 1-5 cd $PROJECT_DIR && [ -f .env ] && set -a && . ./.env && set +a; $PYTHON_BIN -m src.cli scan-a >> $LOG_DIR/scan_a.log 2>&1
30 8 * * 1-5 cd $PROJECT_DIR && [ -f .env ] && set -a && . ./.env && set +a; $PYTHON_BIN -m src.cli scan-a >> $LOG_DIR/scan_a.log 2>&1
0 14 * * 1-5 cd $PROJECT_DIR && [ -f .env ] && set -a && . ./.env && set +a; $PYTHON_BIN -m src.cli scan-a >> $LOG_DIR/scan_a.log 2>&1
# 전략 스캐너(B): 평일 10:05~15:05 매시간 (A 결과 5분 뒤)
5 10,11,12,13,14,15 * * 1-5 cd $PROJECT_DIR && [ -f .env ] && set -a && . ./.env && set +a; $PYTHON_BIN -m src.cli scan-b >> $LOG_DIR/scan_b.log 2>&1
# <<< trading-system (자동 생성) <<<
CRONEOF

mkdir -p "$LOG_DIR"

if [[ "${1:-}" != "--apply" ]]; then
  echo "아래 내용이 crontab 에 등록됩니다. 실제 등록은 --apply 를 붙이세요."
  echo
  echo "$CRON_BLOCK"
  exit 0
fi

TMP="$(mktemp)"
crontab -l 2>/dev/null | sed '/# >>> trading-system/,/# <<< trading-system/d' > "$TMP"
printf '%s\n' "$CRON_BLOCK" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"

echo "등록 완료. 확인: crontab -l"
echo "로그 위치: $LOG_DIR"
