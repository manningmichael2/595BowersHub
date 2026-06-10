-- Migration 013: Universal API Toolbox
-- Creates the dynamic API registry and usage logging tables.
-- This replaces the hardcoded skill system with a flexible, growing toolbox.

-- API Registry — describes available APIs that any layer can use
CREATE TABLE IF NOT EXISTS public.bh_api_registry (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    base_url    TEXT NOT NULL,
    description TEXT NOT NULL,
    auth_type   TEXT NOT NULL DEFAULT 'none',  -- none, header, bearer, api_key, basic
    auth_config JSONB,                          -- {"header": "X-Api-Key", "env_var": "BRAVE_API_KEY"}
    endpoints   JSONB NOT NULL DEFAULT '[]',    -- [{name, path, method, description, params}]
    headers     JSONB,                          -- default headers for all requests
    is_active   BOOLEAN NOT NULL DEFAULT true,
    usage_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes       TEXT                            -- human notes about this API
);

-- API Usage Log — tracks every external API call for pattern detection
CREATE TABLE IF NOT EXISTS public.bh_api_usage_log (
    id          SERIAL PRIMARY KEY,
    api_name    TEXT NOT NULL,
    url         TEXT NOT NULL,
    method      TEXT NOT NULL DEFAULT 'GET',
    status_code INTEGER,
    duration_ms INTEGER,
    called_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_usage_log_api_name ON public.bh_api_usage_log (api_name);
CREATE INDEX IF NOT EXISTS idx_api_usage_log_called_at ON public.bh_api_usage_log (called_at DESC);

-- Seed the registry with known APIs
-- These are the APIs the system already uses or can use (free, no auth)

INSERT INTO public.bh_api_registry (name, base_url, description, auth_type, endpoints) VALUES
(
    'espn',
    'https://site.api.espn.com/apis/site/v2/sports',
    'ESPN Sports API — live scores, box scores, standings, schedules, news for MLB, NFL, NBA, NHL, MLS, UFC, F1, Golf, Tennis, College sports. No auth required.',
    'none',
    '[
        {"name": "scoreboard", "path": "/{sport}/{league}/scoreboard", "method": "GET", "description": "Live/recent scores. Params: dates (YYYYMMDD)", "params": {"sport": "baseball|football|basketball|hockey|soccer|mma|racing|golf|tennis", "league": "mlb|nfl|nba|nhl|usa.1|ufc|f1|pga|atp|eng.1|esp.1", "dates": "YYYYMMDD"}},
        {"name": "summary", "path": "/{sport}/{league}/summary", "method": "GET", "description": "Full game detail with box score, play-by-play, stats. Params: event (game ID from scoreboard)", "params": {"event": "game ID number"}},
        {"name": "standings", "path": "/{sport}/{league}/standings", "method": "GET", "description": "Current league standings"},
        {"name": "teams", "path": "/{sport}/{league}/teams", "method": "GET", "description": "All teams in a league"},
        {"name": "team_detail", "path": "/{sport}/{league}/teams/{team_id}", "method": "GET", "description": "Specific team info, roster, stats"},
        {"name": "news", "path": "/{sport}/{league}/news", "method": "GET", "description": "Latest news/headlines for a sport. Params: limit (number)"}
    ]'::jsonb
),
(
    'wttr',
    'https://wttr.in',
    'Weather API — current conditions and forecast for any location worldwide. No auth required. Supports cities, zip codes, airports, landmarks.',
    'none',
    '[
        {"name": "forecast", "path": "/{location}", "method": "GET", "description": "Weather forecast. Use format=j1 for JSON.", "params": {"location": "city name, zip code, or airport code", "format": "j1"}}
    ]'::jsonb
),
(
    'npr_rss',
    'https://feeds.npr.org',
    'NPR News RSS — top stories, world news, business, science, technology. No auth required.',
    'none',
    '[
        {"name": "top_stories", "path": "/1001/rss.xml", "method": "GET", "description": "Top news stories"},
        {"name": "world", "path": "/1004/rss.xml", "method": "GET", "description": "World news"},
        {"name": "business", "path": "/1006/rss.xml", "method": "GET", "description": "Business/economy news"},
        {"name": "science", "path": "/1007/rss.xml", "method": "GET", "description": "Science news"},
        {"name": "technology", "path": "/1019/rss.xml", "method": "GET", "description": "Technology news"}
    ]'::jsonb
),
(
    'ars_technica',
    'https://feeds.arstechnica.com',
    'Ars Technica RSS — technology, science, gaming, policy news. No auth required.',
    'none',
    '[
        {"name": "all", "path": "/arstechnica/index", "method": "GET", "description": "All Ars Technica articles"}
    ]'::jsonb
),
(
    'open_meteo',
    'https://api.open-meteo.com/v1',
    'Open-Meteo Weather API — detailed weather forecasts, historical data, air quality. Free, no auth, high resolution.',
    'none',
    '[
        {"name": "forecast", "path": "/forecast", "method": "GET", "description": "Weather forecast by coordinates", "params": {"latitude": "decimal", "longitude": "decimal", "current_weather": "true", "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum"}},
        {"name": "geocoding", "path": "/geocoding/v1/search", "method": "GET", "description": "Convert city name to lat/lng", "params": {"name": "city name", "count": "1"}}
    ]'::jsonb
),
(
    'tmdb',
    'https://api.themoviedb.org/3',
    'The Movie Database API — movies, TV shows, ratings, cast, streaming availability. Requires free API key (set TMDB_API_KEY env var).',
    'api_key',
    '[
        {"name": "search_movie", "path": "/search/movie", "method": "GET", "description": "Search for movies by title", "params": {"query": "movie title"}},
        {"name": "search_tv", "path": "/search/tv", "method": "GET", "description": "Search for TV shows", "params": {"query": "show title"}},
        {"name": "trending", "path": "/trending/all/week", "method": "GET", "description": "Trending movies and TV this week"},
        {"name": "movie_detail", "path": "/movie/{id}", "method": "GET", "description": "Full movie details, cast, ratings"}
    ]'::jsonb
),
(
    'exchangerate',
    'https://open.er-api.com/v6',
    'Exchange Rate API — free currency conversion. No auth, 1500 requests/month.',
    'none',
    '[
        {"name": "latest", "path": "/latest/{base}", "method": "GET", "description": "Latest exchange rates. Base is 3-letter currency code (USD, EUR, GBP, etc)"}
    ]'::jsonb
),
(
    'wikipedia',
    'https://en.wikipedia.org/api/rest_v1',
    'Wikipedia API — article summaries, random articles, page content. No auth.',
    'none',
    '[
        {"name": "summary", "path": "/page/summary/{title}", "method": "GET", "description": "Get a summary of a Wikipedia article"},
        {"name": "random", "path": "/page/random/summary", "method": "GET", "description": "Get a random Wikipedia article summary"}
    ]'::jsonb
),
(
    'numbersapi',
    'http://numbersapi.com',
    'Numbers API — fun facts about numbers, dates, math. No auth.',
    'none',
    '[
        {"name": "number_fact", "path": "/{number}", "method": "GET", "description": "Fun fact about a number"},
        {"name": "date_fact", "path": "/{month}/{day}/date", "method": "GET", "description": "Historical fact about a date"},
        {"name": "math_fact", "path": "/{number}/math", "method": "GET", "description": "Math fact about a number"}
    ]'::jsonb
)
ON CONFLICT (name) DO NOTHING;
