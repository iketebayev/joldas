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
post tour /requests/new "transport=car&date_from=$D1&language=en&group_size=2&price_per_day=20000" >/dev/null
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
post tour /requests/new "transport=car&date_from=$SOON&language=en&group_size=2&price_per_day=20000" >/dev/null
TR2=$(q "SELECT max(id) FROM requests")
post guide /requests/$TR2/offer "action=accept" >/dev/null
post tour /offers/$(q "SELECT id FROM offers WHERE request_id=$TR2 AND guide_id=$AIDOS")/choose >/dev/null
TA2=$(q "SELECT id FROM assignments WHERE request_id=$TR2 AND status<>'cancelled'")
post tour /assignments/$TA2/pay >/dev/null
post tour /assignments/$TA2/cancel >/dev/null
ok "$(q "SELECT count(*) FROM payments WHERE assignment_id=$TA2 AND kind='refund'")" "0" "возврата нет"

echo "9. Отмена гидом → штраф 1★, полный возврат, заявка снова открыта"
post tour /requests/new "transport=car&date_from=$D1&language=en&group_size=2&price_per_day=20000" >/dev/null
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


echo "15. Анкета безопасности: без согласия — отказ, с согласием — сохранена"
D3=$(date -d '+40 days' +%F); D4=$(date -d '+41 days' +%F)
N0=$(q "SELECT count(*) FROM requests")
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/requests/new -d "transport=car&date_from=$D3&date_to=$D4&language=en&group_size=4&price_per_day=20000&risks=anaphylaxis&epipen=on&ice_name=Hans&ice_phone=%2B491701234567"
ok "$(q "SELECT count(*) FROM requests")" "$N0" "без согласия заявка не создана"
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/requests/new -d "transport=car&date_from=$D3&date_to=$D4&language=en&group_size=4&price_per_day=20000&countries=DE&risks=anaphylaxis&epipen=on&ice_name=Hans+Safety&ice_phone=%2B491701234567&consent=on"
SR=$(q "SELECT max(id) FROM requests")
ok "$(q "SELECT risks[1]||'/'||epipen||'/'||(consent_at IS NOT NULL) FROM request_safety WHERE request_id=$SR")" "anaphylaxis/true/true" "анкета сохранена с согласием"

echo "16. Допуслуги: выбор с допами → сумма и депозит"
post guide /requests/$SR/offer "action=accept" >/dev/null
post timur /requests/$SR/offer "action=accept" >/dev/null
ok "$(curl -s -b $D/timur $B/requests/$SR | grep -c 'Hans Safety')" "0" "другой гид не видит контакт ЧП"
DRONE=$(q "SELECT id FROM guide_addons WHERE guide_id=$AIDOS AND kind='drone'")
CAT=$(q "SELECT id FROM guide_addons WHERE guide_id=$AIDOS AND kind='catering'")
DP=$(q "SELECT price FROM guide_addons WHERE id=$DRONE"); CP=$(q "SELECT price FROM guide_addons WHERE id=$CAT")
SO=$(q "SELECT id FROM offers WHERE request_id=$SR AND guide_id=$AIDOS")
post tour /offers/$SO/choose "addon_ids=$DRONE&addon_ids=$CAT" >/dev/null
SA=$(q "SELECT id FROM assignments WHERE request_id=$SR AND status<>'cancelled'")
EXP=$(( 20000*2 + DP + 4*CP ))
ok "$(q "SELECT total FROM assignments WHERE id=$SA")" "$EXP" "итого = 2 дня × 20 000 + дрон + 4 × кейтеринг ($EXP)"
ok "$(curl -s -b $D/guide $B/requests/$SR | grep -c 'Hans Safety')" "0" "назначенный гид до оплаты депозита контакт ЧП не видит"
post tour /assignments/$SA/pay >/dev/null
ok "$(q "SELECT amount FROM payments WHERE assignment_id=$SA AND kind='deposit'")" "$(( (EXP*10+50)/100 ))" "депозит 10% от суммы с допами"
PAGE=$(curl -s -b $D/guide -H "Cookie: lang=ru" $B/requests/$SR)
ok "$(echo "$PAGE" | grep -c 'Hans Safety')" "1" "после подтверждения назначенный гид видит контакт ЧП"
ok "$(echo "$PAGE" | grep -c 'Риск анафилаксии')" "1" "в брифе есть действие по анафилаксии"

