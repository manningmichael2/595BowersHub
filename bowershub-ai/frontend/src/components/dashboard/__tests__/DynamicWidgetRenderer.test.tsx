import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DynamicWidgetRenderer, type WidgetSpec } from '../DynamicWidgetRenderer'

describe('DynamicWidgetRenderer', () => {
  it('renders a metric spec (value, label, delta)', () => {
    const spec: WidgetSpec = { type: 'metric', title: 'Spend', value: '$1,240', label: 'this month', delta: '+3%', delta_positive: false }
    render(<DynamicWidgetRenderer spec={spec} />)
    expect(screen.getByText('Spend')).toBeTruthy()
    expect(screen.getByText('$1,240')).toBeTruthy()
    expect(screen.getByText('this month')).toBeTruthy()
    expect(screen.getByText('+3%')).toBeTruthy()
  })

  it('renders a list spec', () => {
    render(<DynamicWidgetRenderer spec={{ type: 'list', title: 'Todo', items: ['Renew tags', 'Book dentist'] }} />)
    expect(screen.getByText('Todo')).toBeTruthy()
    expect(screen.getByText('Renew tags')).toBeTruthy()
    expect(screen.getByText('Book dentist')).toBeTruthy()
  })

  it('renders a bar spec with rows', () => {
    render(<DynamicWidgetRenderer spec={{ type: 'bar', title: 'By category', rows: [{ label: 'Food', value: 400 }, { label: 'Travel', value: 200 }] }} />)
    expect(screen.getByText('By category')).toBeTruthy()
    expect(screen.getByText('Food')).toBeTruthy()
    expect(screen.getByText('400')).toBeTruthy()
    expect(screen.getByText('Travel')).toBeTruthy()
  })

  it('shows a fallback for an unsupported type', () => {
    render(<DynamicWidgetRenderer spec={{ type: 'pie' } as unknown as WidgetSpec} />)
    expect(screen.getByText(/unsupported widget/i)).toBeTruthy()
  })
})
