CREATE TABLE IF NOT EXISTS games (
    app_id          BIGINT PRIMARY KEY,
    title           TEXT NOT NULL,
    release_date    DATE,
    win             BOOLEAN NOT NULL DEFAULT FALSE,
    mac             BOOLEAN NOT NULL DEFAULT FALSE,
    linux           BOOLEAN NOT NULL DEFAULT FALSE,
    rating_category TEXT,
    positive_ratio  NUMERIC(5,4),
    total_reviews   INTEGER NOT NULL DEFAULT 0,
    price_usd       NUMERIC(10,2) NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    user_id        BIGINT PRIMARY KEY,
    total_products INTEGER NOT NULL DEFAULT 0,
    total_reviews  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recommendations (
    review_id      BIGINT PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES users(user_id),
    app_id         BIGINT NOT NULL REFERENCES games(app_id),
    is_recommended BOOLEAN NOT NULL,
    hours_played   NUMERIC(10,2),
    review_date    DATE,
    helpful        INTEGER,
    funny          INTEGER
);
CREATE INDEX IF NOT EXISTS idx_rec_app  ON recommendations(app_id);
CREATE INDEX IF NOT EXISTS idx_rec_date ON recommendations(review_date);

-- Riwayat hasil live polling (dasar panel Live Updates).
CREATE TABLE IF NOT EXISTS live_updates (
    id                     BIGSERIAL PRIMARY KEY,
    app_id                 BIGINT NOT NULL REFERENCES games(app_id),
    polled_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    price_usd              NUMERIC(10,2),
    steam_recommendations  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_live_app_time ON live_updates(app_id, polled_at DESC);

-- Penampung data untuk mode replay (struktur sama dengan recommendations, tanpa FK).
CREATE TABLE IF NOT EXISTS replay_buffer (LIKE recommendations INCLUDING DEFAULTS);

-- Materialized View utama dasbor (satu-satunya definisi is_hidden_gem sesuai D-3).
-- Dikonversi dari VIEW biasa ke MATERIALIZED VIEW pada T5 setelah EXPLAIN ANALYZE > 1 detik pada data penuh.
CREATE MATERIALIZED VIEW IF NOT EXISTS game_stats AS
WITH med AS (
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY total_reviews) AS median_reviews FROM games
)
SELECT
    g.app_id, g.title, g.release_date, g.win, g.mac, g.linux,
    g.rating_category, g.positive_ratio, g.total_reviews, g.price_usd,
    COUNT(r.review_id)                                     AS total_recommendations,
    AVG(CASE WHEN r.is_recommended THEN 1.0 ELSE 0.0 END)  AS recommended_share,
    AVG(r.hours_played)                                    AS avg_hours_played,
    (g.positive_ratio >= 0.80 AND g.total_reviews < med.median_reviews) AS is_hidden_gem
FROM games g
CROSS JOIN med
LEFT JOIN recommendations r ON r.app_id = g.app_id
GROUP BY g.app_id, med.median_reviews;

CREATE UNIQUE INDEX IF NOT EXISTS idx_game_stats_app_id
    ON game_stats(app_id);
CREATE INDEX IF NOT EXISTS idx_game_stats_hidden_gem
    ON game_stats(is_hidden_gem, positive_ratio DESC, total_reviews DESC);
