import os

APP_NAME = os.getenv("APP_NAME", "Joldas")
SECRET_KEY = os.environ["SECRET_KEY"]
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
DOMAIN = os.getenv("DOMAIN", "hack.ai-lab.kz")
DEPOSIT_PERCENT = int(os.getenv("DEPOSIT_PERCENT", "10"))
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo1234")

GREENAPI_URL = os.getenv("GREENAPI_URL", "").rstrip("/")
GREENAPI_INSTANCE = os.getenv("GREENAPI_INSTANCE", "")
GREENAPI_TOKEN = os.getenv("GREENAPI_TOKEN", "")

UI_LANGS = ("kk", "ru", "en")

# Языки, на которых гид может вести тур (коды ISO 639-1).
GUIDE_LANGS = ("en", "zh", "de", "fr", "es", "it", "ar", "tr", "ko", "ja", "ru", "kk")

SPECIALIZATIONS = ("jeep", "hiking", "ethno", "sacred", "photo", "camping")

# Правила рейтинга
BAYES_C = 5
BAYES_DEFAULT_MEAN = 4.5
LEVEL_EXPERIENCED = (5, 4.3)   # заказов, рейтинг
LEVEL_EXPERT = (20, 4.6)

# Тариф «Старт» у турфирмы: заявок в месяц
START_PLAN_MONTHLY_REQUESTS = 1
CANCEL_REFUND_HOURS = 48

# Цены — гипотеза для MVP, реальные платежи не подключены.
SEASON_PRICE = 29900     # ₸ в месяц, тариф «Сезон» для турфирм
URGENT_PRICE = 4900      # ₸ за поднятие заявки

# Анкета безопасности
COUNTRIES = ("CN", "DE", "FR", "GB", "US", "IT", "ES", "NL", "PL", "CH", "AT", "RU", "KR", "JP",
             "TR", "AE", "SA", "IN", "IL", "UZ", "KG", "AZ", "GE", "AU", "CA")
DIETS = ("vegetarian", "vegan", "halal", "lactose", "gluten", "nuts", "seafood", "no_trad_dairy")
RISKS = ("anaphylaxis", "asthma", "cardio", "motion_sickness", "drug_allergy")
SAFETY_RETENTION_DAYS = 30

# Допуслуги гидов
ADDON_KINDS = ("drone", "photo", "reel", "camping", "starlink", "catering")

# Въезд в госпарк «Кызылсай» с 1.09.2026 (inaktau.kz). Оплату через Halyk проводит гид,
# турист возмещает её отдельно от дневной ставки — без комиссии площадки.
MRP = 4325                      # 1 МРП в 2026 году, ₸
PARK_SITES = ("bozjyra", "tuzbair", "kyzylkup", "bokty")
FEE_TRAIL_MRP = 0.2             # туристская тропа, с человека в сутки
FEE_FOREIGN_MULT = 2            # иностранцам — двойной тариф
FEE_VEHICLE_MRP = {"car": 0.7, "minibus": 2.7, "bus": 5.0, "bus_big": 7.0}
SEATS_PER_CAR = 4

# Валюты цены в заявке; внутри всё считается в тенге.
CURRENCIES = ("KZT", "USD", "EUR", "CNY")
CURRENCY_SIGN = {"KZT": "₸", "USD": "$", "EUR": "€", "CNY": "¥"}
RATES_REFRESH_HOURS = 6

# Туры агентств
TRANSPORT = ("tour", "car", "none")
TOUR_INCLUDES = ("transport", "guide", "meals", "camping", "entry_fee")

# Каналы связи до бронирования и их порядок для региона туриста.
CHANNELS = ("whatsapp", "instagram", "rednote", "x")
CHANNEL_ORDER = {"cn": ("rednote", "whatsapp", "instagram", "x"),
                 "cis": ("whatsapp", "instagram", "x", "rednote"),
                 "west": ("whatsapp", "instagram", "x", "rednote")}
CIS_COUNTRIES = ("RU", "UZ", "KG", "AZ", "GE", "KZ")

# Верификация личности и видеовизитка.
MEDIA_DIR = os.getenv("MEDIA_DIR", "/data/media")
KYC_KEY = os.getenv("KYC_KEY", "")
KYC_REQUIRED = os.getenv("KYC_REQUIRED", "1") == "1"   # без проверки гид не откликается на заявки
KYC_PENDING_DAYS = 30                                   # непроверенные сканы удаляются
DOC_TYPES = ("id_card", "passport")
# Задания для живого селфи: два случайных на попытку, модератор сверяет жест на кадре.
KYC_CHALLENGES = ("palm", "two_fingers", "thumb_up", "turn_left", "turn_right", "touch_ear")
PHOTO_MAX_MB = 10
VIDEO_MAX_MB = 50
VIDEO_MIN_SEC, VIDEO_MAX_SEC = 30, 60
VIDEO_LEVELS = ("fluent", "conversational", "basic")
