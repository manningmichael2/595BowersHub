/**
 * AdminConsolePage — Admin console with sidebar navigation.
 *
 * Each section is a nested child route under `/admin/*` so deep links
 * survive page reloads. Non-admin users hitting any admin route are
 * redirected to `/` (R12.5).
 */
import { useEffect } from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation, Link } from 'react-router-dom'
import { useAuthStore } from '../stores/auth'

// Sections
import UsersSection from './admin/UsersSection'
import WorkspacesSection from './admin/WorkspacesSection'
import SkillsSection from './admin/SkillsSection'
import SlashCommandsSection from './admin/SlashCommandsSection'
import PatternsSection from './admin/PatternsSection'
import ApiRegistrySection from './admin/ApiRegistrySection'
import ModelsSection from './admin/ModelsSection'
import CostSection from './admin/CostSection'
import AuditSection from './admin/AuditSection'
import SemanticMemorySection from './admin/SemanticMemorySection'
import ThemeManagementSection from './admin/ThemeManagementSection'
import IconManagementSection from './admin/IconManagementSection'

// ---- Sidebar configuration -----------------------------------------------

interface SectionDef {
  slug: string
  label: string
  icon: string
}

const SECTIONS: SectionDef[] = [
  { slug: 'users', label: 'Users', icon: '👥' },
  { slug: 'workspaces', label: 'Workspaces', icon: '🏠' },
  { slug: 'skills', label: 'Skills', icon: '🔧' },
  { slug: 'commands', label: 'Slash Commands', icon: '⌨️' },
  { slug: 'patterns', label: 'Routing Patterns', icon: '🔀' },
  { slug: 'api-registry', label: 'API Registry', icon: '🔌' },
  { slug: 'models', label: 'Models', icon: '🤖' },
  { slug: 'cost', label: 'Cost', icon: '💰' },
  { slug: 'semantic-memory', label: 'Semantic Memory', icon: '🧠' },
  { slug: 'audit', label: 'Audit Log', icon: '📋' },
  { slug: 'themes', label: 'Theme Management', icon: '🎨' },
  { slug: 'icon', label: 'Icon Management', icon: '🖼️' },
]

// ---- Page shell ----------------------------------------------------------

export default function AdminConsolePage() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()

  // Admin gate (R12.5)
  useEffect(() => {
    if (user && user.role !== 'admin') {
      navigate('/', { replace: true })
    }
  }, [user, navigate])

  if (!user || user.role !== 'admin') {
    return null
  }

  const path = location.pathname
  const activeSlug =
    SECTIONS.find(s => path === `/admin/${s.slug}` || path.startsWith(`/admin/${s.slug}/`))?.slug
    ?? 'users'

  return (
    <div className="h-screen flex flex-col bg-[#1a1a2e] text-gray-200">
      {/* Header */}
      <div className="border-b border-gray-800 px-4 py-3 flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-400"
        >
          ← Back
        </button>
        <h1 className="text-lg font-medium">Admin Console</h1>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Sidebar */}
        <nav className="w-56 border-r border-gray-800 p-2 overflow-y-auto shrink-0 hidden md:block">
          <ul className="space-y-1">
            {SECTIONS.map(section => {
              const isActive = section.slug === activeSlug
              return (
                <li key={section.slug}>
                  <Link
                    to={`/admin/${section.slug}`}
                    className={
                      'flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ' +
                      (isActive
                        ? 'bg-indigo-500/10 text-indigo-200 border-l-2 border-indigo-500'
                        : 'text-gray-400 hover:bg-gray-800/60 hover:text-gray-200 border-l-2 border-transparent')
                    }
                  >
                    <span>{section.icon}</span>
                    <span>{section.label}</span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>

        {/* Mobile: horizontal tab strip */}
        <div className="md:hidden border-b border-gray-800 px-2 overflow-x-auto shrink-0 absolute top-12 left-0 right-0 z-10 bg-[#1a1a2e]">
          <div className="flex gap-1 min-w-max py-1">
            {SECTIONS.map(section => {
              const isActive = section.slug === activeSlug
              return (
                <Link
                  key={section.slug}
                  to={`/admin/${section.slug}`}
                  className={
                    'px-3 py-1.5 text-xs rounded-lg whitespace-nowrap ' +
                    (isActive
                      ? 'bg-indigo-500/15 text-indigo-200'
                      : 'text-gray-400 hover:bg-gray-800/60')
                  }
                >
                  <span className="mr-1">{section.icon}</span>
                  {section.label}
                </Link>
              )
            })}
          </div>
        </div>

        {/* Content */}
        <main className="flex-1 overflow-y-auto md:pt-0 pt-9">
          <div className="max-w-6xl mx-auto p-4 md:p-6">
            <Routes>
              <Route index element={<Navigate to="users" replace />} />
              <Route path="users" element={<UsersSection />} />
              <Route path="workspaces" element={<WorkspacesSection />} />
              <Route path="skills" element={<SkillsSection />} />
              <Route path="commands" element={<SlashCommandsSection />} />
              <Route path="patterns" element={<PatternsSection />} />
              <Route path="api-registry" element={<ApiRegistrySection />} />
              <Route path="models" element={<ModelsSection />} />
              <Route path="cost" element={<CostSection />} />
              <Route path="semantic-memory" element={<SemanticMemorySection />} />
              <Route path="audit" element={<AuditSection />} />
              <Route path="themes" element={<ThemeManagementSection />} />
              <Route path="icon" element={<IconManagementSection />} />
              <Route path="*" element={<Navigate to="users" replace />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  )
}
