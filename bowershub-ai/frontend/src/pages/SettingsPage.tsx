/**
 * SettingsPage — thin shell hosting section-based settings (R12.1).
 *
 * Sections (in order, R12.1):
 *   Profile, Appearance, Voice, Notifications, Briefing, Context Capture,
 *   Scheduled Prompts.
 *
 * An Admin entry is appended only when the current user has admin role
 * (R12.5). Authenticated-only — `App.tsx` already guards routing on
 * `useAuthStore().user` (R12.7).
 *
 * Each section is a separate component; this page is just a navigator + pane.
 * Section components live under `frontend/src/components/`. Sections that
 * have not been implemented yet are rendered as inline placeholders so the
 * navigation works end-to-end while their dedicated components ship.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, ChevronRight } from 'lucide-react'
import { useAuthStore } from '../stores/auth'
import { useSettingsStore } from '../stores/settings'
import { useFeatures } from '../hooks/useFeatures'
import { useBreakpoint } from '../hooks/useBreakpoint'
import { api } from '../services/api'
import { toast } from '../stores/toast'
import AppearancePanel from '../components/AppearancePanel'
import VoicePanel from '../components/VoicePanel'
import { Button, Badge, Switch } from '../components/ui'

type SectionId =
  | 'profile'
  | 'appearance'
  | 'navigation'
  | 'voice'
  | 'notifications'
  | 'briefing'
  | 'context-capture'
  | 'scheduled-prompts'
  | 'labs'
  | 'admin'

interface SectionDef {
  id: SectionId
  label: string
  icon: string
}

const BASE_SECTIONS: SectionDef[] = [
  { id: 'profile', label: 'Profile', icon: '👤' },
  { id: 'appearance', label: 'Appearance', icon: '🎨' },
  { id: 'navigation', label: 'Navigation', icon: '🧭' },
  { id: 'voice', label: 'Voice', icon: '🎙️' },
  { id: 'notifications', label: 'Notifications', icon: '🔔' },
  { id: 'briefing', label: 'Briefing', icon: '🌅' },
  { id: 'context-capture', label: 'Context Capture', icon: '📥' },
  { id: 'labs', label: 'Labs', icon: '🧪' },
  { id: 'scheduled-prompts', label: 'Scheduled Prompts', icon: '⏰' },
]

const ADMIN_SECTION: SectionDef = { id: 'admin', label: 'Admin', icon: '🛠️' }

/** Renders the active section's pane. Sections that link out (scheduled
 * prompts, admin) never reach here — handleSelect navigates away instead. */
function SectionPane({ id }: { id: SectionId }) {
  switch (id) {
    case 'profile':
      return <ProfileSection />
    case 'appearance':
      return <AppearancePanel />
    case 'navigation':
      return <NavigationSection />
    case 'voice':
      return <VoicePanel />
    case 'notifications':
      return (
        <PlaceholderSection
          title="Notifications"
          description="Daily briefing and budget alert preferences. Coming soon."
        />
      )
    case 'briefing':
      return (
        <PlaceholderSection
          title="Briefing"
          description="Morning card workspace and briefing schedule. Coming soon."
        />
      )
    case 'context-capture':
      return (
        <PlaceholderSection
          title="Context Capture"
          description="Background context-capture preferences. Coming soon."
        />
      )
    case 'labs':
      return <LabsSection />
    default:
      return null
  }
}