echo "17. Акимат: страна видна, здоровье — нет"
ok "$(curl -s -b $D/admin $B/requests/$SR | grep -c 'Hans Safety')" "0" "админ не видит контакт ЧП"
ok "$(curl -s -b $D/admin -H "Cookie: lang=ru" $B/dashboard | grep -q 'Германия' && echo yes)" "yes" "страна в дашборде"

echo "18. Через 30 дней после тура здоровье и ICE стираются, страны остаются для статистики"
q "UPDATE requests SET date_from=current_date-45, date_to=current_date-44 WHERE id=$SR" >/dev/null
docker compose exec -T app python -c "
import asyncio
from app.db import init_pool, pool
from app.services.safety import purge
async def m():
    await init_pool()
    async with pool().acquire() as c: print(await purge(c))
asyncio.run(m())" >/dev/null
ok "$(q "SELECT cardinality(risks) || '/' || (ice_name IS NULL) || '/' || (ice_phone IS NULL) FROM request_safety WHERE request_id=$SR")" "0/true/true" "здоровье и контакт ЧП стёрты"
ok "$(q "SELECT cardinality(countries) > 0 FROM request_safety WHERE request_id=$SR")" "t" "страны сохранились"


echo "19. Маршрут тура: GPX и доступ"
GR=$(q "SELECT r.id FROM requests r WHERE array_length(r.site_ids,1) >= 2 AND r.status='open' LIMIT 1")
GPX=$(curl -s -b $D/guide $B/requests/$GR/route.gpx)
ok "$(echo "$GPX" | python3 -c "import sys,xml.dom.minidom as m; d=m.parseString(sys.stdin.read()); print(len(d.getElementsByTagName('rtept')))")" "$(( $(q "SELECT array_length(site_ids,1) FROM requests WHERE id=$GR") + 2 ))" "GPX валиден: Актау → объекты → Актау"
CLOSED=$(q "SELECT r.id FROM requests r JOIN users u ON u.id=r.author_id WHERE r.status='done' AND NOT EXISTS (SELECT 1 FROM offers o WHERE o.request_id=r.id AND o.guide_id=$TIMUR) LIMIT 1")
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/timur $B/requests/$CLOSED/route.gpx)" "403" "чужой гид не скачает GPX закрытого тура"
ok "$(curl -s -o /dev/null -w '%{http_code}' $B/academy/bozjyra.gpx)" "200" "GPX объекта в Академии"


echo "20. Въезд в госпарк: расчёт, отдельно от ставки гида"
D5=$(date -d '+50 days' +%F); D6=$(date -d '+51 days' +%F)
BZ=$(q "SELECT id FROM sites WHERE slug='bozjyra'"); TZ=$(q "SELECT id FROM sites WHERE slug='tuzbair'"); SH=$(q "SELECT id FROM sites WHERE slug='sherkala'")
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/requests/new -d "transport=car&date_from=$D5&date_to=$D6&language=en&group_size=4&price_per_day=20000&site_ids=$BZ&site_ids=$TZ"
PR=$(q "SELECT max(id) FROM requests")
ok "$(curl -s -b $D/tour -H 'Cookie: lang=ru' $B/requests/$PR | grep -c '16.868')" "1" "заказчик видит ≈16 868 ₸ за въезд (4 чел. × 2 дн.)"
post guide /requests/$PR/offer "action=accept" >/dev/null
ok "$(curl -s -b $D/guide -H 'Cookie: lang=ru' $B/requests/$PR | grep -c 'Вы оплачиваете въезд')" "1" "гид видит, что въезд оплачивает он"
post tour /offers/$(q "SELECT id FROM offers WHERE request_id=$PR AND guide_id=$AIDOS")/choose >/dev/null
PA=$(q "SELECT id FROM assignments WHERE request_id=$PR AND status<>'cancelled'")
ok "$(q "SELECT entry_fee||'/'||total FROM assignments WHERE id=$PA")" "16868/40000" "въезд отдельно от ставки гида"
post tour /assignments/$PA/pay >/dev/null
ok "$(q "SELECT amount FROM payments WHERE assignment_id=$PA AND kind='deposit'")" "4000" "депозит 10% только от услуг гида"
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/requests/new -d "transport=car&date_from=$D5&language=en&group_size=4&price_per_day=20000&site_ids=$SH"
NR=$(q "SELECT max(id) FROM requests")
ok "$(curl -s -b $D/tour -H 'Cookie: lang=ru' $B/requests/$NR | grep -c 'Кроме ставки гида')" "0" "маршрут вне парка — без платы за въезд"


