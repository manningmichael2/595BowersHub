/**
 * Single source of truth for primary navigation.
 *
 * Previously each surface (TopNav, BottomTabBar, the Sidebar footer row)
 * declared its own emoji-based list, which drifted out of sync and rendered
 * inconsistently across platforms. These items now drive every nav surface
 * with real (themeable, baseline-aligned) Lucide icons.
 *
 * `feature` ties an item to a registry feature key — shown iff server-permitted
 * AND not self-hidden (see lib/featureNav). Items without `feature` always show.
 */
import {
  LayoutDashboard,
  MessageSquare,
  Wallet,
  Database,
  Settings,
  Workflow,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  path: string
  label: string
  Icon: LucideIcon
  feature?: string
}

export const NAV_ITEMS: NavItem[] = [
  { path: '/dashboard', label: 'Dashboard', Icon: LayoutDashboard },
  { path: '/chat', label: 'Chat', Icon: MessageSquare },
  { path: '/finance', label: 'Finance', Icon: Wallet, feature: 'finance' },
  { path: '/db', label: 'Database', Icon: Database, feature: 'database' },
  { path: '/settings', label: 'Settings', Icon: Settings },
]

/**
 * Embedded external tools. These route to the in-app iframe shell
 * (ToolFramePage at /tools/:id) rather than raw host:port URLs, so they stay
 * inside the PWA and carry no hardcoded IPs.
 */
export const TOOL_ITEMS: NavItem[] = [
  { path: '/tools/n8n', label: 'n8n', Icon: Workflow },
]
