/**
 * FinanceQA — conversational finance Q&A grounded in real data (R1.1/R1.2, R5.2).
 *
 * Ask a free-text question; the answer is narrated from figures computed in SQL
 * (never authored by the model). The "reveal query / figures" disclosure shows
 * the SQL and the raw rows behind every answer (verifiability, R1.2). Empty
 * (R1.6) and out-of-scope (R1.4) answers render with their own affordance so
 * they read as honest bounds, not failures.
 *
 * Tokenized Tailwind (R5.2) — sets the pattern for the Task 18 migration.
 */
import { useState } from 'react'
import { financeQa, type QaResponse } from '../services/financeQa'

const EXAMPLES = [
  'How much did I spend on groceries this year?',
  'What were my 5 biggest expenses last month?',
  'How much did I spend on dining vs last quarter?',
]

export default function FinanceQaPage() {
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<QaResponse | null>(null)
  const [revealed, setRevealed] = useState(false)

  async function ask(q: string) {
    const text = q.trim()
    if (!text || loading) return
    setLoading(true)
    setError(null)
    setResult(null)
    setRevealed(false)
    try {
      setResult(await financeQa.ask(text))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong answering that.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <h1 className="text-lg font-semibold text-text mb-1">Ask your finances</h1>
      <p className="text-sm text-text-muted mb-4">
        Free-text questions answered from your real data. Every number is computed in
        SQL and shown to you — nothing is made up.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          ask(question)
        }}
        className="flex gap-2"
      >
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. How much did I spend on groceries this year?"
          className="flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-text-muted focus:outline-none focus:border-primary"
          data-testid="qa-input"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-on-primary disabled:opacity-50"
        >
          {loading ? 'Asking…' : 'Ask'}
        </button>
      </form>

      {!result && !loading && !error && (
        <div className="mt-4 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setQuestion(ex)
                ask(ex)
              }}
              className="rounded-full border border-border px-3 py-1 text-xs text-text-muted hover:text-text hover:border-primary"
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div
          className="mt-5 rounded-md border border-border bg-surface px-4 py-3 text-sm text-text"
          data-testid="qa-error"
        >
          ⚠️ {error}
        </div>
      )}

      {result && (
        <section className="mt-5" data-testid="qa-result" data-scope={result.scope}>
          <div
            className="rounded-md border border-border bg-surface px-4 py-3 text-sm text-text whitespace-pre-wrap"
          >
            {result.scope === 'out_of_scope' && <span className="mr-1">🚫</span>}
            {result.scope === 'empty' && <span className="mr-1">🔍</span>}
            {result.answer}
          </div>

          {result.sql && (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => setRevealed((v) => !v)}
                className="text-xs text-text-muted hover:text-text underline"
                data-testid="qa-reveal"
              >
                {revealed ? 'Hide query & figures' : 'Reveal query & figures'}
              </button>
              {revealed && (
                <div className="mt-2 space-y-3">
                  <div>
                    <div className="text-xs font-medium text-text-muted mb-1">Query</div>
                    <pre className="overflow-x-auto rounded-md border border-border bg-surface-dark px-3 py-2 text-xs text-text">
                      {result.sql}
                    </pre>
                  </div>
                  {result.figures.length > 0 && (
                    <div>
                      <div className="text-xs font-medium text-text-muted mb-1">Figures</div>
                      <pre className="overflow-x-auto rounded-md border border-border bg-surface-dark px-3 py-2 text-xs text-text">
                        {JSON.stringify(result.figures, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
