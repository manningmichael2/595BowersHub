import { lazy, ComponentType } from 'react'

export interface WidgetProps {
  config: Record<string, any>
  widgetDef: {
    id: number
    widget_key: string
    display_name: string
    description: string
    category: string
    data_endpoint: string
    default_config: Record<string, any>
  }
  data: any
}

export interface WidgetDefinition {
  component: React.LazyExoticComponent<ComponentType<WidgetProps>>
}

const WIDGET_COMPONENTS: Record<string, WidgetDefinition> = {
  'weather':              { component: lazy(() => import('./widgets/WeatherWidget')) },
  'finance_summary':      { component: lazy(() => import('./widgets/FinanceSummaryWidget')) },
  'finance_balances':     { component: lazy(() => import('./widgets/BalancesWidget')) },
  'recent_transactions':  { component: lazy(() => import('./widgets/RecentTransactionsWidget')) },
  'budget_progress':      { component: lazy(() => import('./widgets/BudgetProgressWidget')) },
  'system_health':        { component: lazy(() => import('./widgets/SystemHealthWidget')) },
  'containers':           { component: lazy(() => import('./widgets/ContainersWidget')) },
  'inventory':            { component: lazy(() => import('./widgets/InventoryWidget')) },
  'knowledge_base':       { component: lazy(() => import('./widgets/KnowledgeBaseWidget')) },
  'recent_emails':        { component: lazy(() => import('./widgets/RecentEmailsWidget')) },
  'tailscale_devices':    { component: lazy(() => import('./widgets/TailscaleWidget')) },
  'api_spend':            { component: lazy(() => import('./widgets/ApiSpendWidget')) },
  'sports_scores':        { component: lazy(() => import('./widgets/SportsScoresWidget')) },
  'news':                 { component: lazy(() => import('./widgets/NewsWidget')) },
}

export function getWidgetComponent(key: string): WidgetDefinition | undefined {
  return WIDGET_COMPONENTS[key]
}

export { WIDGET_COMPONENTS }
