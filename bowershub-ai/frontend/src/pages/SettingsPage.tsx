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
import AppearancePanel from '../components/AppearancePanel'
import VoicePanel from '../components/VoicePanel'

type SectionId =
  | 'profile'
  | 'appearance'
  | 'voice'
  | 'notifications'
  | 'briefing'
  | 'context-capture'
  | 'scheduled-prompts'
  | 'admin'

interface SectionDef {
  id: SectionId
  label: string
  icon: string
}

const BASE_SECTIONS: SectionDef[] = [
  { id: 'profile', label: 'Profile', icon: '👤' },
  { id: 'appearance', label: 'Appearance', icon: '🎨' },
  { id: 'voice', label: 'Voice', icon: '🎙️' },
  { id: 'notifications', label: 'Notifications', icon: '🔔' },
  { id: 'briefing', label: 'Briefing', icon: '🌅' },
  { id: 'context-capture', label: 'Context Capture', icon: '📥' },
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
