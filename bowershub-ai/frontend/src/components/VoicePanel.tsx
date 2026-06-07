/**
 * VoicePanel — Settings → Voice section.
 *
 * Implements task 19.3:
 *   - Browser-capability badge: when `SpeechRecognition` is undefined we
 *     show "Voice unavailable in this browser" and hide the STT-only
 *     controls. TTS controls remain — `speechSynthesis` is independent
 *     and is supported in more browsers (R10.8).
 *   - TTS output enabled/disabled toggle.
 *   - Voice picker populated from `speechSynthesis.getVoices()` (the list
 *     loads asynchronously in some browsers — we listen for the
 *     `voiceschanged` event).
 *   - Speech rate slider clamped to the spec'd 0.5..2.0 range.
 *   - Auto-submit pause threshold (numeric, in ms).
 *   - Manual-send toggle (disables auto-submit on pause).
 *   - Every change calls `useSettingsStore.patch({voice: {...}})` so the
 *     server persists the preference and the optimistic merge keeps the
 *     UI snappy.
 *
 * Persistence keys match the design (R10.9):
 *   `voice.output_enabled`, `voice.voice_name`, `voice.speech_rate`,
 *   `voice.auto_submit_pause_ms`, `voice.manual_send`.
 *
 * _Requirements: R10.8, R10.9, R12.3
 */
import { useEffect, useMemo, useState } from 'react'
import { useSettingsStore, type VoiceSettings } from '../stores/settings'

// ---- Capability detection -------------------------------------------------

interface VoiceCapabilities {
  stt: boolean // SpeechRecognition (input)
  tts: boolean // speechSynthesis  (output)
}

function detectCapabilities(): VoiceCapabilities {
  if (typeof window === 'undefined') return { stt: false, tts: false }
  const w = window as any
  const stt = !!(w.SpeechRecognition || w.webkitSpeechRecognition)
  const tts = !!w.speechSynthesis && typeof w.SpeechSynthesisUtterance === 'function'
  return { stt, tts }
}

// ---- Defaults (mirrored from design.md §VoiceSettings) --------------------

const DEFAULTS: Required<VoiceSettings> = {
  output_enabled: true,
  voice_name: '',
  speech_rate: 1.0,
  auto_submit_pause_ms: 2000,
  manual_send: false,
}

// Speech rate is clamped to the spec'd range. SpeechSynthesisUtterance.rate
// technically accepts 0.1..10, but the design pins 0.5..2.0 for usability.
const RATE_MIN = 0.5
const RATE_MAX = 2.0
const RATE_STEP = 0.1

// Auto-submit pause threshold guardrails.
const PAUSE_MIN_MS = 500
const PAUSE_MAX_MS = 10_000

// ---- Component ------------------------------------------------------------