echo "21. Цена в валюте: пересчёт в тенге по курсу, подсказка средней ставки"
USD=$(q "SELECT kzt FROM exchange_rates WHERE code='USD'")
ok "$( [ -n "$USD" ] && echo yes )" "yes" "курс USD загружен ($USD ₸)"
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/requests/new -d "transport=car&date_from=$D5&language=en&group_size=2&price_per_day=60&currency=USD"
UR=$(q "SELECT max(id) FROM requests")
EXPK=$(python3 -c "print(round(60*$USD))")
ok "$(q "SELECT currency||'/'||price_original::int||'/'||price_per_day FROM requests WHERE id=$UR")" "USD/60/$EXPK" "60 USD сохранены как $EXPK ₸"
ok "$(curl -s -b $D/guide -H 'Cookie: lang=ru' $B/requests | grep -q '\$60' && echo yes)" "yes" "гид видит исходную сумму в долларах рядом с тенге"
HINT=$(curl -s "$B/api/price-hint?language=en&sites=$BZ")
ok "$(echo "$HINT" | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok' if d['avg_kzt'] and d['rates']['USD'] and d['scope'] else d)")" "ok" "подсказка: средняя ставка и курсы"


echo "22. Туры агентств: вопрос о транспорте, витрина, бронь, подписка"
N0=$(q "SELECT count(*) FROM requests")
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/requests/new -d "date_from=$D5&language=en&group_size=2&price_per_day=20000"
ok "$(q "SELECT count(*) FROM requests")" "$N0" "без ответа о транспорте заявка туриста не создаётся"
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/requests/new -d "transport=none&date_from=$D5&language=en&group_size=2&price_per_day=20000&site_ids=$BZ"
ok "$(q "SELECT transport FROM requests ORDER BY id DESC LIMIT 1")" "none" "ответ «нет ни тура, ни машины» сохранён"
ok "$(curl -s -b $D/guide -H 'Cookie: lang=ru' $B/requests | grep -q 'нужна машина' && echo yes)" "yes" "гид видит бейдж «нужна машина»"
TID=$(curl -s "$B/api/tours?sites=$BZ&language=en" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
ok "$( [ -n "$TID" ] && echo yes )" "yes" "витрина подобрала тур по объекту и языку"
MAXG=$(q "SELECT max_group FROM tours WHERE id=$TID")
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/tours/$TID/book -d "date_from=$D5&group_size=$((MAXG+1))"
ok "$(q "SELECT count(*) FROM tour_bookings WHERE tour_id=$TID AND date_from='$D5'")" "0" "группа больше максимума — бронь отклонена"
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/tours/$TID/book -d "date_from=$D5&group_size=2"
BID=$(q "SELECT id FROM tour_bookings WHERE tour_id=$TID AND date_from='$D5'")
ok "$(q "SELECT status||'/'||total FROM tour_bookings WHERE id=$BID")" "pending/$(( $(q "SELECT price_per_person FROM tours WHERE id=$TID") * 2 ))" "бронь создана: ждёт подтверждения, сумма = цена × 2"
AG=$(q "SELECT u.email FROM tours t JOIN users u ON u.id=t.company_id WHERE t.id=$TID")
login agency "$AG"
post agency /bookings/$BID/confirm >/dev/null
ok "$(q "SELECT status FROM tour_bookings WHERE id=$BID")" "confirmed" "агентство подтвердило бронь"
AGPHONE=$(q "SELECT phone FROM users WHERE email='$AG'")
TPAGE=$(curl -s -b $D/tour $B/requests)
ok "$(echo "$TPAGE" | grep -q "tel:$AGPHONE" && echo yes)" "yes" "турист видит контакты агентства"
echo "$TPAGE" | grep -q "tel:$AGPHONE" || { echo "   отладка: телефон=[$AGPHONE], брони в странице: $(echo "$TPAGE" | grep -c 'bookings/')"; }
AGID=$(q "SELECT company_id FROM tours WHERE id=$TID")
q "UPDATE companies SET plan='start', plan_until=NULL WHERE user_id=$AGID" >/dev/null
ok "$(curl -s "$B/api/tours" | python3 -c "import sys,json; print('yes' if all(t['id']!=$TID for t in json.load(sys.stdin)) else 'no')")" "yes" "без подписки туры агентства скрыты"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/tour $B/tours/$TID)" "404" "страница тура без подписки недоступна туристу"

