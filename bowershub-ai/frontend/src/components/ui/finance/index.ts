/**
 * Finance UI widgets (R2.5) — React Aria-backed primitives for the hard finance
 * inputs (date pickers, currency field, combobox, data grid).
 *
 * IMPORTANT: this barrel is **deliberately separate** from `components/ui` and
 * is NOT re-exported there. It must be imported only from the lazy-loaded
 * finance routes so `react-aria-components` stays in the finance chunk and out
 * of the main bundle (R2.5 / NFR Performance). Call-sites import the project's
 * widget names here — never `react-aria-components` directly.
 */
export { CurrencyInput, type CurrencyInputProps } from './CurrencyInput'
export { Combobox, type ComboboxProps, type ComboboxOption } from './Combobox'
export { DatePicker, type DatePickerProps, DateRangePicker, type DateRangePickerProps } from './DatePicker'
export { DataGrid, type DataGridProps, type DataGridColumn } from './DataGrid'
