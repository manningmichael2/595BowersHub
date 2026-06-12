export default function DashboardV2() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6 text-center space-y-4" style={{ backgroundColor: 'var(--color-background)' }}>
      <div className="w-16 h-16 rounded-2xl bg-indigo-500/20 flex items-center justify-center text-3xl">
        🚀
      </div>
      <div className="space-y-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--color-text)' }}>Dashboard V2</h2>
        <p className="text-sm max-w-md" style={{ color: 'var(--color-text-muted)' }}>
          The experimental real-time command center is now active. 
          The SSE data stream engine will be implemented in Task 2.
        </p>
      </div>
      <div className="text-[10px] uppercase tracking-widest font-bold px-2 py-1 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
        Experimental Mode
      </div>
    </div>
  )
}
