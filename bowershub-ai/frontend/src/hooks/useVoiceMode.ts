/**
 * useVoiceMode — voice input + voice output lifecycle.
 *
 * Owns the in-browser Web Speech API integration for BowersHub AI's Voice Mode
 * (R10.1–R10.10):
 *
 *   - STT input via `webkitSpeechRecognition` / `SpeechRecognition`.
 *     Streams `onresult` partials into the consumer via `transcript` and the
 *     `onTranscriptUpdate` callback. On a configurable pause (default 2s),
 *     auto-submits unless `voice.manual_send` is on (R10.3).
 *
 *   - TTS output via `SpeechSynthesisUtterance`. Subscribes to the assistant
 *     message stream from `useConversationStore` and chunks the prose into
 *     utterances per sentence boundary. Code blocks, tables, and inline
 *     images are stripped via `tts_strip` from `lib/tts_strip` so the
 *     listener hears prose only (R10.5).
 *
 *   - `stop()` halts STT (without auto-submitting whatever was partial,
 *     R10.6) and cancels any in-flight TTS.
 *
 *   - `stopSpeaking()` cancels TTS only (R10.7).
 *
 *   - Capability detection: hidden if neither STT nor TTS is available
 *     in this browser. Each capability is checked separately so a
 *     desktop Firefox user (TTS yes, STT no) still gets read-aloud
 *     output (R10.8).
 *
 *   - All audio stays in the browser. Nothing in this hook posts audio
 *     bytes anywhere — we hand off only finalized text to consumers
 *     (R10.10). Privacy property is exercised by §27.5.
 *
 * Voice preferences (`voice.voice_name`, `voice.speech_rate`,
 * `voice.auto_submit_pause_ms`, `voice.manual_send`,
 * `voice.output_enabled`) come from `useSettingsStore` (R10.9).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSettingsStore, type VoiceSettings } from '../stores/settings'
import { useConversationStore } from '../stores/conversation'
import { tts_strip } from '../lib/tts_strip'

// ---- Types ---------------------------------------------------------------

export interface UseVoiceModeOptions {
  /**
   * Called when the recognizer auto-finalizes after a pause and
   * `voice.manual_send` is off (R10.3). Receives the final transcript text.
   * The consumer is responsible for submitting the message.
   */
  onAutoSubmit?: (text: string) => void

  /**
   * Called on every recognition result (interim or final) so the consumer
   * can mirror the partial transcript into the chat input (R10.2).
   * `isFinal` is true when the engine marked the result final.
   */
  onTranscriptUpdate?: (text: string, isFinal: boolean) => void
}

export interface UseVoiceModeReturn {
  /** True while STT is actively listening. */
  isListening: boolean
  /** True while at least one TTS utterance is queued or speaking. */
  isSpeaking: boolean
  /** Latest accumulated transcript (finalized + interim). */
  transcript: string
  /** True iff at least one of STT or TTS is supported in this browser. */
  isSupported: boolean
  /** Capability detail — useful for hiding only the parts that are unavailable. */
  capabilities: { stt: boolean; tts: boolean }

  start: () => Promise<void>
  stop: () => void
  stopSpeaking: () => void
  /** Speak arbitrary text immediately (used for previews / test buttons). */
  speakText: (text: string) => void
}

// Voice preference defaults — kept in sync with `VoicePanel.tsx` DEFAULTS.
const DEFAULT_VOICE: Required<VoiceSettings> = {
  output_enabled: true,
  voice_name: '',
  speech_rate: 1.0,
  auto_submit_pause_ms: 2000,
  manual_send: false,
}

// ---- Capability detection ------------------------------------------------

interface SpeechCapabilities {
  stt: boolean
  tts: boolean
}

function detectCapabilities(): SpeechCapabilities {
  if (typeof window === 'undefined') return { stt: false, tts: false }
  const w = window as any
  const stt = !!(w.SpeechRecognition || w.webkitSpeechRecognition)
  const tts = !!w.speechSynthesis && typeof w.SpeechSynthesisUtterance === 'function'
  return { stt, tts }
}

function getSpeechRecognitionCtor(): any | null {
  if (typeof window === 'undefined') return null
  const w = window as any
  return w.SpeechRecognition || w.webkitSpeechRecognition || null
}

