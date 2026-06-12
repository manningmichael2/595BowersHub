import { z } from 'zod'

export const WidgetTypeSchema = z
  .object({
    id: z.number(),
    widget_key: z.string(),
    display_name: z.string(),
    description: z.string(),
    category: z.string(),
    data_endpoint: z.string(),
    default_config: z.record(z.string(), z.any()),
  })
  .passthrough()

export const WidgetInstanceSchema = z
  .object({
    widget_key: z.string(),
    position: z.number(),
    config_overrides: z.record(z.string(), z.any()),
  })
  .passthrough()

export const PageLayoutSchema = z
  .object({
    page_key: z.string(),
    widgets: z.array(WidgetInstanceSchema),
  })
  .passthrough()

export const LayoutsResponseSchema = z
  .object({
    pages: z.array(PageLayoutSchema),
  })
  .passthrough()

export type WidgetType = z.infer<typeof WidgetTypeSchema>
export type WidgetInstance = z.infer<typeof WidgetInstanceSchema>
export type PageLayout = z.infer<typeof PageLayoutSchema>
