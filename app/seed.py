"""Наполнение: реальные объекты Мангистау + сгенерированные данные для демонстрации.

    python -m app.seed          — заполнить, если база пустая
    python -m app.seed --reset  — очистить всё и заполнить заново
"""
import asyncio
import random
import sys
from datetime import date, datetime, time, timedelta, timezone

from .auth import hash_password
from .config import DEMO_PASSWORD
from .db import close_pool, init_pool, pool
from .services import rating

# Координаты проверены по OpenStreetMap (Nominatim), сентябрь 2026.
SITES = [
    ("bozjyra", "Бозжыра", "Бозжира", "Bozzhyra", 43.40456, 54.07704),
    ("tuzbair", "Тұзбайыр", "Тузбаир", "Tuzbair", 44.03891, 53.15859),
    ("sherkala", "Шерқала", "Шеркала", "Sherkala", 44.25432, 52.00804),
    ("torysh", "Торыш", "Долина шаров Торыш", "Torysh Valley of Balls", 44.29639, 51.50749),
    ("bokty", "Бокты", "Бокты", "Bokty", 43.42283, 53.79909),
    ("kyzylkup", "Қызылқұп", "Кызылкуп", "Kyzylkup", 43.47664, 53.80259),
    ("beket_ata", "Бекет ата", "Бекет-ата", "Beket Ata", 43.59477, 54.08118),
    ("karaman_ata", "Қараман ата", "Караман-ата", "Karaman Ata", 43.89983, 51.87271),
    ("karagiye", "Қарақия ойысы", "Впадина Карагие", "Karagiye Depression", 43.40410, 51.78540),
    ("shakpak_ata", "Шақпақ ата", "Шакпак-ата", "Shakpak Ata", 44.43341, 51.13891),
    ("zhygylgan", "Жығылған", "Жыгылган", "Zhygylgan", 44.61648, 50.81276),
    ("kapamsay", "Қапамсай", "Каньон Капамсай", "Kapamsay Canyon", 44.39702, 51.08036),
    ("sultan_epe", "Сұлтан эпе", "Султан-эпе", "Sultan Epe", 44.47137, 51.01225),
    ("kenderli", "Кендірлі", "Кендерли", "Kenderli", 43.32338, 52.90458),
    ("shopan_ata", "Шопан ата", "Шопан-ата", "Shopan Ata", 43.54906, 53.38944),
]

# имя, email (или None), языки, специализации, объекты, ставка, стаж, bio,
# (выполнено заказов, целевая средняя оценка)
GUIDES = [
    ("Айдос Жаксылыков", "guide@demo.kz", ["en", "ru", "kk"], ["jeep", "photo"],
     ["bozjyra", "tuzbair", "bokty", "kyzylkup"], 25000, 8,
     "Джип-туры по Устюрту с 2018 года. Знаю лучшие точки для рассвета на Бозжыре.", (22, 4.85)),
    ("Динара Сейтқалиева", None, ["en", "de", "ru"], ["ethno", "sacred"],
     ["beket_ata", "shopan_ata", "shakpak_ata", "karaman_ata"], 30000, 6,
     "Историк по образованию. Подземные мечети, некрополи, легенды Мангышлака.", (14, 4.7)),
    ("Нурлан Абилов", None, ["en", "ru"], ["jeep", "camping"],
     ["bozjyra", "tuzbair", "sherkala", "torysh"], 22000, 4,
     "Кемпинги в пустыне, ночь под звёздами у Бозжыры.", (9, 4.5)),
    ("Айгерим Утепова", None, ["fr", "en", "ru"], ["photo", "hiking"],
     ["sherkala", "torysh", "kapamsay"], 28000, 5,
     "Фототуры для небольших групп, работаю с французскими агентствами.", (7, 4.9)),
    ("Ерлан Кенжебаев", None, ["ru", "kk"], ["jeep"],
     ["bozjyra", "bokty", "kyzylkup", "beket_ata"], 18000, 10,
     "Водитель-гид, 10 лет по Мангистау. Иностранные языки — нет.", (25, 4.65)),
    ("Мадина Ермекова", None, ["en", "tr", "ru"], ["ethno"],
     ["sultan_epe", "shakpak_ata", "zhygylgan"], 24000, 3,
     "Этно-программы, казахская кухня, встречи с мастерами.", (5, 4.45)),
    ("Санжар Тулегенов", None, ["en", "ru"], ["hiking", "camping"],
     ["kapamsay", "zhygylgan", "sultan_epe"], 20000, 2,
     "Пешие маршруты по каньонам Тупкарагана.", (2, 4.5)),
    ("Асель Нурмагамбетова", None, ["zh", "en", "ru"], ["ethno", "photo"],
     ["bozjyra", "sherkala", "beket_ata"], 35000, 2,
     "Училась в Урумчи. Пока единственный гид с китайским на площадке.", (3, 5.0)),
    ("Бауыржан Сарсенов", None, ["ar", "en"], ["sacred"],
     ["beket_ata", "shopan_ata", "shakpak_ata", "karaman_ata"], 30000, 7,
     "Паломнические маршруты по сакральным местам.", (6, 4.3)),
    ("Жанна Калиева", None, ["de", "en"], ["photo"],
     ["tuzbair", "sherkala", "karagiye"], 27000, 4,
     "Немецкие группы, фото на закате.", (4, 4.8)),
    ("Тимур Оразов", None, ["en", "ru"], ["jeep"],
     ["bozjyra", "kyzylkup"], 20000, 1, "Начинающий гид, свой Land Cruiser.", (0, 0)),
    ("Алия Досова", None, ["en", "ru", "kk"], ["hiking"],
     ["kapamsay", "sultan_epe"], 21000, 1, "Новичок на площадке.", (1, 5.0)),
]