// ---- Sentence chunker ----------------------------------------------------
//
// Streaming TTS sounds best when we wait for a sentence boundary and speak
// one sentence at a time. We accumulate streamed text into a buffer and
// flush each "complete" sentence as we see it. Trailing partial text stays
// in the buffer until `flushBuffer(true)` is called (final flush after the
// stream completes).

const SENTENCE_END_RE = /([.!?])(\s+|$)/

function pullSentence(buf: string): { sentence: string | null; rest: string } {
  const m = buf.match(SENTENCE_END_RE)
  if (!m) return { sentence: null, rest: buf }
  const endIdx = (m.index ?? 0) + m[0].length
  const sentence = buf.slice(0, endIdx).trim()
  const rest = buf.slice(endIdx)
  return { sentence: sentence.length > 0 ? sentence : null, rest }
}

// ---- Hook ----------------------------------------------------------------

export function useVoiceMode(options: UseVoiceModeOptions = {}): UseVoiceModeReturn {
  const capsRef = useRef<SpeechCapabilities>(detectCapabilities())
  const [isListening, setIsListening] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [transcript, setTranscript] = useState('')

  const recognitionRef = useRef<any | null>(null)
  const finalTranscriptRef = useRef('')
  const interimTranscriptRef = useRef('')
  const pauseTimerRef = useRef<number | null>(null)
  const stoppedManuallyRef = useRef(false)

  // TTS state — kept in refs so changes don't re-render the hook unnecessarily.
  const ttsBufferRef = useRef('')
  const ttsLastConsumedLenRef = useRef(0)
  const ttsActiveUtterancesRef = useRef(0)
  const ttsStreamingRef = useRef(false)

  // Pull voice settings + the auto-submit callback through refs so the
  // recognition handlers always see the current values (recognition lives
  // outside React's render cycle).
  const voiceSettings = useSettingsStore(s => s.settings.voice)
  const voiceRef = useRef<Required<VoiceSettings>>({
    ...DEFAULT_VOICE,
    ...(voiceSettings || {}),
  })
  useEffect(() => {
    voiceRef.current = {
      ...DEFAULT_VOICE,
      ...(voiceSettings || {}),
    }
  }, [voiceSettings])

  const onAutoSubmitRef = useRef(options.onAutoSubmit)
  const onTranscriptUpdateRef = useRef(options.onTranscriptUpdate)
  useEffect(() => {
    onAutoSubmitRef.current = options.onAutoSubmit
  }, [options.onAutoSubmit])
  useEffect(() => {
    onTranscriptUpdateRef.current = options.onTranscriptUpdate
  }, [options.onTranscriptUpdate])

  // ---- TTS helpers -------------------------------------------------------

  const speakChunk = useCallback((chunk: string) => {
    const caps = capsRef.current
    if (!caps.tts) return
    const text = chunk.trim()
    if (!text) return

    try {
      const synth = window.speechSynthesis
      const utter = new SpeechSynthesisUtterance(text)

      const v = voiceRef.current
      utter.rate = Math.max(0.5, Math.min(2.0, v.speech_rate))

      // Match by name when set; fall back to default voice otherwise.
      const wantedName = (v.voice_name || '').trim()
      if (wantedName) {
        const match = synth.getVoices().find(vc => vc.name === wantedName)
        if (match) utter.voice = match
      }

      ttsActiveUtterancesRef.current += 1
      setIsSpeaking(true)

      const handleDone = () => {
        ttsActiveUtterancesRef.current = Math.max(
          0,
          ttsActiveUtterancesRef.current - 1,
        )
        if (ttsActiveUtterancesRef.current === 0) {
          setIsSpeaking(false)
        }
      }
      utter.onend = handleDone
      utter.onerror = handleDone

      synth.speak(utter)
    } catch {
      // Ignore — TTS is best-effort. A single utterance failure shouldn't
      // crash voice mode.
    }
  }, [])

  /**
   * Pull as many complete sentences as possible out of the buffer and speak
   * them. If `final` is true, also speaks any remaining partial text.
   */
  const flushBuffer = useCallback(
    (final: boolean) => {
      let buf = ttsBufferRef.current
      while (true) {
        const { sentence, rest } = pullSentence(buf)
        if (!sentence) break
        speakChunk(sentence)
        buf = rest
      }
      if (final) {
        const tail = buf.trim()
        if (tail) speakChunk(tail)
        buf = ''
      }
      ttsBufferRef.current = buf
    },
    [speakChunk],
  )

  /**
   * Subscribe to the conversation store's streaming events. Each tick of new
   * content gets stripped via `tts_strip` then chunked into sentences.
   *
   * We track `ttsLastConsumedLenRef` so we only speak the *delta* of the
   * stripped stream — handing the full stripped buffer to the chunker each
   * tick would re-speak everything.
   */
  useEffect(() => {
    if (!capsRef.current.tts) return
    // We always subscribe — the listener checks `output_enabled` per tick so
    // toggling the preference takes effect mid-session without remounting.

    const unsubscribe = useConversationStore.subscribe((state, prev) => {
      const v = voiceRef.current
      if (!v.output_enabled) return

      // Stream just started → reset buffers.
      if (state.isStreaming && !prev.isStreaming) {
        ttsBufferRef.current = ''
        ttsLastConsumedLenRef.current = 0
        ttsStreamingRef.current = true
        return
      }

      // Stream just ended → flush whatever is left and stop tracking.
      if (!state.isStreaming && prev.isStreaming) {
        // Consume any final delta first.
        if (state.streamingContent.length > ttsLastConsumedLenRef.current) {
          const stripped = tts_strip(state.streamingContent)
          const delta = stripped.slice(ttsLastConsumedLenRef.current)
          ttsBufferRef.current += delta
          ttsLastConsumedLenRef.current = stripped.length
        }
        flushBuffer(true)
        ttsStreamingRef.current = false
        return
      }

      // Mid-stream token append.
      if (
        state.isStreaming &&
        state.streamingContent !== prev.streamingContent
      ) {
        const stripped = tts_strip(state.streamingContent)
        if (stripped.length > ttsLastConsumedLenRef.current) {
          const delta = stripped.slice(ttsLastConsumedLenRef.current)
          ttsBufferRef.current += delta
          ttsLastConsumedLenRef.current = stripped.length
          flushBuffer(false)
        }
      }
    })

    return unsubscribe
  }, [flushBuffer])

  // ---- STT helpers -------------------------------------------------------

  const clearPauseTimer = useCallback(() => {
    if (pauseTimerRef.current !== null) {
      window.clearTimeout(pauseTimerRef.current)
      pauseTimerRef.current = null
    }
  }, [])

  const cleanupRecognition = useCallback(() => {
    clearPauseTimer()
    const rec = recognitionRef.current
    if (rec) {
      try {
        rec.onresult = null
        rec.onend = null
        rec.onerror = null
        rec.onstart = null
      } catch {
        // ignore
      }
    }
    recognitionRef.current = null
    interimTranscriptRef.current = ''
    setIsListening(false)
  }, [clearPauseTimer])

  const finalize = useCallback(
    (autoSubmit: boolean) => {
      clearPauseTimer()
      const finalText = (
        finalTranscriptRef.current +
        interimTranscriptRef.current
      ).trim()

      if (autoSubmit && finalText.length > 0) {
        onAutoSubmitRef.current?.(finalText)
      }

      // Reset for next session.
      finalTranscriptRef.current = ''
      interimTranscriptRef.current = ''
    },
    [clearPauseTimer],
  )

  const stop = useCallback(() => {
    stoppedManuallyRef.current = true
    clearPauseTimer()
    const rec = recognitionRef.current
    if (rec) {
      try {
        rec.stop()
      } catch {
        // ignore
      }
    }
    // Manual stop never auto-submits (R10.6) — the consumer keeps whatever
    // was transcribed in the input field.
    finalize(false)
    cleanupRecognition()
    // Also cancel any in-flight TTS so "stop" feels like a hard stop.
    try {
      if (capsRef.current.tts) window.speechSynthesis.cancel()
    } catch {
      // ignore
    }
    ttsActiveUtterancesRef.current = 0
    ttsBufferRef.current = ''
    setIsSpeaking(false)
  }, [cleanupRecognition, clearPauseTimer, finalize])

  const start = useCallback(async () => {
    const Ctor = getSpeechRecognitionCtor()
    if (!Ctor) return
    if (recognitionRef.current) return // already listening

    // Request mic permission via getUserMedia. Some browsers will prompt
    // here, others rely on the SpeechRecognition API to prompt on its own.
    // We deliberately discard the MediaStream — SpeechRecognition manages
    // its own audio pipeline; the only purpose of this call is the prompt.
    try {
      if (
        typeof navigator !== 'undefined' &&
        navigator.mediaDevices &&
        typeof navigator.mediaDevices.getUserMedia === 'function'
      ) {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: true,
        })
        // Immediately release the tracks. SpeechRecognition will request
        // its own audio stream behind the scenes.
        for (const track of stream.getTracks()) {
          try {
            track.stop()
          } catch {
            // ignore
          }
        }
      }
    } catch {
      // Permission denied or no mediaDevices — let SpeechRecognition try
      // anyway. Some browsers (Safari) prompt at the SpeechRecognition layer.
    }

    let rec: any
    try {
      rec = new Ctor()
    } catch {
      return
    }
    rec.continuous = true
    rec.interimResults = true
    try {
      rec.lang =
        (typeof navigator !== 'undefined' && navigator.language) || 'en-US'
    } catch {
      // ignore
    }

    finalTranscriptRef.current = ''
    interimTranscriptRef.current = ''
    setTranscript('')
    stoppedManuallyRef.current = false

    rec.onstart = () => {
      setIsListening(true)
    }

    rec.onresult = (evt: any) => {
      let newlyFinal = ''
      let interim = ''
      const results = evt.results
      // Process every result from `resultIndex` onward — earlier results
      // are already accounted for in `finalTranscriptRef`.
      for (let i = evt.resultIndex; i < results.length; i++) {
        const r = results[i]
        const text = r[0]?.transcript ?? ''
        if (r.isFinal) {
          newlyFinal += text
        } else {
          interim += text
        }
      }

      if (newlyFinal) {
        finalTranscriptRef.current += newlyFinal
      }
      interimTranscriptRef.current = interim

      const merged = (finalTranscriptRef.current + interim).trim()
      setTranscript(merged)
      onTranscriptUpdateRef.current?.(merged, !!newlyFinal && !interim)

      // Reset the pause timer on each recognition tick.
      clearPauseTimer()
      const v = voiceRef.current
      if (!v.manual_send) {
        const ms = Math.max(500, v.auto_submit_pause_ms || 2000)
        pauseTimerRef.current = window.setTimeout(() => {
          pauseTimerRef.current = null
          // Stop the recognizer; the auto-submit happens in `onend` so we
          // capture any final results emitted as the engine winds down.
          try {
            rec.stop()
          } catch {
            // ignore
          }
          // Mark this stop as an auto-submit request; `onend` will look at
          // this flag and call onAutoSubmit if appropriate.
          stoppedManuallyRef.current = false
        }, ms)
      }
    }

    rec.onerror = () => {
      // Don't auto-submit on errors (no-mic, no-permission, network).
      stoppedManuallyRef.current = true
    }

    rec.onend = () => {
      const wasManualStop = stoppedManuallyRef.current
      // Auto-submit if recognition ended on its own (pause-timer triggered
      // a stop, or engine timed out) AND manual_send is off.
      const v = voiceRef.current
      const shouldAutoSubmit = !wasManualStop && !v.manual_send
      finalize(shouldAutoSubmit)
      cleanupRecognition()
    }

    recognitionRef.current = rec
    try {
      rec.start()
    } catch {
      // Some browsers throw if start() is called while already started.
      cleanupRecognition()
    }
  }, [cleanupRecognition, clearPauseTimer, finalize])

  const stopSpeaking = useCallback(() => {
    if (!capsRef.current.tts) return
    try {
      window.speechSynthesis.cancel()
    } catch {
      // ignore
    }
    ttsActiveUtterancesRef.current = 0
    ttsBufferRef.current = ''
    ttsLastConsumedLenRef.current = 0
    setIsSpeaking(false)
  }, [])

  const speakText = useCallback(
    (text: string) => {
      if (!capsRef.current.tts) return
      if (!voiceRef.current.output_enabled) return
      const stripped = tts_strip(text)
      if (!stripped.trim()) return
      // Speak as a single utterance — caller is in charge of chunking.
      speakChunk(stripped)
    },
    [speakChunk],
  )

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.stop()
      } catch {
        // ignore
      }
      cleanupRecognition()
      try {
        if (capsRef.current.tts) window.speechSynthesis.cancel()
      } catch {
        // ignore
      }
    }
  }, [cleanupRecognition])

  const caps = capsRef.current
  return {
    isListening,
    isSpeaking,
    transcript,
    isSupported: caps.stt || caps.tts,
    capabilities: caps,
    start,
    stop,
    stopSpeaking,
    speakText,
  }
}