export default function VoicePanel() {
  const settings = useSettingsStore(s => s.settings)
  const patch = useSettingsStore(s => s.patch)

  const [caps, setCaps] = useState<VoiceCapabilities>(() => detectCapabilities())
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const [pendingKey, setPendingKey] = useState<keyof VoiceSettings | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // Effective values: merge persisted settings over defaults.
  const voice: Required<VoiceSettings> = useMemo(() => {
    const v = settings.voice || {}
    return {
      output_enabled: v.output_enabled ?? DEFAULTS.output_enabled,
      voice_name: v.voice_name ?? DEFAULTS.voice_name,
      speech_rate: typeof v.speech_rate === 'number' ? v.speech_rate : DEFAULTS.speech_rate,
      auto_submit_pause_ms:
        typeof v.auto_submit_pause_ms === 'number'
          ? v.auto_submit_pause_ms
          : DEFAULTS.auto_submit_pause_ms,
      manual_send: v.manual_send ?? DEFAULTS.manual_send,
    }
  }, [settings.voice])

  // ---- Re-check capabilities + load voice list --------------------------
  //
  // `speechSynthesis.getVoices()` returns [] synchronously in some browsers
  // (Chrome especially) — it populates only after the `voiceschanged` event
  // fires. Subscribe so the picker updates when the list arrives.

  useEffect(() => {
    const newCaps = detectCapabilities()
    setCaps(newCaps)
    if (!newCaps.tts) return

    const synth = window.speechSynthesis
    const refresh = () => {
      try {
        setVoices(synth.getVoices() || [])
      } catch {
        setVoices([])
      }
    }
    refresh()
    synth.addEventListener?.('voiceschanged', refresh)
    return () => {
      synth.removeEventListener?.('voiceschanged', refresh)
    }
  }, [])

  // ---- Local input state for numeric fields -----------------------------
  //
  // The pause threshold is edited as a free-form number; we commit on blur
  // so each keystroke isn't a network call.

  const [pauseInput, setPauseInput] = useState<string>(
    String(voice.auto_submit_pause_ms),
  )
  useEffect(() => {
    setPauseInput(String(voice.auto_submit_pause_ms))
  }, [voice.auto_submit_pause_ms])

  const [rateValue, setRateValue] = useState<number>(voice.speech_rate)
  useEffect(() => {
    setRateValue(voice.speech_rate)
  }, [voice.speech_rate])

  // ---- Patch helper ------------------------------------------------------

  const patchVoice = async (key: keyof VoiceSettings, value: any) => {
    setErrorMsg(null)
    setPendingKey(key)
    try {
      await patch({ voice: { [key]: value } })
    } catch (err: any) {
      setErrorMsg(
        err?.response?.data?.detail || 'Failed to save voice preference.',
      )
    } finally {
      setPendingKey(null)
    }
  }

  // ---- Handlers ----------------------------------------------------------

  const onToggleOutput = () => {
    patchVoice('output_enabled', !voice.output_enabled)
  }

  const onSelectVoice = (e: React.ChangeEvent<HTMLSelectElement>) => {
    patchVoice('voice_name', e.target.value)
  }

  const onRateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const n = parseFloat(e.target.value)
    if (!Number.isFinite(n)) return
    setRateValue(n)
  }

  const onRateCommit = () => {
    const clamped = Math.min(RATE_MAX, Math.max(RATE_MIN, rateValue))
    if (clamped === voice.speech_rate) return
    patchVoice('speech_rate', clamped)
  }

  const onPauseInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setPauseInput(e.target.value)
  }

  const onPauseCommit = () => {
    const n = parseInt(pauseInput, 10)
    if (!Number.isFinite(n)) {
      // Reset display to the persisted value.
      setPauseInput(String(voice.auto_submit_pause_ms))
      return
    }
    const clamped = Math.min(PAUSE_MAX_MS, Math.max(PAUSE_MIN_MS, n))
    setPauseInput(String(clamped))
    if (clamped === voice.auto_submit_pause_ms) return
    patchVoice('auto_submit_pause_ms', clamped)
  }

  const onToggleManualSend = () => {
    patchVoice('manual_send', !voice.manual_send)
  }

  const onPreviewVoice = () => {
    if (!caps.tts) return
    try {
      const synth = window.speechSynthesis
      synth.cancel()
      const u = new SpeechSynthesisUtterance(
        'This is a preview of the selected voice.',
      )
      u.rate = Math.min(RATE_MAX, Math.max(RATE_MIN, voice.speech_rate))
      const match = voices.find(v => v.name === voice.voice_name)
      if (match) u.voice = match
      synth.speak(u)
    } catch {
      // Non-fatal — some browsers throw on rapid speak/cancel.
    }
  }

  // ---- Render ------------------------------------------------------------

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-medium text-gray-100">Voice</h2>
        <p className="text-sm text-gray-400 mt-1">
          Voice mode preferences for speech-to-text input and text-to-speech
          replies. Audio never leaves your browser.
        </p>
      </div>

      {/* Browser-capability badge (R10.8) */}
      {!caps.stt && (
        <div className="rounded-lg border border-amber-700/40 bg-amber-900/20 px-3 py-2 text-sm text-amber-200">
          <span className="font-medium">Voice unavailable in this browser.</span>{' '}
          Speech-to-text input requires the Web Speech API (Chrome, Edge, or
          Safari). Your TTS output preferences below still apply when the app
          reads replies aloud.
        </div>
      )}

      {!caps.tts && (
        <div className="rounded-lg border border-amber-700/40 bg-amber-900/20 px-3 py-2 text-sm text-amber-200">
          Text-to-speech is not supported in this browser. Output controls are
          disabled.
        </div>
      )}

      {errorMsg && (
        <div className="rounded-lg border border-red-700/40 bg-red-900/20 px-3 py-2 text-sm text-red-300">
          {errorMsg}
        </div>
      )}

      {/* ---------------- TTS output ---------------- */}
      <section className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-gray-200">
              Read replies aloud
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              When on, assistant responses are spoken as they stream. Code
              blocks, tables, and images are skipped.
            </p>
          </div>
          <ToggleSwitch
            checked={voice.output_enabled}
            disabled={!caps.tts || pendingKey === 'output_enabled'}
            onChange={onToggleOutput}
            ariaLabel="Read replies aloud"
          />
        </div>
      </section>

      {/* ---------------- Voice picker ---------------- */}
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium text-gray-200">Voice</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Voices are provided by your browser/OS.
            {voices.length === 0 && caps.tts && ' Loading…'}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={voice.voice_name || ''}
            onChange={onSelectVoice}
            disabled={
              !caps.tts || !voice.output_enabled || pendingKey === 'voice_name'
            }
            className="flex-1 rounded-lg border border-gray-700 bg-gray-800/40 px-3 py-2 text-sm text-gray-100 focus:border-indigo-500 focus:outline-none disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <option value="">(Browser default)</option>
            {voices.map(v => (
              <option key={`${v.name}|${v.lang}`} value={v.name}>
                {v.name} — {v.lang}
                {v.default ? ' (default)' : ''}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={onPreviewVoice}
            disabled={!caps.tts || !voice.output_enabled}
            className="px-3 py-2 rounded-lg bg-gray-800 text-sm text-gray-200 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
            title="Preview the selected voice"
          >
            Preview
          </button>
        </div>
      </section>

      {/* ---------------- Speech rate ---------------- */}
      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-gray-200">Speech rate</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              How fast the assistant speaks (0.5× – 2.0×).
            </p>
          </div>
          <div className="text-sm font-medium text-gray-100 tabular-nums w-12 text-right">
            {rateValue.toFixed(1)}×
          </div>
        </div>
        <input
          type="range"
          min={RATE_MIN}
          max={RATE_MAX}
          step={RATE_STEP}
          value={rateValue}
          onChange={onRateChange}
          onMouseUp={onRateCommit}
          onTouchEnd={onRateCommit}
          onKeyUp={onRateCommit}
          disabled={!caps.tts || !voice.output_enabled}
          aria-label="Speech rate"
          className="w-full accent-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed"
        />
        <div className="flex justify-between text-[10px] uppercase tracking-wider text-gray-500">
          <span>Slow</span>
          <span>Normal</span>
          <span>Fast</span>
        </div>
      </section>

      {/* ---------------- STT controls (gated by capability) ---------------- */}
      {caps.stt && (
        <>
          <section className="space-y-3">
            <div>
              <h3 className="text-sm font-medium text-gray-200">
                Auto-submit pause
              </h3>
              <p className="text-xs text-gray-500 mt-0.5">
                Length of silence (in milliseconds) before your transcript is
                finalized and sent.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={PAUSE_MIN_MS}
                max={PAUSE_MAX_MS}
                step={100}
                value={pauseInput}
                onChange={onPauseInputChange}
                onBlur={onPauseCommit}
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    e.currentTarget.blur()
                  }
                }}
                disabled={voice.manual_send}
                className="w-32 rounded-lg border border-gray-700 bg-gray-800/40 px-3 py-2 text-sm text-gray-100 focus:border-indigo-500 focus:outline-none disabled:opacity-40 disabled:cursor-not-allowed"
                aria-label="Auto-submit pause threshold (ms)"
              />
              <span className="text-sm text-gray-400">ms</span>
              {pendingKey === 'auto_submit_pause_ms' && (
                <span className="text-xs text-gray-500">Saving…</span>
              )}
            </div>
          </section>

          <section className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-medium text-gray-200">
                  Manual send
                </h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  Don't auto-submit on pause. You'll press send yourself after
                  speaking.
                </p>
              </div>
              <ToggleSwitch
                checked={voice.manual_send}
                disabled={pendingKey === 'manual_send'}
                onChange={onToggleManualSend}
                ariaLabel="Manual send"
              />
            </div>
          </section>
        </>
      )}
    </div>
  )
}

// ---- Sub-components -------------------------------------------------------

function ToggleSwitch({
  checked,
  disabled,
  onChange,
  ariaLabel,
}: {
  checked: boolean
  disabled?: boolean
  onChange: () => void
  ariaLabel: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={onChange}
      disabled={disabled}
      className={
        'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ' +
        (checked ? 'bg-indigo-500' : 'bg-gray-700') +
        (disabled ? ' opacity-40 cursor-not-allowed' : ' cursor-pointer')
      }
    >
      <span
        className={
          'inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ' +
          (checked ? 'translate-x-5' : 'translate-x-0.5')
        }
      />
    </button>
  )
}
