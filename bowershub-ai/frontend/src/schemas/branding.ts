import { z } from 'zod'

export const BrandingUrlsSchema = z
  .object({
    icon_192: z.string(),
    icon_512: z.string(),
    icon_maskable_512: z.string(),
  })
  .passthrough()

export const BrandingResponseSchema = z
  .object({
    version: z.string().nullable(),
    urls: BrandingUrlsSchema.nullable(),
    has_rollback: z.boolean().optional(),
  })
  .passthrough()

export type BrandingUrls = z.infer<typeof BrandingUrlsSchema>
