import {
  ComboBox,
  Label as AriaLabel,
  Input as AriaInput,
  Button as AriaButton,
  Popover,
  ListBox,
  ListBoxItem,
  type Key,
} from 'react-aria-components'
import { ChevronDown } from 'lucide-react'
import { cn } from '../cn'

export interface ComboboxOption {
  id: Key
  label: string
}

export interface ComboboxProps {
  label?: string
  options: ComboboxOption[]
  selectedKey?: Key | null
  onSelectionChange?: (key: Key | null) => void
  placeholder?: string
  className?: string
  /** Allow free-text entries not in the list. */
  allowsCustomValue?: boolean
}

/**
 * Combobox — autocomplete/typeahead over React Aria's ComboBox (R2.5): filtered
 * listbox, keyboard nav, ARIA. For finance pickers (merchant, category, …).
 * Exposed through the finance UI boundary.
 */
export function Combobox({
  label,
  options,
  selectedKey,
  onSelectionChange,
  placeholder,
  className,
  allowsCustomValue,
}: ComboboxProps) {
  return (
    <ComboBox
      className={cn('flex flex-col gap-1', className)}
      selectedKey={selectedKey ?? null}
      onSelectionChange={(key) => onSelectionChange?.(key)}
      items={options}
      allowsCustomValue={allowsCustomValue}
    >
      {label && <AriaLabel className="text-sm font-medium text-text">{label}</AriaLabel>}
      <div className="relative flex items-center">
        <AriaInput
          placeholder={placeholder}
          className={cn(
            'h-10 w-full rounded-md border border-border bg-background px-3 pr-9 text-sm text-text',
            'placeholder:text-text-muted',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 focus-visible:ring-offset-background',
          )}
        />
        <AriaButton className="absolute right-2 text-text-muted" aria-label="Show options">
          <ChevronDown className="h-4 w-4" />
        </AriaButton>
      </div>
      <Popover className="z-dropdown w-[--trigger-width] overflow-auto rounded-md border border-border bg-surface p-1 text-text shadow-elevation-2">
        <ListBox className="outline-none">
          {(item: ComboboxOption) => (
            <ListBoxItem
              id={item.id}
              className="cursor-pointer rounded-sm px-2 py-1.5 text-sm text-text outline-none data-[focused]:bg-surface-light data-[selected]:font-medium"
            >
              {item.label}
            </ListBoxItem>
          )}
        </ListBox>
      </Popover>
    </ComboBox>
  )
}
