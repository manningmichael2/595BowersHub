import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import SystemHealthWidget from '../SystemHealthWidget'

const base = {
  cpu_percent: 95.0,
  memory: { used_bytes: 8e9, total_bytes: 16e9, percent: 50 },
  disk: [{ mount: '/', used_bytes: 5e11, total_bytes: 1e12, percent: 50 }],
  uptime_seconds: 3600,
}

describe('SystemHealthWidget — Hardware HUD strain banner', () => {
  it('shows the strain banner naming the culprit when present', () => {
    render(<SystemHealthWidget data={{ ...base, strain: { cpu_percent: 95, culprit: 'Embedding worker' } }} widgetDef={{} as any} config={{}} />)
    expect(screen.getByText(/high load/i)).toBeTruthy()
    expect(screen.getByText('Embedding worker')).toBeTruthy()
  })

  it('shows a generic strain banner when no culprit is known', () => {
    render(<SystemHealthWidget data={{ ...base, strain: { cpu_percent: 95, culprit: null } }} widgetDef={{} as any} config={{}} />)
    expect(screen.getByText(/high load/i)).toBeTruthy()
  })

  it('renders no strain banner when the host is idle', () => {
    render(<SystemHealthWidget data={{ ...base, cpu_percent: 20 }} widgetDef={{} as any} config={{}} />)
    expect(screen.queryByText(/high load/i)).toBeNull()
  })
})
