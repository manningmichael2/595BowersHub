import { z } from 'zod'

export const UserSchema = z
  .object({
    id: z.number(),
    email: z.string().email(),
    display_name: z.string(),
    role: z.string(),
    is_active: z.boolean(),
  })
  .passthrough()

export const AuthResponseSchema = z
  .object({
    access_token: z.string(),
    refresh_token: z.string(),
    user: UserSchema,
  })
  .passthrough()

export const RefreshResponseSchema = z
  .object({
    access_token: z.string(),
    refresh_token: z.string(),
  })
  .passthrough()

export type User = z.infer<typeof UserSchema>
