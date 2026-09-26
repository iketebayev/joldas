"""English-friendly отели Актау с прямыми контактами.

Только отели международных сетей: английский на ресепшене — стандарт бренда и указан
в профилях отелей. Каждый контакт — из официального сайта сети или OpenStreetMap,
ссылки на источники показываются на странице. Ничего не придумываем: нет данных — нет кнопки.
"""
from datetime import date

CHECKED_ON = date(2026, 9, 26)

HOTELS = [
    {
        "slug": "rixos",
        "name": "Rixos Water World Aktau",
        "brand": "Accor",
        "kind": "resort",
        "lat": 43.5067, "lon": 51.2968,
        "address": {"ru": "Тёплый пляж, 34 · ≈20 км от города",
                    "kk": "Жылы жағажай, 34 · қаладан ≈20 км",
                    "en": "Warm Beach 34 · ~20 km from the city"},
        "phone": "+7 7292 21 77 77",
        "whatsapp": "+7 701 091 73 84",
        "email": "Rixos.Aktau.RE@accor.com",
        "website": "https://www.rixos.com/en/hotel-resort/rixos-water-world-aktau",
        "instagram": "rixoswaterworldaktau",
        "sources": [("Accor", "https://all.accor.com/hotel/B7R0/index.en.shtml"),
                    ("OpenStreetMap", "https://www.openstreetmap.org/node/12083602869")],
    },
    {
        "slug": "renaissance",
        "name": "Renaissance by Sulo",
        "brand": "ex-Marriott",
        "kind": "city",
        "lat": 43.6455, "lon": 51.1514,
        "address": {"ru": "9 мкр, 1/1 · набережная", "kk": "9 шағын аудан, 1/1 · жағалау",
                    "en": "Microdistrict 9, 1/1 · seafront"},
        "phone": "+7 7292 30 06 00",
        "whatsapp": "+7 701 937 11 07",
        "email": None,
        "website": None,
        "instagram": None,
        "sources": [("OpenStreetMap", "https://www.openstreetmap.org/way/335575312"),
                    ("Tripadvisor", "https://www.tripadvisor.com/Hotel_Review-g674570-d585377-Reviews-Renaissance_By_Sulo-Aktau_Mangystau_Province.html")],
    },
    {
        "slug": "holiday-inn",
        "name": "Holiday Inn Aktau",
        "brand": "IHG",
        "kind": "city",
        "lat": 43.6385, "lon": 51.1650,
        "address": {"ru": "4 мкр, 73 · центр", "kk": "4 шағын аудан, 73 · орталық",
                    "en": "Microdistrict 4, bldg 73 · city centre"},
        "phone": "+7 7292 29 07 07",
        "whatsapp": None,
        "email": "reservation@hi-aktau.com",
        "website": "https://www.ihg.com/holidayinn/hotels/us/en/aktau/scohi/hoteldetail",
        "instagram": None,
        "sources": [("IHG", "https://www.ihg.com/holidayinn/hotels/us/en/aktau/scohi/hoteldetail"),
                    ("OpenStreetMap", "https://www.openstreetmap.org/way/327568453")],
    },
    {
        "slug": "holiday-inn-seaside",
        "name": "Holiday Inn Aktau – Seaside",
        "brand": "IHG",
        "kind": "seaside",
        "lat": None, "lon": None,
        "address": {"ru": "15 мкр, Самал · у моря", "kk": "15 шағын аудан, Самал · теңіз жағасы",
                    "en": "Microdistrict 15, Samal · seaside"},
        "phone": "+7 7292 29 08 00",
        "whatsapp": None,
        "email": "hiseaside@hi-aktau.com",
        "website": "https://www.ihg.com/holidayinn/hotels/us/en/aktau/scose/hoteldetail",
        "instagram": None,
        "sources": [("IHG", "https://www.ihg.com/holidayinn/hotels/us/en/aktau/scose/hoteldetail")],
    },
]

BY_SLUG = {h["slug"]: h for h in HOTELS}
