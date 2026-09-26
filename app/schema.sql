-- Схема применяется при каждом старте: всё идемпотентно.

CREATE TABLE IF NOT EXISTS regions (
    id      SERIAL PRIMARY KEY,
    code    TEXT UNIQUE NOT NULL,
    name_kk TEXT NOT NULL,
    name_ru TEXT NOT NULL,
    name_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    role          TEXT NOT NULL CHECK (role IN ('guide','company','tourist','admin')),
    name          TEXT NOT NULL,
    email         TEXT UNIQUE,
    phone         TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    ui_lang       TEXT NOT NULL DEFAULT 'ru',
    -- рейтинг как заказчика (для турфирм и туристов) или как гида
    rating        NUMERIC(3,2),
    reviews_count INT NOT NULL DEFAULT 0,
    is_demo       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS sites (
    id        SERIAL PRIMARY KEY,
    region_id INT NOT NULL REFERENCES regions(id),
    slug      TEXT UNIQUE NOT NULL,
    name_kk   TEXT NOT NULL,
    name_ru   TEXT NOT NULL,
    name_en   TEXT NOT NULL,
    lat       DOUBLE PRECISION NOT NULL,
    lon       DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS guides (
    user_id          INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    region_id        INT NOT NULL REFERENCES regions(id),
    languages        TEXT[] NOT NULL DEFAULT '{}',
    specializations  TEXT[] NOT NULL DEFAULT '{}',
    site_ids         INT[]  NOT NULL DEFAULT '{}',
    day_rate         INT,
    experience_years INT,
    bio              TEXT,
    external_links   TEXT,
    completed_count  INT  NOT NULL DEFAULT 0,
    level            TEXT NOT NULL DEFAULT 'novice' CHECK (level IN ('novice','experienced','expert'))
);

CREATE TABLE IF NOT EXISTS companies (
    user_id   INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    region_id INT NOT NULL REFERENCES regions(id),
    name      TEXT NOT NULL,
    plan      TEXT NOT NULL DEFAULT 'start' CHECK (plan IN ('start','season')),
    plan_until DATE
);

CREATE TABLE IF NOT EXISTS requests (
    id            SERIAL PRIMARY KEY,
    author_id     INT NOT NULL REFERENCES users(id),
    author_type   TEXT NOT NULL CHECK (author_type IN ('company','tourist')),
    region_id     INT NOT NULL REFERENCES regions(id),
    date_from     DATE NOT NULL,
    date_to       DATE NOT NULL,
    site_ids      INT[] NOT NULL DEFAULT '{}',
    language      TEXT NOT NULL,
    group_size    INT NOT NULL DEFAULT 1 CHECK (group_size > 0),
    price_per_day INT NOT NULL CHECK (price_per_day > 0),
    note          TEXT,
    urgent        BOOLEAN NOT NULL DEFAULT FALSE,
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open','matched','confirmed','done','cancelled')),
    is_demo       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (date_to >= date_from)
);
CREATE INDEX IF NOT EXISTS requests_status_idx ON requests (status);

CREATE TABLE IF NOT EXISTS offers (
    id            SERIAL PRIMARY KEY,
    request_id    INT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    guide_id      INT NOT NULL REFERENCES users(id),
    price_per_day INT NOT NULL CHECK (price_per_day > 0),
    message       TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','chosen','rejected','withdrawn')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (request_id, guide_id)
);

CREATE TABLE IF NOT EXISTS assignments (
    id            SERIAL PRIMARY KEY,
    request_id    INT NOT NULL REFERENCES requests(id),
    offer_id      INT NOT NULL REFERENCES offers(id),
    guide_id      INT NOT NULL REFERENCES users(id),
    client_id     INT NOT NULL REFERENCES users(id),
    price_per_day INT NOT NULL,
    days          INT NOT NULL,
    total         INT NOT NULL,
    status        TEXT NOT NULL
                  CHECK (status IN ('awaiting_payment','confirmed','done','cancelled')),
    cancelled_by  TEXT CHECK (cancelled_by IN ('client','guide')),
    cancelled_at  TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- У заявки может быть только одно живое назначение.
CREATE UNIQUE INDEX IF NOT EXISTS assignments_one_active
    ON assignments (request_id) WHERE status <> 'cancelled';

CREATE TABLE IF NOT EXISTS payments (
    id            SERIAL PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('deposit','refund','subscription')),
    assignment_id INT REFERENCES assignments(id),
    company_id    INT REFERENCES users(id),
    amount        INT NOT NULL,
    status        TEXT NOT NULL,
    provider      TEXT NOT NULL DEFAULT 'test',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reviews (
    id               SERIAL PRIMARY KEY,
    assignment_id    INT NOT NULL REFERENCES assignments(id),
    author_id        INT REFERENCES users(id),          -- NULL у системных оценок
    target_id        INT NOT NULL REFERENCES users(id),
    target_role      TEXT NOT NULL CHECK (target_role IN ('guide','client')),
    overall          SMALLINT NOT NULL CHECK (overall BETWEEN 1 AND 5),
    c_route          SMALLINT CHECK (c_route BETWEEN 1 AND 5),
    c_language       SMALLINT CHECK (c_language BETWEEN 1 AND 5),
    c_punctuality    SMALLINT CHECK (c_punctuality BETWEEN 1 AND 5),
    c_communication  SMALLINT CHECK (c_communication BETWEEN 1 AND 5),
    text             TEXT,
    reply            TEXT,
    reply_at         TIMESTAMPTZ,
    is_system        BOOLEAN NOT NULL DEFAULT FALSE,
    hidden           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Один отзыв от одного автора на один заказ.
CREATE UNIQUE INDEX IF NOT EXISTS reviews_one_per_author
    ON reviews (assignment_id, author_id) WHERE author_id IS NOT NULL;
-- Одна системная оценка (штраф за отмену) на заказ.
CREATE UNIQUE INDEX IF NOT EXISTS reviews_one_system
    ON reviews (assignment_id) WHERE is_system;

CREATE TABLE IF NOT EXISTS review_reports (
    id          SERIAL PRIMARY KEY,
    review_id   INT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    reporter_id INT NOT NULL REFERENCES users(id),
    reason      TEXT,
    resolved    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (review_id, reporter_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id         SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    link       TEXT,
    whatsapp   TEXT NOT NULL DEFAULT 'off' CHECK (whatsapp IN ('off','sent','failed')),
    is_read    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications (user_id, is_read);

CREATE TABLE IF NOT EXISTS broadcasts (
    id         SERIAL PRIMARY KEY,
    language   TEXT NOT NULL,
    text       TEXT NOT NULL,
    recipients INT NOT NULL,
    created_by INT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Анкета безопасности группы. Отдельная таблица: доступ только автору и назначенному гиду,
-- удаляется через 30 дней после тура (services/safety.py::purge).
CREATE TABLE IF NOT EXISTS request_safety (
    request_id INT PRIMARY KEY REFERENCES requests(id) ON DELETE CASCADE,
    countries  TEXT[] NOT NULL DEFAULT '{}',
    diet       TEXT[] NOT NULL DEFAULT '{}',
    risks      TEXT[] NOT NULL DEFAULT '{}',
    epipen     BOOLEAN NOT NULL DEFAULT FALSE,
    ice_name   TEXT,
    ice_phone  TEXT,
    note       TEXT,
    consent_at TIMESTAMPTZ
);

-- Допуслуги гида и их снимок в заказе на момент выбора.
CREATE TABLE IF NOT EXISTS guide_addons (
    id       SERIAL PRIMARY KEY,
    guide_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind     TEXT NOT NULL CHECK (kind IN ('drone','photo','reel','camping','starlink','catering')),
    price    INT  NOT NULL CHECK (price > 0),
    per      TEXT NOT NULL CHECK (per IN ('tour','person')),
    active   BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (guide_id, kind)
);

CREATE TABLE IF NOT EXISTS assignment_addons (
    assignment_id INT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    addon_id      INT REFERENCES guide_addons(id) ON DELETE SET NULL,
    kind          TEXT NOT NULL,
    price         INT  NOT NULL,
    per           TEXT NOT NULL,
    qty           INT  NOT NULL,
    amount        INT  NOT NULL,
    PRIMARY KEY (assignment_id, kind)
);

-- Въезд в госпарк: сумма фиксируется при выборе гида; платит гид, возмещает турист отдельно.
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS entry_fee INT NOT NULL DEFAULT 0;

-- Курсы валют: 1 единица валюты = kzt тенге. Обновляются каждые 6 часов (services/rates.py).
CREATE TABLE IF NOT EXISTS exchange_rates (
    code       TEXT PRIMARY KEY,
    kzt        NUMERIC(12,4) NOT NULL,
    source     TEXT NOT NULL,
    rate_date  TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Валюта, в которой заказчик указал цену; price_per_day всегда хранится в тенге.
ALTER TABLE requests ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'KZT';
ALTER TABLE requests ADD COLUMN IF NOT EXISTS price_original NUMERIC(12,2);

-- Как турист едет: свой тур, своя машина или ни того, ни другого (тогда предлагаем туры агентств).
ALTER TABLE requests ADD COLUMN IF NOT EXISTS transport TEXT CHECK (transport IN ('tour','car','none'));

-- Готовые туры турагентств. Показываются только у агентств с активным тарифом «Сезон».
CREATE TABLE IF NOT EXISTS tours (
    id               SERIAL PRIMARY KEY,
    company_id       INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    description      TEXT,
    days             INT  NOT NULL CHECK (days BETWEEN 1 AND 30),
    price_per_person INT  NOT NULL CHECK (price_per_person > 0),
    languages        TEXT[] NOT NULL DEFAULT '{}',
    site_ids         INT[]  NOT NULL DEFAULT '{}',
    includes         TEXT[] NOT NULL DEFAULT '{}',
    max_group        INT  NOT NULL DEFAULT 8 CHECK (max_group > 0),
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tour_bookings (
    id         SERIAL PRIMARY KEY,
    tour_id    INT NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
    tourist_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date_from  DATE NOT NULL,
    group_size INT  NOT NULL CHECK (group_size > 0),
    total      INT  NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','confirmed','declined','cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Каналы связи гида до бронирования (WhatsApp, Instagram, RedNote, X).
ALTER TABLE guides ADD COLUMN IF NOT EXISTS whatsapp     TEXT;
ALTER TABLE guides ADD COLUMN IF NOT EXISTS instagram    TEXT;
ALTER TABLE guides ADD COLUMN IF NOT EXISTS rednote_id   TEXT;
ALTER TABLE guides ADD COLUMN IF NOT EXISTS rednote_link TEXT;
ALTER TABLE guides ADD COLUMN IF NOT EXISTS x_handle     TEXT;

-- Клики по кнопкам связи (гиды и отели) — аналитика обращений по каналам.
CREATE TABLE IF NOT EXISTS contact_clicks (
    id          SERIAL PRIMARY KEY,
    target_type TEXT NOT NULL CHECK (target_type IN ('guide','hotel')),
    target_ref  TEXT NOT NULL,
    channel     TEXT NOT NULL,
    user_id     INT REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS contact_clicks_created ON contact_clicks (created_at);

-- Верификация личности гида. Сканы документа и селфи хранятся зашифрованными и удаляются
-- сразу после решения модератора (или через 30 дней без решения) — остаётся только статус.
ALTER TABLE guides ADD COLUMN IF NOT EXISTS id_verified_at TIMESTAMPTZ;
ALTER TABLE guides ADD COLUMN IF NOT EXISTS photo TEXT;        -- одобренное фото профиля

CREATE TABLE IF NOT EXISTS guide_kyc (
    id            SERIAL PRIMARY KEY,
    guide_id      INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    doc_type      TEXT NOT NULL CHECK (doc_type IN ('id_card','passport')),
    doc_file      TEXT,              -- зашифрованный файл; NULL после удаления
    selfie_files  TEXT[],            -- кадры живого селфи с заданиями; NULL после удаления
    challenges    TEXT[] NOT NULL,   -- какие задания выпали (жесты), по порядку кадров
    photo_file    TEXT,              -- кандидат в фото профиля
    consent_at    TIMESTAMPTZ NOT NULL,
    checks        TEXT[] NOT NULL DEFAULT '{}',   -- что подтвердил модератор
    reject_reason TEXT,
    reviewer_id   INT REFERENCES users(id),
    reviewed_at   TIMESTAMPTZ,
    purged_at     TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS guide_kyc_guide ON guide_kyc (guide_id, created_at DESC);

-- Видеовизитка: загрузка → обработка воркером (перекодирование, постер, превью, громкость,
-- распознавание языка и субтитры) → модерация с оценкой уровня языка → показ.
CREATE TABLE IF NOT EXISTS guide_videos (
    id            SERIAL PRIMARY KEY,
    guide_id      INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token         TEXT NOT NULL UNIQUE,       -- имя папки с файлами
    lang          TEXT NOT NULL,              -- заявленный язык визитки
    status        TEXT NOT NULL DEFAULT 'processing'
                  CHECK (status IN ('processing','review','approved','rejected','failed','replaced')),
    duration      REAL,
    size_bytes    BIGINT,
    mean_volume   REAL,                       -- дБ, для проверки звука
    speech_ratio  REAL,                       -- доля времени с речью
    detected_lang TEXT,
    detected_prob REAL,
    subtitles     JSONB NOT NULL DEFAULT '{}',  -- {"fr": "WEBVTT…", "en": "WEBVTT…"}
    level         TEXT CHECK (level IN ('fluent','conversational','basic')),
    error         TEXT,
    reject_reason TEXT,
    reviewer_id   INT REFERENCES users(id),
    reviewed_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS guide_videos_guide ON guide_videos (guide_id, created_at DESC);

-- Подтверждённый по видео уровень языка: бейдж «English · Fluent · видео».
CREATE TABLE IF NOT EXISTS guide_lang_levels (
    guide_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lang        TEXT NOT NULL,
    level       TEXT NOT NULL CHECK (level IN ('fluent','conversational','basic')),
    video_id    INT REFERENCES guide_videos(id) ON DELETE SET NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guide_id, lang)
);

-- Демо-гиды из сида считаются прошедшими проверку, иначе демо-сценарии встанут.
UPDATE guides g SET id_verified_at = now()
FROM users u WHERE u.id = g.user_id AND u.is_demo AND g.id_verified_at IS NULL;

-- Контакты гида закрыты до оплаты депозита. Суммы брони фиксируются в заказе:
-- deposit_amount (10% — выручка площадки, онлайн) и balance_to_guide (90% — гиду при встрече).
ALTER TABLE guides ADD COLUMN IF NOT EXISTS telegram TEXT;
ALTER TABLE guides ADD COLUMN IF NOT EXISTS vehicle_details TEXT;
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS deposit_amount INT;
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS balance_to_guide INT;
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS contacts_unlocked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS deposit_paid_at TIMESTAMPTZ;
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS voucher_code TEXT UNIQUE;
ALTER TABLE requests ADD COLUMN IF NOT EXISTS direct BOOLEAN NOT NULL DEFAULT FALSE;  -- бронь напрямую из профиля

-- Заказы до этой версии: суммы и флаг по старым правилам (депозит оплачен → контакты открыты;
-- турфирма депозит не платит, контакты — после подтверждения).
UPDATE assignments a SET
    deposit_amount   = CASE WHEN r.author_type = 'tourist' THEN round(a.total * 0.10) ELSE 0 END,
    balance_to_guide = a.total - CASE WHEN r.author_type = 'tourist' THEN round(a.total * 0.10) ELSE 0 END
FROM requests r WHERE r.id = a.request_id AND a.deposit_amount IS NULL;
UPDATE assignments a SET contacts_unlocked = TRUE,
    deposit_paid_at = (SELECT min(p.created_at) FROM payments p WHERE p.assignment_id = a.id AND p.kind = 'deposit')
WHERE a.status IN ('confirmed','done') AND NOT a.contacts_unlocked AND a.voucher_code IS NULL;
UPDATE assignments SET voucher_code = 'JL-' || upper(substr(md5(id::text || created_at::text), 1, 6))
WHERE contacts_unlocked AND voucher_code IS NULL;

-- Роли аналитики: финансовый админ (P&L площадки) и госнаблюдатель (макропоказатели региона).
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('guide','company','tourist','admin','finance_admin','gov_observer'));

-- Воронка прямой брони: просмотр карточки → выбор даты → бронь → оплата депозита.
CREATE TABLE IF NOT EXISTS funnel_events (
    id         BIGSERIAL PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('view','date','booking','paid')),
    guide_id   INT REFERENCES users(id) ON DELETE CASCADE,
    visitor    TEXT NOT NULL,          -- id посетителя из сессии (не персональные данные)
    is_demo    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS funnel_events_created ON funnel_events (created_at);
