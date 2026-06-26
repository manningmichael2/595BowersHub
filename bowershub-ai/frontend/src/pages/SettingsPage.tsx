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
import { useAuthStore } from '../stores/auth'
import { useSettingsStore } from '../stores/settings'
import { useFeatures } from '../hooks/useFeatures'
import { api } from '../services/api'
import { toast } from '../stores/toast'
import AppearancePanel from '../components/AppearancePanel'
import VoicePanel from '../components/VoicePanel'

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

export default function SettingsPage() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const [activeSection, setActiveSection] = useState<SectionId>('profile')

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

  return (
    // The app body is locked to `overflow: hidden` (see index.css) so the
    // chat shell can use position:fixed inset:0 without surprising
    // scrolling on mobile. This page therefore has to manage its own
    // scroll: a fixed-height shell whose body pane is `overflow-y-auto`.
    <div
      className="bh-app-shell bg-surface text-gray-200 flex flex-col"
      style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0 }}
    >
      {/* Header */}
      <div className="border-b border-gray-800 px-4 py-3 flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-400"
          aria-label="Back"
        >
          ← Back
        </button>
        <h1 className="text-lg font-medium">Settings</h1>
      </div>

      {/* Body: nav (left on desktop, top on mobile) + active section pane.
          `flex-1 min-h-0 overflow-y-auto` lets the inner content scroll
          while the header stays pinned. */}
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col md:flex-row max-w-5xl w-full mx-auto md:gap-6 p-4 md:p-6">
        {/* Section nav */}
        <nav
          className="md:w-56 md:shrink-0 flex md:flex-col gap-1 overflow-x-auto md:overflow-visible mb-4 md:mb-0"
          aria-label="Settings sections"
        >
          {sections.map(s => {
            const isActive = s.id === activeSection
            return (
              <button
                key={s.id}
                onClick={() => handleSelect(s.id)}
                className={
                  'shrink-0 md:w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-sm transition-colors ' +
                  (isActive
                    ? 'bg-gray-800 text-gray-100'
                    : 'text-gray-400 hover:bg-gray-800/60 hover:text-gray-200')
                }
              >
                <span aria-hidden="true">{s.icon}</span>
                <span>{s.label}</span>
              </button>
            )
          })}
        </nav>

        {/* Active section pane */}
        <main className="flex-1 min-w-0">
          {activeSection === 'profile' && <ProfileSection />}
          {activeSection === 'appearance' && <AppearancePanel />}
          {activeSection === 'navigation' && <NavigationSection />}
          {activeSection === 'voice' && <VoicePanel />}
          {activeSection === 'notifications' && (
            <PlaceholderSection
              title="Notifications"
              description="Daily briefing and budget alert preferences. Coming soon."
            />
          )}
          {activeSection === 'briefing' && (
            <PlaceholderSection
              title="Briefing"
              description="Morning card workspace and briefing schedule. Coming soon."
            />
          )}
          {activeSection === 'context-capture' && (
            <PlaceholderSection
              title="Context Capture"
              description="Background context-capture preferences. Coming soon."
            />
          )}
          {activeSection === 'labs' && <LabsSection />}
        </main>
      </div>
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
        <h2 className="text-lg font-medium text-gray-100">Profile</h2>
        <p className="text-sm text-gray-400 mt-1">
          Your account details.
        </p>
      </div>

      <div className="space-y-3">
        <div className="flex justify-between items-center py-2">
          <span className="text-sm">Display Name</span>
          <span className="text-sm text-gray-400">{user?.display_name}</span>
        </div>
        <div className="flex justify-between items-center py-2">
          <span className="text-sm">Email</span>
          <span className="text-sm text-gray-400">{user?.email}</span>
        </div>
        <div className="flex justify-between items-center py-2">
          <span className="text-sm">Role</span>
          <span className="text-xs px-2 py-0.5 rounded bg-indigo-900/30 text-indigo-300">
            {user?.role}
          </span>
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
        <h2 className="text-lg font-medium text-gray-100">{title}</h2>
        <p className="text-sm text-gray-400 mt-1">{description}</p>
      </div>
      <div className="text-sm text-gray-500 italic">Coming soon.</div>
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
        <h2 className="text-lg font-medium text-gray-100 flex items-center gap-2">
          Labs <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-500/20 text-indigo-400 uppercase tracking-wider">Experimental</span>
        </h2>
        <p className="text-sm text-gray-400 mt-1">
          Opt-in to experimental features currently in development. These may be unstable.
        </p>
      </div>

      <div className="space-y-4">
        <label className="flex items-start gap-3 p-4 rounded-xl border border-gray-800 bg-gray-900/30 cursor-pointer hover:bg-gray-800/40 transition-colors">
          <div className="flex items-center h-5">
            <input
              type="checkbox"
              className="w-4 h-4 rounded border-gray-700 bg-gray-800 text-indigo-500 focus:ring-indigo-500/50"
              checked={!!settings.use_experimental_dashboard}
              onChange={(e) => patch({ use_experimental_dashboard: e.target.checked })}
            />
          </div>
          <div>
            <div className="text-sm font-medium text-gray-200">Dashboard V2 (SSE Command Center)</div>
            <div className="text-xs text-gray-500 mt-1 leading-relaxed">
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
  const loadFeatureAccess = useAuthStore(s => s.loadFeatureAccess)
  const [saving, setSaving] = useState<string | null>(null)

  const permitted = (access?.features ?? []).filter(f => f.permitted)
  const hidden = new Set(access?.hidden_nav ?? [])

  const toggle = async (key: string, show: boolean) => {
    setSaving(key)
    const next = new Set(hidden)
    if (show) next.delete(key); else next.add(key)
    try {
      await api.put('/api/me/settings/nav', { hidden: [...next] })
      await loadFeatureAccess()   // refresh so the nav updates immediately
    } catch (err: any) {
      toast.error(`Couldn't update navigation: ${err.response?.data?.detail || 'Unknown error'}`)
    } finally {
      setSaving(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-medium text-gray-100">Navigation</h2>
        <p className="text-sm text-gray-400 mt-1">
          Hide features you don't use from your navigation. This is cosmetic — the
          pages stay accessible by direct link.
        </p>
      </div>
      <div className="space-y-3">
        {permitted.length === 0 && (
          <p className="text-sm text-gray-500">No optional features available.</p>
        )}
        {permitted.map(f => (
          <label
            key={f.key}
            className="flex items-center justify-between gap-3 p-3 rounded-xl border border-gray-800 bg-gray-900/30"
          >
            <span className="text-sm text-gray-200">{f.label}</span>
            <input
              type="checkbox"
              aria-label={`Show ${f.label} in navigation`}
              disabled={saving === f.key}
              checked={!hidden.has(f.key)}
              onChange={e => toggle(f.key, e.target.checked)}
              className="w-4 h-4 rounded border-gray-700 bg-gray-800 text-indigo-500"
            />
          </label>
        ))}
      </div>
    </div>
  )
}
