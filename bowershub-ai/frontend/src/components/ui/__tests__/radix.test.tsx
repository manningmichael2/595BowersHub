/**
 * Tests for the Radix-backed chrome (T5 / R2.2): the confirm() → AlertDialog
 * rewire (the behavior-bearing change) plus representative Dialog/Switch/Tabs
 * interactions to prove the wrappers wire up open/close, keyboard, and state.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import ConfirmDialog from '../../ConfirmDialog'
import { confirm, useConfirmStore } from '../../../stores/confirm'
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
  Switch,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from '..'

afterEach(() => {
  cleanup()
  useConfirmStore.setState({ request: null })
})

describe('confirm() via AlertDialog', () => {
  it('shows the message and resolves true on the confirm action', async () => {
    render(<ConfirmDialog />)
    let result!: Promise<boolean>
    act(() => {
      result = confirm({ message: 'Delete this?', confirmLabel: 'Delete' })
    })
    const btn = await screen.findByRole('button', { name: 'Delete' })
    expect(screen.getByText('Delete this?')).toBeTruthy()
    fireEvent.click(btn)
    await expect(result).resolves.toBe(true)
  })

  it('resolves false on cancel', async () => {
    render(<ConfirmDialog />)
    let result!: Promise<boolean>
    act(() => {
      result = confirm({ message: 'Sure?', cancelLabel: 'Nope' })
    })
    const cancel = await screen.findByRole('button', { name: 'Nope' })
    fireEvent.click(cancel)
    await expect(result).resolves.toBe(false)
  })

  it('resolves false on Escape', async () => {
    render(<ConfirmDialog />)
    let result!: Promise<boolean>
    act(() => {
      result = confirm({ message: 'Sure?' })
    })
    await screen.findByText('Sure?')
    fireEvent.keyDown(document.activeElement || document.body, { key: 'Escape' })
    await expect(result).resolves.toBe(false)
  })
})

describe('Dialog', () => {
  it('opens from the trigger and shows its content', async () => {
    render(
      <Dialog>
        <DialogTrigger>Open</DialogTrigger>
        <DialogContent>
          <DialogTitle>Hello</DialogTitle>
        </DialogContent>
      </Dialog>,
    )
    expect(screen.queryByText('Hello')).toBeNull()
    fireEvent.click(screen.getByText('Open'))
    expect(await screen.findByText('Hello')).toBeTruthy()
  })
})

describe('Switch', () => {
  it('toggles checked state', () => {
    function Harness() {
      const [on, setOn] = useState(false)
      return <Switch checked={on} onCheckedChange={setOn} aria-label="wifi" />
    }
    render(<Harness />)
    const sw = screen.getByRole('switch')
    expect(sw.getAttribute('aria-checked')).toBe('false')
    fireEvent.click(sw)
    expect(sw.getAttribute('aria-checked')).toBe('true')
  })
})

describe('Tabs', () => {
  // Radix's own tab-switching (pointer/keyboard) is exercised upstream and
  // doesn't drive in jsdom; here we verify the wrapper's structure: roles, the
  // controlled default selection, and that only the active panel renders.
  it('renders tabs with roles and shows the controlled default panel', () => {
    render(
      <Tabs value="b">
        <TabsList>
          <TabsTrigger value="a">A</TabsTrigger>
          <TabsTrigger value="b">B</TabsTrigger>
        </TabsList>
        <TabsContent value="a">Panel A</TabsContent>
        <TabsContent value="b">Panel B</TabsContent>
      </Tabs>,
    )
    expect(screen.getAllByRole('tab')).toHaveLength(2)
    const active = screen.getByRole('tab', { name: 'B' })
    expect(active.getAttribute('data-state')).toBe('active')
    expect(screen.getByText('Panel B')).toBeTruthy()
    expect(screen.queryByText('Panel A')).toBeNull()
  })
})