echo "— Прямая бронь: контакты закрыты до депозита 10%, после — открыты, ваучер"
TID_=$(q "SELECT id FROM users WHERE email='tourist@demo.kz'")
BG=$(q "SELECT g.user_id FROM guides g WHERE g.day_rate > 0 AND g.id_verified_at IS NOT NULL AND 'en' = ANY(g.languages)
        AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.guide_id=g.user_id AND a.client_id=$TID_) ORDER BY g.user_id LIMIT 1")
BGPH=$(q "SELECT substr(regexp_replace(phone,'\D','','g'),2) FROM users WHERE id=$BG")
ok "$(curl -s $B/guides/$BG | grep -c "$BGPH")" "0" "гость: номера гида нет в HTML"
ok "$(curl -s -b $D/tour $B/guides/$BG | grep -cE 'wa\.me|t\.me/|/c/guide/')" "0" "турист без брони: ни ссылок, ни номера"
ok "$(curl -s -b $D/tour $B/guides/$BG | grep -c 'lockbox')" "1" "вместо контактов — замок"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/tour $B/c/guide/$BG/whatsapp)" "403" "прямой адрес канала без оплаты — 403"
ok "$(curl -s $B/api/tours | grep -c "$BGPH")" "0" "API не отдаёт номер гида"
BD1=$(date -d '+45 days' +%F); BD2=$(date -d '+46 days' +%F); BL=en
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/guides/$BG/book -d "date_from=$BD1&date_to=$BD2&group_size=2&language=$BL"
BA=$(q "SELECT a.id FROM assignments a JOIN requests r ON r.id=a.request_id WHERE a.guide_id=$BG AND a.client_id=$TID_ AND r.direct ORDER BY a.id DESC LIMIT 1")
RATE=$(q "SELECT day_rate FROM guides WHERE user_id=$BG")
ok "$(q "SELECT status || '/' || total || '/' || deposit_amount || '/' || balance_to_guide || '/' || contacts_unlocked FROM assignments WHERE id=$BA")" \
   "awaiting_payment/$((RATE*2))/$((RATE*2/10))/$((RATE*2 - RATE*2/10))/false" "бронь: итог = ставка × 2 дня, депозит 10%, остаток 90%, контакты закрыты"
BR=$(q "SELECT request_id FROM assignments WHERE id=$BA")
ok "$(q "SELECT count(*) FROM notifications WHERE user_id=$BG AND link='/requests/$BR'")" "1" "гид получил уведомление о брони"
curl -s -o /dev/null -b $D/tour -c $D/tour -X POST $B/guides/$BG/book -d "date_from=$BD2&date_to=$BD2&group_size=2&language=$BL"
ok "$(q "SELECT count(*) FROM assignments WHERE guide_id=$BG AND client_id=$TID_ AND status<>'cancelled'")" "1" "занятые даты повторно не бронируются"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/tour $B/assignments/$BA/voucher)" "404" "ваучера до оплаты нет"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/tour $B/c/guide/$BG/whatsapp)" "403" "до оплаты канал закрыт"
post tour /assignments/$BA/pay >/dev/null
ok "$(q "SELECT status || '/' || contacts_unlocked || '/' || (deposit_paid_at IS NOT NULL) || '/' || (voucher_code LIKE 'JL-%') FROM assignments WHERE id=$BA")" "confirmed/true/true/true" "депозит оплачен: контакты открыты, ваучер выдан"
ok "$(q "SELECT amount FROM payments WHERE assignment_id=$BA AND kind='deposit'")" "$((RATE*2/10))" "в платежах ровно 10%"
ok "$(curl -s -b $D/tour $B/guides/$BG | grep -c 'class="guide-phone"')" "1" "после оплаты номер гида виден"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/tour $B/c/guide/$BG/telegram)" "302" "после оплаты каналы открываются"
VC=$(q "SELECT voucher_code FROM assignments WHERE id=$BA")
ok "$(curl -s -b $D/tour $B/assignments/$BA/voucher | grep -c "$VC")" "2" "ваучер с кодом открывается"
ok "$(curl -s $B/guides/$BG | grep -c "$BGPH")" "0" "другим (гостю) номер по-прежнему не виден"
post tour /assignments/$BA/cancel >/dev/null
ok "$(q "SELECT status || '/' || contacts_unlocked FROM assignments WHERE id=$BA")" "cancelled/false" "отмена закрывает контакты"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/tour $B/c/guide/$BG/whatsapp)" "403" "после отмены канал снова закрыт"
ok "$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/c/track/hotel/rixos/call)" "204" "звонок отелю засчитан"
ok "$(curl -s -H 'Cookie: lang=ru' -b $D/admin $B/dashboard | grep -c 'Обращения по каналам')" "1" "дашборд показывает обращения по каналам"
ok "$(curl -s $B/hotels | grep -c 'href="tel:')" "4" "у всех отелей есть кнопка звонка"

