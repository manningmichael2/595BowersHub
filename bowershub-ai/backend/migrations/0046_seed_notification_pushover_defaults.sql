-- 0046 — seed per-user notification prefs so the alert-routing cutover keeps
-- delivering on Pushover.
--
-- Context: alerts (budgets/inbox/reminders/gameday) used to post straight to the
-- single shared Pushover account, ignoring per-user prefs. They now route
-- through NotificationService.send()/notify_users(), which honors each user's
-- bh_notification_prefs. The hardcoded fallback for a user with no row is
-- web_push=on / pushover=OFF — so without seeding, existing household members
-- would silently stop getting Pushover alerts after this deploy.
--
-- Seed each currently-active user a `default` row with pushover=on (matching
-- today's behavior). Idempotent: ON CONFLICT DO NOTHING preserves any prefs a
-- user has already set via Settings → Notifications. New users created later get
-- the opt-in default (pushover off) until they enable it themselves.

INSERT INTO public.bh_notification_prefs (user_id, event_type, web_push, pushover)
SELECT id, 'default', true, true
  FROM public.bh_users
 WHERE is_active = true
ON CONFLICT (user_id, event_type) DO NOTHING;
