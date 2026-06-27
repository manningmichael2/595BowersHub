/**
 * Accessibility baseline (T9 / R2.7). Runs axe-core over accessible
 * compositions of the primitives — a named checker, not a manual claim. The
 * color-contrast rule is disabled here because jsdom has no layout/computed
 * colors to measure; contrast is verified separately across all 10 presets in
 * themeContract.test.ts.
 *
 * Also exercises the matchMedia harness (R2.7): setMatchMedia drives the
 * desktop/mobile branch deterministically (the shell's useBreakpoint consumes
 * this in P3).
 */
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render } from '@testing-library/react'
import { axe } from 'vitest-axe'
import * as axeMatchers from 'vitest-axe/matchers'
import { setMatchMedia } from '../../../test/setup'
import {
  Button,
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Input,
  Label,
  Badge,
  Switch,
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
  EmptyState,
  ErrorState,
} from '..'

expect.extend(axeMatchers)

const axeOpts = { rules: { 'color-contrast': { enabled: false } } }

afterEach(cleanup)

describe('primitives a11y (axe)', () => {
  it('Button has no violations', async () => {
    const { container } = render(<Button>Save</Button>)
    expect(await axe(container, axeOpts)).toHaveNoViolations()
  })

  it('Card composition has no violations', async () => {
    const { container } = render(
      <Card>
        <CardHeader>
          <CardTitle>Title</CardTitle>
        </CardHeader>
        <CardContent>Body</CardContent>
      </Card>,
    )
    expect(await axe(container, axeOpts)).toHaveNoViolations()
  })

  it('labelled Input has no violations', async () => {
    const { container } = render(
      <div>
        <Label htmlFor="amt">Amount</Label>
        <Input id="amt" />
      </div>,
    )
    expect(await axe(container, axeOpts)).toHaveNoViolations()
  })

  it('Badge has no violations', async () => {
    const { container } = render(<Badge variant="success">Active</Badge>)
    expect(await axe(container, axeOpts)).toHaveNoViolations()
  })

  it('Switch (with label) has no violations', async () => {
    const { container } = render(<Switch aria-label="Notifications" />)
    expect(await axe(container, axeOpts)).toHaveNoViolations()
  })

  it('EmptyState / ErrorState have no violations', async () => {
    const { container } = render(
      <div>
        <EmptyState title="Nothing here" description="Add something." />
        <ErrorState message="Failed" onRetry={() => {}} />
      </div>,
    )
    expect(await axe(container, axeOpts)).toHaveNoViolations()
  })

  it('open Dialog has no violations', async () => {
    const { baseElement } = render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Confirm</DialogTitle>
          <DialogDescription>Are you sure?</DialogDescription>
        </DialogContent>
      </Dialog>,
    )
    expect(await axe(baseElement, axeOpts)).toHaveNoViolations()
  })
})

describe('matchMedia harness drives both responsive branches (R2.7)', () => {
  it('reports the desktop branch when set true and mobile when false', () => {
    setMatchMedia(true)
    expect(window.matchMedia('(min-width: 1024px)').matches).toBe(true)
    setMatchMedia(false)
    expect(window.matchMedia('(min-width: 1024px)').matches).toBe(false)
  })
})
