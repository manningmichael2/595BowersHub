-- Migration 017: Seed routing patterns for L1 instant dispatch
-- These patterns fire before any AI call — zero cost, zero latency.
-- They cover the most common query shapes that don't need AI classification.

-- Weather patterns
INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)\b(weather|forecast|temperature|temp)\b', 'regex', s.id, '{}', 'Weather queries (weather, forecast, temp)', 50
FROM public.bh_skills s WHERE s.name = 'weather'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'Weather queries (weather, forecast, temp)');

INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)(?:how|what).*(?:cold|hot|warm|rain|snow|sunny)', 'regex', s.id, '{}', 'Weather via condition words (cold, hot, rain, snow)', 80
FROM public.bh_skills s WHERE s.name = 'weather'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'Weather via condition words (cold, hot, rain, snow)');

-- Sports patterns
INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)\b(tigers?|lions?|pistons?|red wings?|wolverines?)\b.*\b(score|game|play|win|lose|lost|won|pitch)', 'regex', s.id, '{"team": "$1"}', 'Detroit teams + game words → sports-score', 40
FROM public.bh_skills s WHERE s.name = 'sports-score'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'Detroit teams + game words → sports-score');

INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)\b(score|box\s*score|scoreboard|standings)\b.*\b(tigers?|lions?|pistons?|red wings?|mlb|nfl|nba|nhl)', 'regex', s.id, '{}', 'Score/standings + team/league', 45
FROM public.bh_skills s WHERE s.name = 'sports-score'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'Score/standings + team/league');

INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)who.*(pitch|start|playing|throwing)', 'regex', s.id, '{}', 'Who is pitching/starting/playing', 50
FROM public.bh_skills s WHERE s.name = 'sports-score'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'Who is pitching/starting/playing');

-- Finance patterns
INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)(?:what.s|show|check).*\b(balance|balances|accounts?)\b', 'regex', s.id, '{}', 'Balance/account queries', 50
FROM public.bh_skills s WHERE s.name = 'balances'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'Balance/account queries');

INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)how much.*(?:spend|spent|cost|paid)', 'regex', s.id, '{"question": "$0"}', 'Spending questions → ask-db', 60
FROM public.bh_skills s WHERE s.name = 'ask-db'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'Spending questions → ask-db');

INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)\b(spending|expenses?)\b.*\b(summary|breakdown|this month|last month)\b', 'regex', s.id, '{}', 'Spending summary/breakdown', 55
FROM public.bh_skills s WHERE s.name = 'spending-summary'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'Spending summary/breakdown');

-- Knowledge/recall patterns
INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)(?:what do I|do I)\s+know\s+about\s+(.+)', 'regex', s.id, '{"query": "$1"}', 'What do I know about X → recall', 40
FROM public.bh_skills s WHERE s.name = 'recall'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'What do I know about X → recall');

INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)^recall\s+(.+)', 'regex', s.id, '{"query": "$1"}', 'Bare "recall X" → recall skill', 30
FROM public.bh_skills s WHERE s.name = 'recall'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'Bare "recall X" → recall skill');

-- Remember patterns
INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)^remember\s+(.+)', 'regex', s.id, '{"topic": "$1"}', 'Bare "remember X" → remember skill', 30
FROM public.bh_skills s WHERE s.name = 'remember'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'Bare "remember X" → remember skill');

-- News patterns
INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority)
SELECT '(?i)(?:what.s|any|show|get).*\b(news|headlines)\b', 'regex', s.id, '{}', 'News/headlines queries', 50
FROM public.bh_skills s WHERE s.name = 'news'
AND NOT EXISTS (SELECT 1 FROM public.bh_patterns WHERE description = 'News/headlines queries');
