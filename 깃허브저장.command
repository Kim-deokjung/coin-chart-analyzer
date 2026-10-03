#!/bin/bash
# 더블클릭: 바뀐 내용을 모두 커밋하고 깃허브(origin/main)에 올린다.
cd "$(dirname "$0")"
echo "== 깃허브에서 최신 내용 받는 중..."
git pull --rebase --autostash origin main || { echo "!! pull 실패. 충돌을 먼저 해결하세요."; read -p "엔터를 누르면 닫힙니다"; exit 1; }
if [ -z "$(git status --porcelain)" ]; then
  echo "== 바뀐 내용 없음. 이미 최신입니다."
else
  git add -A
  echo "== 변경 파일:"; git status --short
  read -p "커밋 메시지 (비우면 날짜로 자동): " MSG
  [ -z "$MSG" ] && MSG="업데이트 $(date '+%Y-%m-%d %H:%M')"
  git commit -q -m "$MSG"
  git push origin main && echo "== 깃허브 저장 완료: $MSG" || echo "!! push 실패"
fi
read -p "엔터를 누르면 닫힙니다"
