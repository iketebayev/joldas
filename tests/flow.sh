#!/usr/bin/env bash
# Сквозные сценарии. Меняют данные — после запуска: docker compose exec app python -m app.seed --reset
set -u
cd "$(dirname "$0")/.."
B=${BASE:-http://127.0.0.1:8090}; D=$(mktemp -d); trap 'rm -rf "$D"' EXIT
q() { docker compose exec -T db psql -U app -d app -tAc "$1"; }
login() { rm -f "$D/$1"; curl -s -o /dev/null -c "$D/$1" -b "$D/$1" -X POST "$B/login" -d "login=$2&password=${DEMO_PASSWORD:-demo1234}"; }
post() { curl -s -o /dev/null -w '%{http_code}' -b "$D/$1" -c "$D/$1" -X POST "$B$2" ${3:+-d "$3"}; }
ok() { if [ "$1" = "$2" ]; then echo "  ✓ $3"; else echo "  ✗ $3 (получили '$1', ожидали '$2')"; FAIL=1; fi; }
FAIL=0
login comp company@demo.kz; login guide guide@demo.kz; login tour tourist@demo.kz; login admin admin@demo.kz
AIDOS=$(q "SELECT id FROM users WHERE email='guide@demo.kz'")
TIMUR=$(q "SELECT id FROM users WHERE name='Тимур Оразов'")
SITE=$(q "SELECT id FROM sites WHERE slug='bozjyra'")
D1=$(date -d '+20 days' +%F); D2=$(date -d '+21 days' +%F); SOON=$(date -d '+1 day' +%F)

echo "1. Турфирма: заявка → уведомления гидам с английским"
N0=$(q "SELECT count(*) FROM notifications WHERE user_id=$AIDOS")
post comp /requests/new "date_from=$D1&date_to=$D2&language=en&site_ids=$SITE&group_size=4&price_per_day=25000&note=test" >/dev/null
RID=$(q "SELECT max(id) FROM requests")
N1=$(q "SELECT count(*) FROM notifications WHERE user_id=$AIDOS")
ok "$((N1-N0))" "1" "Айдос (EN) получил уведомление"
ZH=$(q "SELECT id FROM users WHERE name='Асель Нурмагамбетова'")
ERLAN=$(q "SELECT id FROM users WHERE name='Ерлан Кенжебаев'")
ok "$(q "SELECT count(*) FROM notifications WHERE user_id=$ERLAN AND link='/requests/$RID'")" "0" "Ерлану (только RU/KK) уведомление не пришло"

echo "2. Гид: встречная цена 30 000"
post guide /requests/$RID/offer "action=counter&price=30000&message=Знаю+Бозжыру" >/dev/null
ok "$(q "SELECT price_per_day FROM offers WHERE request_id=$RID AND guide_id=$AIDOS")" "30000" "отклик со своей ценой сохранён"
ok "$(curl -s -b $D/guide $B/requests/$RID | grep -c 'Контакты откроются\|contacts unlock\|Байланыстар тапсырыс')" "0" "до выбора гид не видит блок контактов заказа"

echo "3. Турфирма выбирает → подтверждено сразу, контакты открыты"
OID=$(q "SELECT id FROM offers WHERE request_id=$RID AND guide_id=$AIDOS")
post comp /offers/$OID/choose >/dev/null
AID=$(q "SELECT id FROM assignments WHERE request_id=$RID AND status<>'cancelled'")
ok "$(q "SELECT status FROM assignments WHERE id=$AID")" "confirmed" "заказ турфирмы подтверждён без депозита"
ok "$(q "SELECT total FROM assignments WHERE id=$AID")" "60000" "сумма: 2 дня × 30 000"
curl -s -b $D/comp -H "Cookie: lang=ru" $B/requests/$RID | grep -q "+70000000100" && echo "  ✓ турфирма видит телефон гида" || { echo "  ✗ контакты не открылись"; FAIL=1; }

echo "4. Отзыв до завершения запрещён"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/comp $B/assignments/$AID/review)" "403" "форма отзыва недоступна до выполнения"