export default function SettingsPage() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const { isDesktop } = useBreakpoint()
  // null = no section drilled into. On desktop a pane is always shown (defaults
  // to Profile); on mobile null means the section LIST is shown (master-detail).
  const [activeSection, setActiveSection] = useState<SectionId | null>(null)

  // R12.5 — append Admin entry only when user has admin role.
  const sections: SectionDef[] =
    user?.role === 'admin' ? [...BASE_SECTIONS, ADMIN_SECTION] : BASE_SECTIONS

  const handleSelect = (id: SectionId) => {
    // R12.4 — Scheduled Prompts links out to the standalone page.
    if (id === 'scheduled-prompts') {
      navigate('/scheduled-prompts')
      return
    }
    // R12.5 — Admin entry opens the Admin Console (currently /admin).
    if (id === 'admin') {
      navigate('/admin')
      return
    }
    setActiveSection(id)
  }

  const paneSection = activeSection ?? 'profile' // desktop always shows a pane
  // Mobile drills into a single section; back returns to the list.
  const mobilePaneOpen = !isDesktop && activeSection !== null

  return (
    // The app body is locked to `overflow: hidden` (see index.css); this page
    // manages its own scroll within the shell content area.
    <div className="flex h-full flex-col bg-surface text-text">
      {/* Header — on a mobile drill-in, the back returns to the section LIST
          (not browser-back); otherwise just the title. App-level navigation is
          owned by the shell chrome (rail / drawer / top bar). */}
      <div className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-3">
        {mobilePaneOpen ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setActiveSection(null)}
            aria-label="Back to settings list"
          >
            <ArrowLeft size={16} aria-hidden />
            Settings
          </Button>
        ) : (
          <h1 className="text-lg font-medium">Settings</h1>
        )}
      </div>

      {!isDesktop ? (
        // ---- Mobile: master-detail (full-width list → drilled-in pane) ----
        activeSection === null ? (
          <nav className="flex-1 overflow-y-auto" aria-label="Settings sections">
            {sections.map((s) => (
              <button
                key={s.id}
                onClick={() => handleSelect(s.id)}
                className="flex w-full items-center gap-3 border-b border-border px-4 py-3.5 text-left text-sm text-text transition-colors hover:bg-surface-light/60"
              >
                <span aria-hidden="true" className="text-base">
                  {s.icon}
                </span>
                <span className="flex-1">{s.label}</span>
                <ChevronRight size={16} className="shrink-0 text-text-muted" aria-hidden />
              </button>
            ))}
          </nav>
        ) : (
          <main className="flex-1 overflow-y-auto p-4">
            <SectionPane id={paneSection} />
          </main>
        )
      ) : (
        // ---- Desktop: persistent sidebar + pane ----
        <div className="mx-auto flex w-full max-w-5xl flex-1 min-h-0 gap-6 overflow-y-auto p-6">
          <nav className="flex w-56 shrink-0 flex-col gap-1" aria-label="Settings sections">
            {sections.map((s) => {
              const isActive = s.id === paneSection
              return (
                <button
                  key={s.id}
                  onClick={() => handleSelect(s.id)}
                  className={
                    'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ' +
                    (isActive
                      ? 'bg-surface-light text-text'
                      : 'text-text-muted hover:bg-surface-light/60 hover:text-text')
                  }
                >
                  <span aria-hidden="true">{s.icon}</span>
                  <span>{s.label}</span>
                </button>
              )
            })}
          </nav>

          <main className="min-w-0 flex-1">
            <SectionPane id={paneSection} />
          </main>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Profile section — small enough to live inline. Read-only for now; edit
// affordances (display name, password) ship with later tasks.
// ---------------------------------------------------------------------------

function ProfileSection() {
  const { user } = useAuthStore()
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-medium text-text">Profile</h2>
        <p className="mt-1 text-sm text-text-muted">Your account details.</p>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between py-2">
          <span className="text-sm">Display Name</span>
          <span className="text-sm text-text-muted">{user?.display_name}</span>
        </div>
        <div className="flex items-center justify-between py-2">
          <span className="text-sm">Email</span>
          <span className="text-sm text-text-muted">{user?.email}</span>
        </div>
        <div className="flex items-center justify-between py-2">
          <span className="text-sm">Role</span>
          <Badge variant="secondary">{user?.role}</Badge>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Lightweight placeholder for sections whose dedicated components have not
// been built yet. Keeps the navigation working end-to-end.
// ---------------------------------------------------------------------------

function PlaceholderSection({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-medium text-text">{title}</h2>
        <p className="mt-1 text-sm text-text-muted">{description}</p>
      </div>
      <div className="text-sm italic text-text-muted">Coming soon.</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Labs section — experimental features
// ---------------------------------------------------------------------------

function LabsSection() {
  const { settings, patch } = useSettingsStore()

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-medium text-text">
          Labs
          <span className="rounded bg-primary/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-primary">
            Experimental
          </span>
        </h2>
        <p className="mt-1 text-sm text-text-muted">
          Opt-in to experimental features currently in development. These may be unstable.
        </p>
      </div>

      <div className="space-y-4">
        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-border bg-background/40 p-4 transition-colors hover:bg-surface-light/40">
          <Switch
            className="mt-0.5"
            checked={!!settings.use_experimental_dashboard}
            onCheckedChange={(v) => patch({ use_experimental_dashboard: v })}
            aria-label="Dashboard V2 (SSE Command Center)"
          />
          <div>
            <div className="text-sm font-medium text-text">Dashboard V2 (SSE Command Center)</div>
            <div className="mt-1 text-xs leading-relaxed text-text-muted">
              Replaces the polling-based dashboard with a real-time Server-Sent Events stream.
            </div>
          </div>
        </label>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Navigation section — cosmetic self-hide (R5.4). Lets the user hide features
// they CAN access from their own nav. Purely cosmetic: the route stays
// reachable; only the button is hidden. Lists only permitted features.
// ---------------------------------------------------------------------------

function NavigationSection() {
  const access = useFeatures()
  const loadFeatureAccess = useAuthStore((s) => s.loadFeatureAccess)
  const [saving, setSaving] = useState<string | null>(null)

  const permitted = (access?.features ?? []).filter((f) => f.permitted)
  const hidden = new Set(access?.hidden_nav ?? [])

  const toggle = async (key: string, show: boolean) => {
    setSaving(key)
    const next = new Set(hidden)
    if (show) next.delete(key)
    else next.add(key)
    try {
      await api.put('/api/me/settings/nav', { hidden: [...next] })
      await loadFeatureAccess() // refresh so the nav updates immediately
    } catch (err: any) {
      toast.error(`Couldn't update navigation: ${err.response?.data?.detail || 'Unknown error'}`)
    } finally {
      setSaving(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-medium text-text">Navigation</h2>
        <p className="mt-1 text-sm text-text-muted">
          Hide features you don't use from your navigation. This is cosmetic — the pages stay
          accessible by direct link.
        </p>
      </div>
      <div className="space-y-3">
        {permitted.length === 0 && (
          <p className="text-sm text-text-muted">No optional features available.</p>
        )}
        {permitted.map((f) => (
          <label
            key={f.key}
            className="flex items-center justify-between gap-3 rounded-xl border border-border bg-background/40 p-3"
          >
            <span className="text-sm text-text">{f.label}</span>
            <Switch
              aria-label={`Show ${f.label} in navigation`}
              disabled={saving === f.key}
              checked={!hidden.has(f.key)}
              onCheckedChange={(v) => toggle(f.key, v)}
            />
          </label>
        ))}
      </div>
    </div>
  )
}
