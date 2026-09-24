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