echo "5. Завершение → отзыв 5★ → рейтинг пересчитан"
R0=$(q "SELECT rating FROM users WHERE id=$AIDOS"); C0=$(q "SELECT completed_count FROM guides WHERE user_id=$AIDOS")
post comp /assignments/$AID/complete >/dev/null
ok "$(q "SELECT completed_count FROM guides WHERE user_id=$AIDOS")" "$((C0+1))" "счётчик заказов гида +1"
post comp /assignments/$AID/review "overall=5&c_route=5&c_language=5&c_punctuality=4&c_communication=5&text=Отлично" >/dev/null
R1=$(q "SELECT rating FROM users WHERE id=$AIDOS")
echo "  рейтинг Айдоса: $R0 → $R1"
ok "$(post comp /assignments/$AID/review 'overall=1')" "409" "повторный отзыв на тот же заказ отклонён"
ok "$(q "SELECT count(*) FROM reviews WHERE assignment_id=$AID AND author_id=(SELECT id FROM users WHERE email='company@demo.kz')")" "1" "в базе ровно один отзыв"

echo "6. Турист: заявка → выбор → депозит 10% → контакты"
post tour /requests/new "date_from=$D1&language=en&group_size=2&price_per_day=20000" >/dev/null
TR=$(q "SELECT max(id) FROM requests")
post guide /requests/$TR/offer "action=accept" >/dev/null
TO=$(q "SELECT id FROM offers WHERE request_id=$TR AND guide_id=$AIDOS")
post tour /offers/$TO/choose >/dev/null
TA=$(q "SELECT id FROM assignments WHERE request_id=$TR AND status<>'cancelled'")
ok "$(q "SELECT status FROM assignments WHERE id=$TA")" "awaiting_payment" "у туриста заказ ждёт депозита"
curl -s -b $D/tour -H "Cookie: lang=en" $B/requests/$TR | grep -q "+70000000100" && { echo "  ✗ контакты видны до депозита"; FAIL=1; } || echo "  ✓ до депозита контакты скрыты"
post tour /assignments/$TA/pay >/dev/null
ok "$(q "SELECT amount FROM payments WHERE assignment_id=$TA AND kind='deposit'")" "2000" "депозит 10% от 20 000"
ok "$(q "SELECT status FROM assignments WHERE id=$TA")" "confirmed" "после депозита подтверждено"

echo "7. Отмена туристом за ≥48 ч → депозит возвращён"
post tour /assignments/$TA/cancel >/dev/null
ok "$(q "SELECT amount FROM payments WHERE assignment_id=$TA AND kind='refund'")" "2000" "возврат 2 000"

echo "8. Отмена туристом за <48 ч → депозит не возвращается"
post tour /requests/new "date_from=$SOON&language=en&group_size=2&price_per_day=20000" >/dev/null
TR2=$(q "SELECT max(id) FROM requests")
post guide /requests/$TR2/offer "action=accept" >/dev/null
post tour /offers/$(q "SELECT id FROM offers WHERE request_id=$TR2 AND guide_id=$AIDOS")/choose >/dev/null
TA2=$(q "SELECT id FROM assignments WHERE request_id=$TR2 AND status<>'cancelled'")
post tour /assignments/$TA2/pay >/dev/null
post tour /assignments/$TA2/cancel >/dev/null
ok "$(q "SELECT count(*) FROM payments WHERE assignment_id=$TA2 AND kind='refund'")" "0" "возврата нет"

echo "9. Отмена гидом → штраф 1★, полный возврат, заявка снова открыта"
post tour /requests/new "date_from=$D1&language=en&group_size=2&price_per_day=20000" >/dev/null
TR3=$(q "SELECT max(id) FROM requests")
login timur "$(q "SELECT email FROM users WHERE id=$TIMUR")" 2>/dev/null
q "UPDATE users SET email='timur@demo.kz' WHERE id=$TIMUR" >/dev/null; login timur timur@demo.kz
post guide /requests/$TR3/offer "action=accept" >/dev/null
post timur /requests/$TR3/offer "action=accept" >/dev/null
post tour /offers/$(q "SELECT id FROM offers WHERE request_id=$TR3 AND guide_id=$TIMUR")/choose >/dev/null
TA3=$(q "SELECT id FROM assignments WHERE request_id=$TR3 AND status<>'cancelled'")
post tour /assignments/$TA3/pay >/dev/null
post timur /assignments/$TA3/cancel >/dev/null
ok "$(q "SELECT overall||'/'||is_system FROM reviews WHERE assignment_id=$TA3")" "1/true" "системная оценка 1 гиду"
ok "$(q "SELECT amount FROM payments WHERE assignment_id=$TA3 AND kind='refund'")" "2000" "туристу вернули депозит"
ok "$(q "SELECT status FROM requests WHERE id=$TR3")" "open" "заявка снова открыта"
ok "$(q "SELECT status FROM offers WHERE request_id=$TR3 AND guide_id=$AIDOS")" "pending" "отклик Айдоса вернулся в выбор"

