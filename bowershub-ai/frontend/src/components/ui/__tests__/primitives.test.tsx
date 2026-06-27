/**
 * Component tests for the hand-rolled primitives (T4 / R2.3). Covers render,
 * variant class application, ref forwarding, and className override merging.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRef } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import {
  cn,
  Button,
  Card,
  CardTitle,
  Input,
  Textarea,
  Badge,
  Label,
  Separator,
} from '..'

afterEach(cleanup)

describe('cn', () => {
  it('merges conditional classes and dedupes conflicting Tailwind utilities', () => {
    expect(cn('px-4', false && 'hidden', 'px-2')).toBe('px-2')
    expect(cn('text-text', undefined, 'font-medium')).toBe('text-text font-medium')
  })
})

describe('Button', () => {
  it('renders children and defaults to type=button + primary variant', () => {
    render(<Button>Save</Button>)
    const btn = screen.getByRole('button', { name: 'Save' })
    expect(btn.getAttribute('type')).toBe('button')
    expect(btn.className).toContain('bg-primary')
  })

  it('applies variant and size classes', () => {
    render(
      <Button variant="danger" size="lg">
        Delete
      </Button>,
    )
    const btn = screen.getByRole('button', { name: 'Delete' })
    expect(btn.className).toContain('bg-danger')
    expect(btn.className).toContain('h-11')
  })

  it('forwards ref and fires onClick; respects disabled', () => {
    const ref = createRef<HTMLButtonElement>()
    const onClick = vi.fn()
    render(
      <Button ref={ref} onClick={onClick}>
        Go
      </Button>,
    )
    expect(ref.current).toBeInstanceOf(HTMLButtonElement)
    fireEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledOnce()

    cleanup()
    render(
      <Button onClick={onClick} disabled>
        Nope
      </Button>,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledOnce() // unchanged — disabled
  })

  it('lets a className override win over the variant base background (twMerge)', () => {
    render(<Button className="bg-success">Ok</Button>)
    const tokens = screen.getByRole('button').className.split(/\s+/)
    expect(tokens).toContain('bg-success')
    // The base `bg-primary` is replaced by twMerge. (The variant's
    // `hover:bg-primary/90` is a distinct utility and intentionally remains —
    // a full color override would also override hover.)
    expect(tokens).not.toContain('bg-primary')
  })
})

describe('Card', () => {
  it('renders a tokenized surface with its title', () => {
    render(
      <Card data-testid="card">
        <CardTitle>Net worth</CardTitle>
      </Card>,
    )
    expect(screen.getByTestId('card').className).toContain('bg-surface')
    expect(screen.getByText('Net worth')).toBeTruthy()
  })
})

describe('Input / Textarea', () => {
  it('Input forwards ref and is controllable', () => {
    const ref = createRef<HTMLInputElement>()
    const onChange = vi.fn()
    render(<Input ref={ref} value="hi" onChange={onChange} />)
    expect(ref.current).toBeInstanceOf(HTMLInputElement)
    fireEvent.change(screen.getByDisplayValue('hi'), { target: { value: 'bye' } })
    expect(onChange).toHaveBeenCalled()
  })

  it('Textarea renders with a min height', () => {
    render(<Textarea placeholder="notes" />)
    expect(screen.getByPlaceholderText('notes').className).toContain('min-h-')
  })
})

describe('Badge', () => {
  it('applies the success variant tokens', () => {
    render(<Badge variant="success">Active</Badge>)
    const cls = screen.getByText('Active').className
    expect(cls).toContain('bg-success')
    expect(cls).toContain('text-on-success')
  })
})

describe('Label / Separator', () => {
  it('Label associates via htmlFor', () => {
    render(<Label htmlFor="email">Email</Label>)
    expect(screen.getByText('Email').getAttribute('for')).toBe('email')
  })

  it('Separator exposes role + orientation', () => {
    render(<Separator orientation="vertical" />)
    const sep = screen.getByRole('separator')
    expect(sep.getAttribute('aria-orientation')).toBe('vertical')
    expect(sep.className).toContain('w-px')
  })
})