echo "— Проверка личности гида и видеовизитка"
IMG="docker compose exec -T worker ffmpeg -v error -f lavfi -i testsrc=size=800x600 -frames:v 1 -f image2 -c:v mjpeg -"
$IMG > $D/doc.jpg; cp $D/doc.jpg $D/s0.jpg; cp $D/doc.jpg $D/s1.jpg; cp $D/doc.jpg $D/ph.jpg
NEWG="kyc$(date +%s)@test.kz"
curl -s -o /dev/null -c $D/ng -b $D/ng -X POST $B/register -d "role=guide&name=Тест Гид&email=$NEWG&password=secret123"
NG=$(q "SELECT id FROM users WHERE email='$NEWG'")
q "UPDATE guides SET languages='{en}', day_rate=20000 WHERE user_id=$NG" >/dev/null
ORID=$(q "SELECT id FROM requests WHERE status='open' AND language='en' AND date_from >= CURRENT_DATE LIMIT 1")
ok "$(curl -s -o /dev/null -w '%{redirect_url}' -b $D/ng -c $D/ng -X POST $B/requests/$ORID/offer -d 'action=accept' | sed 's|.*/verify|/verify|')" "/verify" "непроверенный гид не может откликнуться"
ok "$(q "SELECT count(*) FROM offers WHERE guide_id=$NG")" "0" "отклик не создан"
curl -s -o /dev/null -b $D/ng -c $D/ng $B/verify
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/ng -c $D/ng -X POST $B/verify -F doc_type=id_card -F doc=@$D/doc.jpg -F selfie_0=@$D/s0.jpg -F selfie_1=@$D/s1.jpg -F photo=@$D/ph.jpg)" "303" "без согласия — отказ"
ok "$(q "SELECT count(*) FROM guide_kyc WHERE guide_id=$NG")" "0" "заявка без согласия не сохранена"
curl -s -o /dev/null -b $D/ng -c $D/ng -X POST $B/verify -F consent=1 -F doc_type=id_card -F doc=@$D/doc.jpg -F selfie_0=@$D/s0.jpg -F selfie_1=@$D/s1.jpg -F photo=@$D/ph.jpg
KID=$(q "SELECT id FROM guide_kyc WHERE guide_id=$NG")
ok "$(q "SELECT status || '/' || cardinality(selfie_files) || '/' || cardinality(challenges) FROM guide_kyc WHERE id=$KID")" "pending/2/2" "заявка на проверку: документ, 2 селфи, 2 задания"
DOCF=$(q "SELECT doc_file FROM guide_kyc WHERE id=$KID")
ok "$(docker compose exec -T app sh -c "head -c 5 /data/media/kyc/$DOCF")" "gAAAA" "скан документа зашифрован на диске"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/ng $B/dashboard/kyc/$KID/file/doc/0)" "403" "гид не открывает сканы через модерацию"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/admin $B/dashboard/kyc/$KID/file/doc/0)" "200" "модератор видит скан"
PH=$(q "SELECT photo_file FROM guide_kyc WHERE id=$KID")
ok "$(curl -s -o /dev/null -w '%{http_code}' $B/media/photo/$PH)" "404" "фото до одобрения не видно публично"
ok "$(post admin /dashboard/kyc/$KID/approve 'doc_valid=1&name_match=1')" "303" "одобрение без всех галочек не проходит"
ok "$(q "SELECT status FROM guide_kyc WHERE id=$KID")" "pending" "статус не изменился"
post admin /dashboard/kyc/$KID/approve 'doc_valid=1&name_match=1&liveness=1&face_match=1&photo_match=1' >/dev/null
ok "$(q "SELECT status || '/' || (doc_file IS NULL) || '/' || (selfie_files IS NULL) FROM guide_kyc WHERE id=$KID")" "approved/true/true" "одобрено, ссылки на сканы стёрты"
ok "$(docker compose exec -T app sh -c "ls /data/media/kyc/$DOCF 2>/dev/null | wc -l")" "0" "файлы сканов удалены с диска"
ok "$(curl -s -o /dev/null -w '%{http_code}' $B/media/photo/$PH)" "200" "фото профиля стало публичным"
ok "$(curl -s $B/guides/$NG | grep -c 'badge verified')" "1" "в профиле бейдж «Личность подтверждена»"
post ng /requests/$ORID/offer 'action=accept' >/dev/null
ok "$(q "SELECT count(*) FROM offers WHERE guide_id=$NG")" "1" "после проверки отклик проходит"