COMPANIES = [
    ("Caspian Trails", "company@demo.kz"),
    ("Mangystau Explorer", None),
    ("Steppe Travel", None),
]
TOURISTS = [("Anna Müller", "tourist@demo.kz"), ("John Smith", None), ("Li Wei", None)]

REVIEW_TEXT = {
    5: ["Лучший день поездки. Всё чётко по времени, рассказывал интересно.",
        "Amazing guide, knew every viewpoint. Highly recommended!",
        "Sehr professionell, perfekte Organisation.",
        "Группа в восторге, будем работать ещё."],
    4: ["Хороший тур, немного задержались на старте.",
        "Great knowledge of the route, English could be a bit better.",
        "Всё понравилось, но хотелось больше остановок для фото."],
    3: ["Нормально, но опоздал на час."],
}


def ts(d: date) -> datetime:
    return datetime.combine(d, time(12, 0), tzinfo=timezone(timedelta(hours=5)))


def scores_for(target: float, n: int, rnd: random.Random) -> list[int]:
    """n оценок со средним около target."""
    out = []
    for _ in range(n):
        v = 5 if rnd.random() < (target - 4) else 4
        if target < 4.5 and rnd.random() < 0.08:
            v = 3
        out.append(v)
    return out


async def seed(reset: bool) -> None:
    await init_pool()
    db = pool()
    async with db.acquire() as conn, conn.transaction():
        if reset:
            await conn.execute(
                """TRUNCATE assignment_addons, guide_addons, request_safety, broadcasts, notifications, review_reports, reviews, payments, assignments,
                   offers, requests, companies, guides, sites, users, regions RESTART IDENTITY CASCADE"""
            )
        elif await conn.fetchval("SELECT count(*) FROM users"):
            print("База уже заполнена. Для пересоздания: python -m app.seed --reset")
            return

        rnd = random.Random(42)
        pw = hash_password(DEMO_PASSWORD)
        region = await conn.fetchval(
            """INSERT INTO regions (code, name_kk, name_ru, name_en)
               VALUES ('mangystau','Маңғыстау облысы','Мангистауская область','Mangystau Region') RETURNING id"""
        )
        site_id = {}
        for slug, kk, ru, en, lat, lon in SITES:
            site_id[slug] = await conn.fetchval(
                """INSERT INTO sites (region_id, slug, name_kk, name_ru, name_en, lat, lon)
                   VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""", region, slug, kk, ru, en, lat, lon,
            )

        async def user(role, name, email, n, lang="ru"):
            return await conn.fetchval(
                """INSERT INTO users (role, name, email, phone, password_hash, ui_lang, is_demo)
                   VALUES ($1,$2,$3,$4,$5,$6,TRUE) RETURNING id""",
                role, name, email, f"+7000000{n:04d}", pw, lang,
            )

        await user("admin", "Управление туризма Мангистауской области", "admin@demo.kz", 1)
        guides = []
        for i, (name, email, langs, specs, sites, rate, years, bio, stats) in enumerate(GUIDES):
            uid = await user("guide", name, email, 100 + i)
            await conn.execute(
                """INSERT INTO guides (user_id, region_id, languages, specializations, site_ids,
                       day_rate, experience_years, bio) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                uid, region, langs, specs, [site_id[s] for s in sites], rate, years, bio,
            )
            guides.append((uid, langs, [site_id[s] for s in sites], rate, stats))

        companies = []
        for i, (name, email) in enumerate(COMPANIES):
            uid = await user("company", name, email, 200 + i)
            await conn.execute(
                """INSERT INTO companies (user_id, region_id, name, plan, plan_until)
                   VALUES ($1,$2,$3,'season',$4)""",
                uid, region, name, date.today() + timedelta(days=30),
            )
            companies.append(uid)
        tourists = [await user("tourist", n, e, 300 + i, "en") for i, (n, e) in enumerate(TOURISTS)]
        clients = companies + tourists

        async def request(author, lang, d_from, days, sites, price, status, group=None):
            atype = "tourist" if author in tourists else "company"
            return await conn.fetchval(
                """INSERT INTO requests (author_id, author_type, region_id, date_from, date_to, site_ids,
                       language, group_size, price_per_day, status, is_demo, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,TRUE,$11) RETURNING id""",
                author, atype, region, d_from, d_from + timedelta(days=days - 1), sites, lang,
                group or rnd.randint(2, 8), price, status, ts(d_from - timedelta(days=rnd.randint(5, 20))),
            )

        async def assign(rid, guide, client, price, days, status):
            oid = await conn.fetchval(
                """INSERT INTO offers (request_id, guide_id, price_per_day, status)
                   VALUES ($1,$2,$3,'chosen') RETURNING id""", rid, guide, price,
            )
            return await conn.fetchval(
                """INSERT INTO assignments (request_id, offer_id, guide_id, client_id, price_per_day,
                       days, total, status, completed_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8, CASE WHEN $8='done' THEN now() END) RETURNING id""",
                rid, oid, guide, client, price, days, price * days, status,
            )

        today = date.today()
        # История: выполненные заказы с отзывами (июнь — сентябрь).
        for uid, langs, sites, rate, (done, target) in guides:
            foreign = [l for l in langs if l not in ("ru", "kk")] or langs
            for k, score in enumerate(scores_for(target, done, rnd)):
                lang = foreign[k % len(foreign)]
                d_from = today - timedelta(days=rnd.randint(10, 110))
                days = rnd.choice([1, 1, 2, 3])
                client = rnd.choice(clients)
                rid = await request(client, lang, d_from, days, rnd.sample(sites, min(2, len(sites))),
                                    rate, "done")
                aid = await assign(rid, uid, client, rate, days, "done")
                crit = [max(1, min(5, score + rnd.choice([0, 0, 0, -1]))) for _ in range(4)]
                text = rnd.choice(REVIEW_TEXT[score]) if rnd.random() < 0.75 else None
                await conn.execute(
                    """INSERT INTO reviews (assignment_id, author_id, target_id, target_role, overall,
                           c_route, c_language, c_punctuality, c_communication, text, created_at)
                       VALUES ($1,$2,$3,'guide',$4,$5,$6,$7,$8,$9,$10)""",
                    aid, client, uid, score, *crit, text, ts(d_from + timedelta(days=days)),
                )
                if rnd.random() < 0.6:  # гид оценивает заказчика
                    await conn.execute(
                        """INSERT INTO reviews (assignment_id, author_id, target_id, target_role, overall, created_at)
                           VALUES ($1,$2,$3,'client',$4,$5)""",
                        aid, uid, client, rnd.choice([5, 5, 4]), ts(d_from + timedelta(days=days)),
                    )
                if rnd.random() < 0.3 and client in tourists:
                    await conn.execute(
                        "INSERT INTO payments (kind, assignment_id, amount, status) VALUES ('deposit',$1,$2,'paid_test')",
                        aid, round(rate * days * 0.1),
                    )

        # Отмена гидом — системная оценка 1 (Нурлан).
        nurlan = guides[2]
        rid = await request(companies[1], "en", today - timedelta(days=40), 1, nurlan[2][:2], nurlan[3], "cancelled")
        aid = await assign(rid, nurlan[0], companies[1], nurlan[3], 1, "cancelled")
        await conn.execute("UPDATE assignments SET cancelled_by='guide', cancelled_at=now() WHERE id=$1", aid)
        await conn.execute(
            """INSERT INTO reviews (assignment_id, author_id, target_id, target_role, overall, is_system)
               VALUES ($1,NULL,$2,'guide',1,TRUE)""", aid, nurlan[0],
        )

        # Будущее: спрос по языкам. Китайский, корейский, японский — дефицит.
        s = site_id
        future = [
            ("zh", 3, 2, ["bozjyra", "tuzbair"], 40000), ("zh", 6, 3, ["bozjyra", "bokty", "beket_ata"], 38000),
            ("zh", 11, 1, ["sherkala", "torysh"], 35000), ("zh", 17, 2, ["bozjyra", "kyzylkup"], 42000),
            ("zh", 24, 2, ["tuzbair", "sherkala"], 40000), ("zh", 33, 3, ["bozjyra", "beket_ata"], 38000),
            ("zh", 41, 1, ["karagiye"], 35000),
            ("ko", 8, 2, ["bozjyra", "tuzbair"], 38000), ("ko", 29, 1, ["sherkala"], 35000),
            ("ja", 14, 2, ["bozjyra", "torysh"], 40000),
            ("de", 5, 2, ["tuzbair", "sherkala"], 30000), ("de", 19, 1, ["karagiye"], 28000),
            ("fr", 9, 2, ["torysh", "kapamsay"], 30000),
            ("ar", 12, 1, ["beket_ata", "shakpak_ata"], 30000),
            ("en", 2, 1, ["bozjyra"], 25000), ("en", 4, 2, ["bozjyra", "tuzbair"], 25000),
            ("en", 7, 1, ["kapamsay", "zhygylgan"], 22000), ("en", 13, 3, ["bozjyra", "bokty", "kyzylkup"], 26000),
            ("en", 21, 1, ["sherkala", "torysh"], 24000), ("en", 36, 2, ["tuzbair", "karagiye"], 25000),
        ]
        by_lang = {}
        for uid, langs, *_ in guides:
            for l in langs:
                by_lang.setdefault(l, []).append(uid)
        for n, (lang, offset, days, sites_, price) in enumerate(future):
            client = companies[n % len(companies)] if lang != "zh" or n % 3 else tourists[2]
            d_from = today + timedelta(days=offset)
            candidates = by_lang.get(lang, [])
            # Часть заявок уже закрыта, часть с откликами, остальные — без единого отклика.
            if candidates and lang == "en" and offset in (2, 4, 13):
                g = candidates[offset % len(candidates)]
                rid = await request(client, lang, d_from, days, [s[x] for x in sites_], price, "confirmed")
                await assign(rid, g, client, price, days, "confirmed")
            elif candidates and lang == "zh" and offset == 3:
                rid = await request(client, lang, d_from, days, [s[x] for x in sites_], price, "confirmed")
                await assign(rid, candidates[0], client, price, days, "confirmed")
            elif candidates and lang == "de" and offset == 5:
                rid = await request(client, lang, d_from, days, [s[x] for x in sites_], price, "confirmed")
                await assign(rid, candidates[0], client, price, days, "confirmed")
            else:
                rid = await request(client, lang, d_from, days, [s[x] for x in sites_], price, "open")
                if candidates and lang in ("en", "fr", "ar", "de"):
                    for g in candidates[:2]:
                        await conn.execute(
                            """INSERT INTO offers (request_id, guide_id, price_per_day)
                               VALUES ($1,$2,$3) ON CONFLICT DO NOTHING""",
                            rid, g, price + rnd.choice([0, 0, 2000, 5000]),
                        )
        await conn.execute("UPDATE requests SET created_at = now() - interval '2 days' WHERE created_at > now()")

        # Допуслуги у части гидов.
        ADDONS = {
            "Айдос Жаксылыков": [("drone", 25000, "tour"), ("photo", 15000, "tour"), ("catering", 6000, "person")],
            "Айгерим Утепова": [("photo", 20000, "tour"), ("reel", 18000, "tour")],
            "Нурлан Абилов": [("camping", 30000, "tour"), ("starlink", 12000, "tour"), ("catering", 5000, "person")],
            "Асель Нурмагамбетова": [("photo", 15000, "tour"), ("drone", 30000, "tour")],
            "Жанна Калиева": [("photo", 18000, "tour"), ("reel", 15000, "tour")],
            "Динара Сейтқалиева": [("catering", 7000, "person")],
        }
        for name, items in ADDONS.items():
            gid = await conn.fetchval("SELECT id FROM users WHERE name=$1", name)
            for kind, price, per in items:
                await conn.execute(
                    "INSERT INTO guide_addons (guide_id, kind, price, per) VALUES ($1,$2,$3,$4)",
                    gid, kind, price, per,
                )

        # Страны туристов у демо-заявок — для аналитики турпотока (без данных о здоровье).
        LANG_COUNTRIES = {"en": ["GB", "US", "NL", "AU", "CA", "IL"], "zh": ["CN"], "de": ["DE", "AT", "CH"],
                          "fr": ["FR"], "ar": ["AE", "SA"], "ko": ["KR"], "ja": ["JP"], "tr": ["TR"],
                          "ru": ["RU", "UZ", "KG", "AZ"], "kk": ["UZ", "KG"]}
        for r in await conn.fetch("SELECT id, language FROM requests"):
            pool_c = LANG_COUNTRIES.get(r["language"], ["GB"])
            await conn.execute(
                "INSERT INTO request_safety (request_id, countries) VALUES ($1,$2)",
                r["id"], [rnd.choice(pool_c)],
            )

        # Демо для питча: подтверждённый тур Айдоса с анкетой безопасности и допами.
        aidos = guides[0]
        anna = tourists[0]
        d_from = today + timedelta(days=9)
        rid = await request(anna, "en", d_from, 2, [site_id["bozjyra"], site_id["tuzbair"]], 25000, "confirmed", group=4)
        await conn.execute(
            """INSERT INTO request_safety (request_id, countries, diet, risks, epipen,
                   ice_name, ice_phone, note, consent_at)
               VALUES ($1,$2,$3,$4,TRUE,$5,$6,$7,now())""",
            rid, ["DE", "AT"], ["vegetarian", "nuts"], ["anaphylaxis", "motion_sickness"],
            "Klaus Müller", "+491700000000", "Одна туристка боится высоты — держитесь подальше от края обрывов.",
        )
        aid = await assign(rid, aidos[0], anna, 25000, 2, "confirmed")
        extras = []
        for kind, qty in (("drone", 1), ("catering", 4)):
            a = await conn.fetchrow("SELECT * FROM guide_addons WHERE guide_id=$1 AND kind=$2", aidos[0], kind)
            extras.append((a, qty, a["price"] * qty))
            await conn.execute(
                """INSERT INTO assignment_addons (assignment_id, addon_id, kind, price, per, qty, amount)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""", aid, a["id"], kind, a["price"], a["per"], qty, a["price"] * qty,
            )
        total = 25000 * 2 + sum(x[2] for x in extras)
        await conn.execute("UPDATE assignments SET total=$2 WHERE id=$1", aid, total)
        await conn.execute(
            "INSERT INTO payments (kind, assignment_id, amount, status) VALUES ('deposit',$1,$2,'paid_test')",
            aid, round(total * 0.1),
        )
        await rating.recompute_all(conn)

        levels = await conn.fetch(
            """SELECT u.name, u.rating, u.reviews_count, g.completed_count, g.level
               FROM guides g JOIN users u ON u.id=g.user_id ORDER BY u.rating DESC NULLS LAST"""
        )
        for r in levels:
            print(f"  {r['name']:<24} {str(r['rating']):>5}  отзывов {r['reviews_count']:>2}  "
                  f"заказов {r['completed_count']:>2}  {r['level']}")
    await close_pool()
    print("Готово. Демо-вход: admin@demo.kz, company@demo.kz, guide@demo.kz, tourist@demo.kz; пароль из DEMO_PASSWORD")


if __name__ == "__main__":
    asyncio.run(seed("--reset" in sys.argv))
