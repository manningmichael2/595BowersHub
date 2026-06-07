/**
 * useVoiceMode — privacy property test (no audio ever leaves the browser).
 *
 * Validates: Requirements R10.10
 *
 * Property 9: Voice mode never emits audio data over the network.
 *
 * Approach:
 *
 *   1. Stub `SpeechRecognition` and `SpeechSynthesis` so the hook is
 *      drivable in jsdom (which omits both APIs).
 *   2. Stub `navigator.mediaDevices.getUserMedia` so the permission
 *      prompt path does not throw. (getUserMedia returns a MediaStream
 *      object to the caller — that is *not* a network egress; the hook
 *      simply stops the tracks immediately.)
 *   3. Spy on every plausible network egress: `globalThis.fetch`,
 *      `XMLHttpRequest.prototype.send`, and `WebSocket.prototype.send`.
 *   4. Use `fast-check` to drive arbitrary sequences of voice events
 *      against a mounted `useVoiceMode` instance: start, partial STT
 *      results, final STT results, TTS streaming token append, stream
 *      end, manual stop, manual `speakText`.
 *   5. After each generated sequence, assert that NO recorded call
 *      carries audio data — checked across three signals:
 *         a. The body is not a `Blob` whose `type` matches `audio/*`.
 *         b. The body is not a raw `ArrayBuffer` / typed array.
 *         c. The body is not (or does not contain) a `MediaStream`.
 *         d. No request has a `Content-Type` header matching `audio/*`.
 *      and the strongest invariant: the hook never calls any of the
 *      three egress channels at all. The hook is a pure browser-side
 *      lifecycle — only finalized text is handed to consumers via
 *      callbacks (R10.10).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, cleanup } from '@testing-library/react'
import fc from 'fast-check'

import { useVoiceMode } from '../useVoiceMode'
import { useSettingsStore } from '../../stores/settings'
import { useConversationStore } from '../../stores/conversation'

// ---- API mock ------------------------------------------------------------
//
// `useSettingsStore` indirectly imports `services/api`, which in turn
// imports the auth store. We swap out the real client so no test path
// can sneak a `fetch` through it.

vi.mock('../../services/api', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

// ---- Speech API stubs ----------------------------------------------------

interface RecordedCall {
  channel: 'fetch' | 'xhr' | 'ws'
  body: any
  contentType: string | null
  url?: string
}

let recorded: RecordedCall[] = []

class StubSpeechRecognition {
  static lastInstance: StubSpeechRecognition | null = null

  continuous = false
  interimResults = false
  lang = ''
  onstart: ((evt: any) => void) | null = null
  onresult: ((evt: any) => void) | null = null
  onerror: ((evt: any) => void) | null = null
  onend: ((evt: any) => void) | null = null

  constructor() {
    StubSpeechRecognition.lastInstance = this
  }

  start() {
    if (this.onstart) this.onstart({})
  }
  stop() {
    if (this.onend) this.onend({})
  }
  abort() {
    if (this.onend) this.onend({})
  }
}

class StubSpeechSynthesisUtterance {
  text: string
  rate = 1
  voice: any = null
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(text: string) {
    this.text = text
  }
}

const stubSpeechSynthesis = {
  getVoices: () => [] as any[],
  speak: vi.fn((utter: StubSpeechSynthesisUtterance) => {
    // Simulate end-of-utterance synchronously so isSpeaking flips back
    // and the TTS pipeline keeps draining.
    queueMicrotask(() => {
      try {
        utter.onend?.()
      } catch {
        // ignore
      }
    })
  }),
  cancel: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
}

// ---- Egress spies --------------------------------------------------------

function extractContentType(init?: RequestInit | undefined): string | null {
  if (!init) return null
  const h = init.headers
  if (!h) return null
  if (typeof Headers !== 'undefined' && h instanceof Headers) {
    return h.get('content-type')
  }
  if (Array.isArray(h)) {
    const found = h.find(([k]) => String(k).toLowerCase() === 'content-type')
    return found ? String(found[1]) : null
  }
  if (typeof h === 'object') {
    for (const [k, v] of Object.entries(h as Record<string, string>)) {
      if (k.toLowerCase() === 'content-type') return String(v)
    }
  }
  return null
}

function installEgressSpies() {
  // fetch
  const fetchStub = vi.fn(
    async (input: any, init?: RequestInit): Promise<Response> => {
      const url =
        typeof input === 'string'
          ? input
          : input?.url
            ? String(input.url)
            : ''
      recorded.push({
        channel: 'fetch',
        body: init?.body ?? null,
        contentType: extractContentType(init),
        url,
      })
      return new Response('{}', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    },
  )
  ;(globalThis as any).fetch = fetchStub

  // XMLHttpRequest.send
  if (typeof XMLHttpRequest !== 'undefined') {
    const proto: any = (XMLHttpRequest as any).prototype
    if (!proto.__bh_send_orig) {
      proto.__bh_send_orig = proto.send
    }
    proto.send = function (body: any) {
      recorded.push({ channel: 'xhr', body: body ?? null, contentType: null })
      // Don't actually fire — the test never expects a response.
    }
  }

  // WebSocket.send
  if (typeof WebSocket !== 'undefined') {
    const proto: any = (WebSocket as any).prototype
    if (!proto.__bh_send_orig) {
      proto.__bh_send_orig = proto.send
    }
    proto.send = function (body: any) {
      recorded.push({ channel: 'ws', body: body ?? null, contentType: null })
    }
  }
}

function restoreEgress() {
  const xhrProto: any = (XMLHttpRequest as any)?.prototype
  if (xhrProto?.__bh_send_orig) {
    xhrProto.send = xhrProto.__bh_send_orig
    delete xhrProto.__bh_send_orig
  }
  const wsProto: any = (WebSocket as any)?.prototype
  if (wsProto?.__bh_send_orig) {
    wsProto.send = wsProto.__bh_send_orig
    delete wsProto.__bh_send_orig
  }
}

// ---- Audio sniffer -------------------------------------------------------

function bodyContainsAudio(body: any): boolean {
  if (body == null) return false

  // Blob with audio MIME
  if (typeof Blob !== 'undefined' && body instanceof Blob) {
    if (typeof body.type === 'string' && /^audio\//i.test(body.type)) {
      return true
    }
  }

  // Raw binary buffers — voice mode should never serialize audio bytes
  if (typeof ArrayBuffer !== 'undefined' && body instanceof ArrayBuffer) {
    return true
  }
  if (
    typeof ArrayBuffer !== 'undefined' &&
    typeof ArrayBuffer.isView === 'function' &&
    ArrayBuffer.isView(body)
  ) {
    return true
  }

  // MediaStream (would be a hard error — you can't actually serialize one,
  // but we guard against any path that tries to slip a reference through).
  if (typeof MediaStream !== 'undefined' && body instanceof MediaStream) {
    return true
  }

  // FormData parts can hide blobs
  if (typeof FormData !== 'undefined' && body instanceof FormData) {
    for (const [, value] of body.entries() as any) {
      if (bodyContainsAudio(value)) return true
    }
  }

  return false
}

// ---- Setup / teardown ---------------------------------------------------

beforeEach(() => {
  recorded = []

  // Reset stores to a clean baseline so the streaming-state subscription
  // starts from a known shape.
  useSettingsStore.setState({
    settings: { voice: { output_enabled: true, manual_send: false } },
    isLoading: false,
    isLoaded: true,
    error: null,
  } as any)

  useConversationStore.setState({
    isStreaming: false,
    streamingContent: '',
    streamingLayer: null,
    skillStatus: null,
  } as any)

  ;(window as any).SpeechRecognition = StubSpeechRecognition
  ;(window as any).webkitSpeechRecognition = StubSpeechRecognition
  ;(window as any).SpeechSynthesisUtterance = StubSpeechSynthesisUtterance
  ;(window as any).speechSynthesis = stubSpeechSynthesis
  ;(globalThis as any).SpeechSynthesisUtterance = StubSpeechSynthesisUtterance

  // getUserMedia stub — returns a MediaStream-like with no tracks. The
  // hook only calls `getTracks().forEach(t => t.stop())` and discards
  // the stream, so this is enough.
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [] as any[],
      }),
    },
  })

  installEgressSpies()
})

afterEach(() => {
  cleanup()
  restoreEgress()
  delete (window as any).SpeechRecognition
  delete (window as any).webkitSpeechRecognition
  delete (window as any).SpeechSynthesisUtterance
  delete (window as any).speechSynthesis
  vi.restoreAllMocks()
})

// ---- Event-builder for fast-check ---------------------------------------
//
// Each entry models one observable thing that can happen during a voice
// session. The arbitraries pick a sequence of these and the test driver
// applies them in order against a mounted hook.

type VoiceEvent =
  | { kind: 'partial'; text: string }
  | { kind: 'final'; text: string }
  | { kind: 'tts_chunk'; text: string }
  | { kind: 'tts_end' }
  | { kind: 'stop_speaking' }
  | { kind: 'speak_text'; text: string }
  | { kind: 'manual_stop' }

const eventArb: fc.Arbitrary<VoiceEvent> = fc.oneof(
  fc
    .string({ maxLength: 30 })
    .map((text) => ({ kind: 'partial' as const, text })),
  fc
    .string({ maxLength: 30 })
    .map((text) => ({ kind: 'final' as const, text })),
  fc
    .string({ maxLength: 60 })
    .map((text) => ({ kind: 'tts_chunk' as const, text })),
  fc.constant({ kind: 'tts_end' as const }),
  fc.constant({ kind: 'stop_speaking' as const }),
  fc
    .string({ maxLength: 60 })
    .map((text) => ({ kind: 'speak_text' as const, text })),
  fc.constant({ kind: 'manual_stop' as const }),
)

// ---- Tests --------------------------------------------------------------

describe('useVoiceMode — privacy property (R10.10)', () => {
  it('Property 9: arbitrary voice-event sequences never emit audio over fetch / XHR / WebSocket', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(eventArb, { minLength: 0, maxLength: 12 }),
        async (events) => {
          recorded = []

          // Reset streaming state per run.
          useConversationStore.setState({
            isStreaming: false,
            streamingContent: '',
          } as any)

          const submitted: string[] = []
          const { result, unmount } = renderHook(() =>
            useVoiceMode({ onAutoSubmit: (t) => submitted.push(t) }),
          )

          await act(async () => {
            await result.current.start()
          })

          const rec = StubSpeechRecognition.lastInstance
          // Streamed-content tracker so each tts_chunk extends the buffer
          // the way real Layer-3 streaming does.
          let streamingBuf = ''
          let isStreaming = false

          for (const ev of events) {
            await act(async () => {
              switch (ev.kind) {
                case 'partial': {
                  rec?.onresult?.({
                    resultIndex: 0,
                    results: [
                      Object.assign(
                        [{ transcript: ev.text } as any],
                        { isFinal: false, length: 1 },
                      ),
                    ],
                  })
                  break
                }
                case 'final': {
                  rec?.onresult?.({
                    resultIndex: 0,
                    results: [
                      Object.assign(
                        [{ transcript: ev.text } as any],
                        { isFinal: true, length: 1 },
                      ),
                    ],
                  })
                  break
                }
                case 'tts_chunk': {
                  if (!isStreaming) {
                    isStreaming = true
                    streamingBuf = ''
                    useConversationStore.setState({
                      isStreaming: true,
                      streamingContent: '',
                    } as any)
                  }
                  streamingBuf += ev.text
                  useConversationStore.setState({
                    isStreaming: true,
                    streamingContent: streamingBuf,
                  } as any)
                  break
                }
                case 'tts_end': {
                  if (isStreaming) {
                    useConversationStore.setState({
                      isStreaming: false,
                      streamingContent: streamingBuf,
                    } as any)
                    isStreaming = false
                    streamingBuf = ''
                  }
                  break
                }
                case 'stop_speaking': {
                  result.current.stopSpeaking()
                  break
                }
                case 'speak_text': {
                  result.current.speakText(ev.text)
                  break
                }
                case 'manual_stop': {
                  result.current.stop()
                  break
                }
              }
            })
            // Let any queued microtasks (utterance onend, store listeners) run.
            await new Promise((r) => setTimeout(r, 0))
          }

          unmount()

          // --- Invariant checks --------------------------------------------------

          for (const call of recorded) {
            if (bodyContainsAudio(call.body)) {
              throw new Error(
                `audio body sent via ${call.channel}: ${String(call.body)}`,
              )
            }
            if (
              typeof call.contentType === 'string' &&
              /^audio\//i.test(call.contentType)
            ) {
              throw new Error(
                `audio Content-Type "${call.contentType}" set on ${call.channel} call`,
              )
            }
          }

          // Strongest claim: the hook itself owns no network egress at
          // all. Audio handling stays inside the browser (R10.10). If
          // any call landed during a pure voice-event sequence, it is
          // already a leak — even an empty body would imply the hook
          // is contacting the network for some voice-related purpose.
          if (recorded.length !== 0) {
            const summary = recorded
              .map((c) => `${c.channel}:${c.url ?? ''}`)
              .join(', ')
            throw new Error(`unexpected egress during voice session: ${summary}`)
          }

          return true
        },
      ),
      { numRuns: 25 },
    )
  })

  it('Property 9 (sanity): the egress spy actually captures fetches', async () => {
    // Sanity check the harness — if the spies were broken, the property
    // above would pass vacuously. Drive a deliberate fetch and confirm
    // it is recorded.
    recorded = []
    await fetch('/sentinel', {
      method: 'POST',
      body: 'hello',
      headers: { 'content-type': 'text/plain' },
    })
    expect(recorded.length).toBe(1)
    expect(recorded[0].channel).toBe('fetch')
  })
})
