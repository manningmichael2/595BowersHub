import { z } from 'zod'

export const WorkspaceSchema = z
  .object({
    id: z.number(),
    name: z.string(),
    description: z.string().nullable(),
    icon: z.string().nullable(),
    color: z.string().nullable(),
    system_prompt: z.string(),
    default_model: z.string(),
    auto_capture: z.boolean(),
    user_count: z.number(),
    skill_count: z.number(),
  })
  .passthrough()

export type Workspace = z.infer<typeof WorkspaceSchema>