docker compose exec -T worker ffmpeg -v error -f lavfi -i testsrc=size=360x640:rate=15 -f lavfi -i sine=frequency=440 -t 5 -c:v libx264 -c:a aac -f mp4 -movflags frag_keyframe+empty_moov - > $D/short.mp4
curl -s -o /dev/null -b $D/ng -c $D/ng -X POST $B/profile/video -F lang=en -F "video=@$D/short.mp4;type=video/mp4"
VS=$(q "SELECT id FROM guide_videos WHERE guide_id=$NG ORDER BY id DESC LIMIT 1")
for i in $(seq 1 30); do [ "$(q "SELECT status FROM guide_videos WHERE id=$VS")" != "processing" ] && break; sleep 2; done
ok "$(q "SELECT status FROM guide_videos WHERE id=$VS")" "failed" "видео короче 30 секунд отклонено автоматически"
docker compose exec -T worker ffmpeg -v error -f lavfi -i testsrc=size=360x640:rate=15 -f lavfi -i sine=frequency=440 -t 32 -c:v libx264 -c:a aac -f mp4 -movflags frag_keyframe+empty_moov - > $D/ok.mp4
curl -s -o /dev/null -b $D/ng -c $D/ng -X POST $B/profile/video -F lang=en -F "video=@$D/ok.mp4;type=video/mp4"
VO=$(q "SELECT id FROM guide_videos WHERE guide_id=$NG ORDER BY id DESC LIMIT 1")
for i in $(seq 1 60); do [ "$(q "SELECT status FROM guide_videos WHERE id=$VO")" != "processing" ] && break; sleep 2; done
ok "$(q "SELECT status FROM guide_videos WHERE id=$VO")" "review" "видео 32 с обработано и ждёт модератора"
VT=$(q "SELECT token FROM guide_videos WHERE id=$VO")
ok "$(curl -s -o /dev/null -w '%{http_code}' $B/media/video/$VT/video.mp4)" "404" "до одобрения видео не видно публично"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/ng $B/media/video/$VT/video.mp4)" "200" "гид видит своё видео на проверке"
ok "$(post admin /dashboard/video/$VO/approve 'level=conversational')" "303" "модератор одобрил с уровнем"
ok "$(q "SELECT lang || ':' || level FROM guide_lang_levels WHERE guide_id=$NG")" "en:conversational" "уровень языка подтверждён по видео"
ok "$(curl -s -o /dev/null -w '%{http_code}' $B/media/video/$VT/preview.mp4)" "200" "превью для наведения доступно"
ok "$(curl -s "$B/guides?language=en" | grep -c "data-video=\"/media/video/$VT/video.mp4\"")" "1" "в каталоге кнопка видео у гида"
post ng /profile/video/delete >/dev/null
ok "$(q "SELECT count(*) FROM guide_lang_levels WHERE guide_id=$NG")" "0" "удалил видео — бейдж языка снят"

