/**
 * Zod schemas for conversation/message wire types.
 *
 * These schemas are the single source of truth: the TS types are derived via
 * `z.infer`, so the compile-time shape and the runtime validation can never
 * drift apart. `.passthrough()` keeps unknown fields (a new backend column
 * won't be silently dropped). Consumers import the types from
 * `stores/conversation`, which re-exports them.
 */

import { z } from 'zod'

export const MessageSchema = z
  .object({
    id: z.number(),
    conversation_id: z.number(),
    role: z.enum(['user', 'assistant', 'system', 'tool_call', 'tool_result']),
    content: z.string(),
    attachments: z.array(z.any()),
    model_used: z.string().nullable(),
    routing_layer: z.string().nullable(),
    input_tokens: z.number().nullable(),
    output_tokens: z.number().nullable(),
    cost_usd: z.number().nullable(),
    metadata: z.record(z.string(), z.any()),
    created_at: z.string(),
  })
  .passthrough()

export const ConversationSchema = z
  .object({
    id: z.number(),
    workspace_id: z.number(),
    title: z.string().nullable(),
    parent_id: z.number().nullable(),
    is_archived: z.boolean(),
    created_at: z.string(),
    updated_at: z.string(),
    message_count: z.number(),
  })
  .passthrough()

export type Message = z.infer<typeof MessageSchema>
export type Conversation = z.infer<typeof ConversationSchema>
