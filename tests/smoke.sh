#!/usr/bin/env bash
# Все страницы под каждой ролью на трёх языках.  BASE=https://hack.ai-lab.kz tests/smoke.sh
cd "$(dirname "$0")/.."
B=${BASE:-http://127.0.0.1:8090}
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail=0
check() { # jar lang path expect
  code=$(curl -s -o $T/page.html -w '%{http_code}' -b "$1" -H "Cookie: lang=$2" "$B$3")
  if [ "$code" != "$4" ]; then echo "FAIL $2 $3 -> $code (ожидали $4)"; fail=1; fi
  if grep -q "Traceback\|UndefinedError\|jinja2" $T/page.html; then echo "TEMPLATE ERROR $3"; fail=1; fi
  # на сайте не должно быть служебных пометок (демо-логины @demo.kz — не в счёт)
  if sed 's/[a-z]*@demo\.kz//g' $T/page.html | grep -qiE "демо|пилот|\bMVP\b|тестов|test mode|сынақ"; then echo "ПОМЕТКА на странице $2 $3"; fail=1; fi
}
login() { rm -f "$1"; curl -s -o /dev/null -c "$1" -b "$1" -X POST "$B/login" -d "login=$2&password=${DEMO_PASSWORD:-demo1234}&next=/requests"; }
D=$T
login $D/admin admin@demo.kz; login $D/comp company@demo.kz; login $D/guide guide@demo.kz; login $D/tour tourist@demo.kz
for L in kk ru en; do
  check $D/none $L / 200; check $D/none $L /guides 200; check $D/none $L "/guides?language=zh&level=experienced" 200
  check $D/none $L /guides/2 200; check $D/none $L /pricing 200; check $D/none $L /login 200
  check $D/none $L "/register?role=company" 200; check $D/none $L /requests 303
  check $D/admin $L /dashboard 200; check $D/admin $L /requests 303
  check $D/comp $L /requests 200; check $D/comp $L /requests/new 200; check $D/comp $L /dashboard 403
  check $D/guide $L /requests 200; check $D/guide $L /profile 200; check $D/guide $L /notifications 200
  check $D/tour $L /requests 200; check $D/tour $L /requests/new 200
  check $D/none $L /tours 200; check $D/tour $L /tours/1 200; check $D/comp $L /tours/mine 200
  check $D/guide $L /tours/mine 403; check $D/none $L /hotels 200
  check $D/guide $L /nonexistent 404
done
# детальная заявка каждой роли
rid=$(docker compose exec -T db psql -U app -d app -tAc "SELECT id FROM requests WHERE status='open' AND language='en' LIMIT 1")
cid=$(docker compose exec -T db psql -U app -d app -tAc "SELECT r.id FROM requests r JOIN users u ON u.id=r.author_id WHERE u.email='company@demo.kz' AND r.status='open' LIMIT 1")
check $D/guide ru /requests/$rid 200; check $D/admin ru /requests/$rid 200; check $D/comp ru /requests/$cid 200
[ $fail = 0 ] && echo "ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" || { echo "ЕСТЬ ОШИБКИ"; exit 1; }
