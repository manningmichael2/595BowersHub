import {
  DatePicker as AriaDatePicker,
  DateRangePicker as AriaDateRangePicker,
  Label as AriaLabel,
  Group,
  DateInput,
  DateSegment,
  Button as AriaButton,
  Popover,
  Dialog,
  Calendar,
  RangeCalendar,
  CalendarGrid,
  CalendarCell,
  Heading,
  type DatePickerProps as AriaDatePickerProps,
  type DateRangePickerProps as AriaDateRangePickerProps,
  type DateValue,
} from 'react-aria-components'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '../cn'

const fieldGroup =
  'flex h-10 w-full items-center gap-1 rounded-md border border-border bg-background px-3 text-sm text-text focus-within:ring-2 focus-within:ring-primary'
const segmentCls =
  'rounded px-0.5 tabular-nums outline-none focus:bg-primary focus:text-on-primary data-[placeholder]:text-text-muted'
const triggerBtn = 'ml-auto rounded p-0.5 text-text-muted hover:text-text'
const popoverCls = 'z-dropdown rounded-md border border-border bg-surface p-3 text-text shadow-elevation-2'
const cellCls =
  'flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-sm outline-none ' +
  'data-[hovered]:bg-surface-light data-[selected]:bg-primary data-[selected]:text-on-primary ' +
  'data-[disabled]:cursor-default data-[disabled]:opacity-40 data-[outside-month]:opacity-40 ' +
  'data-[focus-visible]:ring-2 data-[focus-visible]:ring-primary'

function CalendarChrome() {
  return (
    <header className="mb-2 flex items-center justify-between">
      <AriaButton slot="previous" className="rounded p-1 text-text-muted hover:text-text" aria-label="Previous">
        <ChevronLeft className="h-4 w-4" />
      </AriaButton>
      <Heading className="text-sm font-medium text-text" />
      <AriaButton slot="next" className="rounded p-1 text-text-muted hover:text-text" aria-label="Next">
        <ChevronRight className="h-4 w-4" />
      </AriaButton>
    </header>
  )
}

export interface DatePickerProps extends Omit<AriaDatePickerProps<DateValue>, 'children'> {
  label?: string
  className?: string
}

/**
 * DatePicker — single-date field + calendar over React Aria (R2.5): locale-aware
 * segments, keyboard entry, ARIA. Pass CalendarDate values from
 * `@internationalized/date`. Exposed through the finance UI boundary.
 */
export function DatePicker({ label, className, ...props }: DatePickerProps) {
  return (
    <AriaDatePicker className={cn('flex flex-col gap-1', className)} {...props}>
      {label && <AriaLabel className="text-sm font-medium text-text">{label}</AriaLabel>}
      <Group className={fieldGroup}>
        <DateInput className="flex flex-1">
          {(segment) => <DateSegment segment={segment} className={segmentCls} />}
        </DateInput>
        <AriaButton className={triggerBtn} aria-label="Open calendar">
          <CalendarDays className="h-4 w-4" />
        </AriaButton>
      </Group>
      <Popover className={popoverCls}>
        <Dialog className="outline-none">
          <Calendar>
            <CalendarChrome />
            <CalendarGrid>{(date) => <CalendarCell date={date} className={cellCls} />}</CalendarGrid>
          </Calendar>
        </Dialog>
      </Popover>
    </AriaDatePicker>
  )
}

export interface DateRangePickerProps
  extends Omit<AriaDateRangePickerProps<DateValue>, 'children'> {
  label?: string
  className?: string
}

/**
 * DateRangePicker — start/end range field + range calendar over React Aria
 * (R2.5). For finance period filters.
 */
export function DateRangePicker({ label, className, ...props }: DateRangePickerProps) {
  return (
    <AriaDateRangePicker className={cn('flex flex-col gap-1', className)} {...props}>
      {label && <AriaLabel className="text-sm font-medium text-text">{label}</AriaLabel>}
      <Group className={fieldGroup}>
        <DateInput slot="start" className="flex">
          {(segment) => <DateSegment segment={segment} className={segmentCls} />}
        </DateInput>
        <span aria-hidden className="px-1 text-text-muted">
          –
        </span>
        <DateInput slot="end" className="flex">
          {(segment) => <DateSegment segment={segment} className={segmentCls} />}
        </DateInput>
        <AriaButton className={triggerBtn} aria-label="Open calendar">
          <CalendarDays className="h-4 w-4" />
        </AriaButton>
      </Group>
      <Popover className={popoverCls}>
        <Dialog className="outline-none">
          <RangeCalendar>
            <CalendarChrome />
            <CalendarGrid>{(date) => <CalendarCell date={date} className={cellCls} />}</CalendarGrid>
          </RangeCalendar>
        </Dialog>
      </Popover>
    </AriaDateRangePicker>
  )
}
