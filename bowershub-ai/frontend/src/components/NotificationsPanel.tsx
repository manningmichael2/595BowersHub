/**
 * NotificationsPanel — Settings → Notifications section.
 *
 * Reads/writes the user's global notification preferences via
 * `GET/PUT /api/me/notifications` (backed by `bh_notification_prefs`, the
 * `default` row). Channels the server can't deliver (no VAPID / Pushover config)
 * are shown disabled with an explanation rather than hidden, so the user
 * understands why a toggle is unavailable.
 */
import { useEffect, useState } from 'react'
import { api } from '../services/api'
import { toast } from '../stores/toast'
import { Switch, Spinner } from './ui'

interface Prefs {
  web_push: boolean
  pushover: boolean
  quiet_start: string | null
  quiet_end: string | null
}

interface Available {
  web_push: boolean
  pushover: boolean
}

const DEFAULTS: Prefs = {
  web_push: true,
  pushover: false,
  quiet_start: null,
  quiet_end: null,
}

export default function NotificationsPanel() {
  const [prefs, setPrefs] = useState<Prefs | null>(null)
  const [available, setAvailable] = useState<Available>({ web_push: false, pushover: false })
  const [loadError, setLoadError] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .get('/api/me/notifications')
      .then((res) => {
        if (!alive) return
        setPrefs({ ...DEFAULTS, ...(res.data.prefs ?? {}) })
        setAvailable(res.data.available ?? { web_push: false, pushover: false })
      })
      .catch(() => alive && setLoadError(true))
    return () => {
      alive = false
    }
  }, [])

  // Persist a partial change. Optimistic: update local state immediately, roll
  // back on failure.
  const save = async (delta: Partial<Prefs>) => {
    if (!prefs) return
    const next = { ...prefs, ...delta }
    setPrefs(next)
    setSaving(true)
    try {
      await api.put('/api/me/notifications', next)
    } catch (err: any) {
      setPrefs(prefs) // roll back
      toast.error(
        `Couldn't save notification settings: ${err.response?.data?.detail || 'Unknown error'}`,
      )
    } finally {
      setSaving(false)
    }
  }

  if (loadError) {
    return (
      <div className="space-y-6">
        <Header />
        <p className="text-sm text-danger">
          Couldn't load notification settings. Please try again later.
        </p>
      </div>
    )
  }

  if (!prefs) {
    return (
      <div className="space-y-6">
        <Header />
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Spinner /> Loading…
        </div>
      </div>
    )
  }

  // Quiet hours are paired — only meaningful when both are set.
  const setQuiet = (which: 'quiet_start' | 'quiet_end', value: string) =>
    save({ [which]: value || null } as Partial<Prefs>)

  return (
    <div className="space-y-6">
      <Header />

      <div className="space-y-4">
        <ChannelRow
          title="Web push"
          description="Browser/desktop push notifications on this and other signed-in devices."
          checked={prefs.web_push}
          available={available.web_push}
          unavailableNote="Web push isn't configured on the server (no VAPID keys)."
          onChange={(v) => save({ web_push: v })}
        />
        <ChannelRow
          title="Pushover"
          description="Push to your phone via the Pushover app."
          checked={prefs.pushover}
          available={available.pushover}
          unavailableNote="Pushover isn't configured on the server."
          onChange={(v) => save({ pushover: v })}
        />

        <div className="rounded-xl border border-border bg-background/40 p-4">
          <div className="text-sm font-medium text-text">Quiet hours</div>
          <div className="mt-1 text-xs leading-relaxed text-text-muted">
            Suppress notifications during these hours. Leave blank for none; a
            range that crosses midnight (e.g. 22:00 → 07:00) is supported.
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-text">
              From
              <input
                type="time"
                value={prefs.quiet_start ?? ''}
                onChange={(e) => setQuiet('quiet_start', e.target.value)}
                className="rounded-lg border border-border bg-surface px-2 py-1 text-sm text-text"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-text">
              To
              <input
                type="time"
                value={prefs.quiet_end ?? ''}
                onChange={(e) => setQuiet('quiet_end', e.target.value)}
                className="rounded-lg border border-border bg-surface px-2 py-1 text-sm text-text"
              />
            </label>
          </div>
        </div>
      </div>

      <p className="text-xs text-text-muted">{saving ? 'Saving…' : 'Changes save automatically.'}</p>
    </div>
  )
}

function Header() {
  return (
    <div>
      <h2 className="text-lg font-medium text-text">Notifications</h2>
      <p className="mt-1 text-sm text-text-muted">
        How and when BowersHub reaches you — briefings, budget alerts, and scheduled prompts.
      </p>
    </div>
  )
}

function ChannelRow({
  title,
  description,
  checked,
  available,
  unavailableNote,
  onChange,
}: {
  title: string
  description: string
  checked: boolean
  available: boolean
  unavailableNote: string
  onChange: (v: boolean) => void
}) {
  return (
    <label
      className={
        'flex items-center justify-between gap-3 rounded-xl border border-border bg-background/40 p-4 ' +
        (available ? '' : 'opacity-60')
      }
    >
      <div>
        <div className="text-sm font-medium text-text">{title}</div>
        <div className="mt-1 text-xs leading-relaxed text-text-muted">
          {available ? description : unavailableNote}
        </div>
      </div>
      <Switch
        aria-label={title}
        disabled={!available}
        checked={available && checked}
        onCheckedChange={onChange}
      />
    </label>
  )
}