echo "— Аналитика: роли, доступы, формулы, выгрузки"
for who in finance gov; do rm -f $D/$who; done
ok "$(curl -s -o /dev/null -w '%{redirect_url}' -c $D/finance -b $D/finance -X POST $B/login -d 'login=admin-finance@demo.kz&password=demo1234&next=/requests' | sed 's|^https\?://[^/]*||')" "/dashboard/finance" "финансист после входа — на /dashboard/finance"
ok "$(curl -s -o /dev/null -w '%{redirect_url}' -c $D/gov -b $D/gov -X POST $B/login -d 'login=admin-gov@demo.kz&password=demo1234' | sed 's|^https\?://[^/]*||')" "/dashboard/gov" "госнаблюдатель после входа — на /dashboard/gov"
code() { curl -s -o /dev/null -w '%{http_code}' -b "$D/$1" "$B$2"; }
ok "$(code finance /dashboard/finance)/$(code finance /dashboard/gov)" "200/403" "финансист видит только финансы"
ok "$(code gov /dashboard/gov)/$(code gov /dashboard/finance)" "200/403" "госнаблюдатель видит только туризм"
ok "$(code admin /dashboard/finance)/$(code admin /dashboard/gov)" "200/200" "админ видит оба дашборда"
ok "$(code gov /dashboard)/$(code gov /dashboard/verify)/$(code gov /requests/$BR)" "403/403/403" "госнаблюдателю закрыты операционные разделы и заявки"
ok "$(code tour /dashboard/finance)/$(code guide /dashboard/gov)" "403/403" "туристу и гиду аналитика закрыта"
ok "$(curl -s -b $D/gov "$B/dashboard/gov?p=year" | grep -cE 'tel:|@demo\.kz|\+7 000|JL-')" "0" "на странице госнаблюдателя нет имён, контактов и ваучеров"
ok "$(curl -s -b $D/gov "$B/dashboard/gov/report.xlsx?p=year" | head -c 2)" "PK" "выгрузка Excel"
ok "$(curl -s -b $D/gov "$B/dashboard/gov/report.pdf?p=year" | head -c 4)" "%PDF" "выгрузка PDF"
ok "$(curl -s -o /dev/null -w '%{http_code}' -b $D/finance "$B/dashboard/gov/report.xlsx")" "403" "финансисту выгрузка акимату закрыта"
CHECK=$(docker compose exec -T app python -c "
import asyncio
from app.db import init_pool, pool
from app.services import analytics
async def m():
    await init_pool(apply_schema=False)
    db = pool()
    f = await analytics.finance(db, 'year'); c = f['cur']
    _, s, e, _ = analytics.window('year')
    gmv = await db.fetchval(\"SELECT coalesce(sum(total),0) FROM assignments WHERE status IN ('confirmed','done') AND coalesce(deposit_paid_at, created_at) >= \$1 AND coalesce(deposit_paid_at, created_at) < \$2\", s, e)
    dep = await db.fetchval('SELECT coalesce(sum(deposit_amount),0) FROM assignments a JOIN requests r ON r.id=a.request_id WHERE r.author_type=\'tourist\' AND deposit_paid_at >= \$1 AND deposit_paid_at < \$2', s, e)
    bad = await db.fetchval(\"SELECT count(*) FROM assignments a JOIN requests r ON r.id=a.request_id WHERE r.author_type='tourist' AND (a.deposit_amount <> round(a.total * 0.10) OR a.balance_to_guide <> a.total - a.deposit_amount)\")
    g = await analytics.gov(db, 'year')
    ok = [c['gmv'] == gmv, c['deposits'] == dep, c['aov'] == round(gmv / c['bookings']), bad == 0,
          c['net'] == c['deposits'] - c['refunds'] - round(c['deposits'] * 0.035),
          g['cur']['local'] <= g['cur']['gmv'], g['cur']['avg_stay'] == round(g['cur']['tourist_days'] / g['cur']['tourists'], 1)]
    print(''.join('1' if x else '0' for x in ok))
asyncio.run(m())")
ok "$CHECK" "1111111" "формулы: GMV, выручка, AOV, 10/90, чистая выручка, доход гидов, длительность"
F0=$(q "SELECT count(*) FROM funnel_events WHERE kind='date' AND NOT is_demo")
curl -s -o /dev/null -A "Mozilla/5.0" -X POST $B/f/date/$BG
curl -s -o /dev/null -X POST $B/f/date/$BG
ok "$(( $(q "SELECT count(*) FROM funnel_events WHERE kind='date' AND NOT is_demo") - F0 ))" "1" "выбор даты попал в воронку, запрос бота/скрипта — нет"

[ $FAIL = 0 ] && echo "=== ВСЕ СЦЕНАРИИ ПРОЙДЕНЫ ===" || { echo "=== ЕСТЬ ПРОВАЛЫ ==="; exit 1; }
