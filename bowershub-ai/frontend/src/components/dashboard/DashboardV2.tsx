import { useDashboardStream } from '../../hooks/useDashboardStream'

export default function DashboardV2() {
  const { isConnected, widgetData } = useDashboardStream()

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6 text-center space-y-4" style={{ backgroundColor: 'var(--color-background)' }}>
      <div className="w-16 h-16 rounded-2xl flex items-center justify-center text-3xl" style={{ backgroundColor: isConnected ? 'var(--color-success)' : 'var(--color-danger)' }}>
        {isConnected ? '🟢' : '🔴'}
      </div>
      <div className="space-y-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--color-text)' }}>Dashboard V2</h2>
        <p className="text-sm max-w-md" style={{ color: 'var(--color-text-muted)' }}>
          SSE Stream Status: {isConnected ? 'Connected' : 'Disconnected'}<br/>
          Keys in Cache: {Object.keys(widgetData).length}
        </p>
      </div>
      <div className="text-[10px] uppercase tracking-widest font-bold px-2 py-1 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
        Experimental Mode
      </div>
    </div>
  )
}