echo "10. Доступы"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/guide $B/dashboard)" "403" "гид не открывает дашборд"
ok "$(post guide /offers/$OID/choose)" "403" "гид не может выбирать отклики"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/timur $B/requests/$RID)" "403" "чужой гид не видит закрытую чужую заявку"

echo "11. Тариф «Старт»: вторая заявка в месяце → на тарифы"
q "UPDATE companies SET plan='start', plan_until=NULL WHERE user_id=(SELECT id FROM users WHERE email='company@demo.kz')" >/dev/null
ok "$(curl -s -o /dev/null -w '%{redirect_url}' -b $D/comp $B/requests/new)" "$B/pricing" "лимит «Старт» ведёт на тарифы"
post comp /billing/subscribe >/dev/null
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/comp $B/requests/new)" "200" "после «Сезона» заявка снова доступна"

echo "12. Рассылка «Объявить набор»"
G=$(q "SELECT count(*) FROM users WHERE role='guide'")
post admin /dashboard/broadcast "language=zh&audience=all&text=Набор+гидов+с+китайским" >/dev/null
ok "$(q "SELECT recipients FROM broadcasts ORDER BY id DESC LIMIT 1")" "$G" "набор — всем гидам ($G)"
ZHG=$(q "SELECT count(*) FROM guides WHERE 'zh' = ANY(languages)")
post admin /dashboard/broadcast "language=zh&audience=lang&text=Есть+спрос" >/dev/null
ok "$(q "SELECT recipients FROM broadcasts ORDER BY id DESC LIMIT 1")" "$ZHG" "спрос — только знающим китайский ($ZHG)"

echo "13. Отмена открытой заявки автором"
post comp /requests/new "date_from=$D1&language=de&group_size=2&price_per_day=20000" >/dev/null
CR=$(q "SELECT max(id) FROM requests")
ok "$(post guide /requests/$CR/cancel)" "403" "чужой не может отменить заявку"
post comp /requests/$CR/cancel >/dev/null
ok "$(q "SELECT status FROM requests WHERE id=$CR")" "cancelled" "автор отменил заявку"

echo "14. Двойная бронь: занятого гида выбрать нельзя"
post comp /requests/new "date_from=$D1&date_to=$D2&language=en&group_size=2&price_per_day=20000" >/dev/null
DB0=$(q "SELECT max(id) FROM requests")
post guide /requests/$DB0/offer "action=accept" >/dev/null
post comp /offers/$(q "SELECT id FROM offers WHERE request_id=$DB0 AND guide_id=$AIDOS")/choose >/dev/null
ok "$(q "SELECT status FROM assignments WHERE request_id=$DB0")" "confirmed" "Айдос забронирован на $D1–$D2"
post comp /requests/new "date_from=$D2&language=en&group_size=2&price_per_day=20000" >/dev/null
DB1=$(q "SELECT max(id) FROM requests")
post guide /requests/$DB1/offer "action=accept" >/dev/null
ok "$(post comp /offers/$(q "SELECT id FROM offers WHERE request_id=$DB1 AND guide_id=$AIDOS")/choose)" "409" "Айдос уже занят на эти даты — выбор отклонён"

[ $FAIL = 0 ] && echo "=== ВСЕ СЦЕНАРИИ ПРОЙДЕНЫ ===" || { echo "=== ЕСТЬ ПРОВАЛЫ ==="; exit 1; }
