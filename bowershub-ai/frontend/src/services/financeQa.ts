/**
 * Typed client for the Finance Q&A API (routers/finance_qa.py).
 *
 * Strict TS types mirror the Pydantic response 1:1 — no `any` at the boundary.
 * All calls go through the shared `api` client (auth injection + 401 refresh).
 */
import { api } from './api'

export type QaScope = 'in_scope' | 'empty' | 'out_of_scope'

export interface QaResponse {
  /** Narrated prose (figures quoted verbatim) or a code-authored empty/out-of-scope message. */
  answer: string
  /** The generated SQL behind the answer, for the "reveal query" disclosure. */
  sql: string | null
  /** The computed rows the answer was narrated from, for the "reveal figures" disclosure. */
  figures: Record<string, unknown>[]
  scope: QaScope
}

export const financeQa = {
  async ask(question: string): Promise<QaResponse> {
    const { data } = await api.post('/api/finance/qa', { question })
    return data as QaResponse
  },
}
