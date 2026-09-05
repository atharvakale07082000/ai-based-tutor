import { describe, expect, it } from 'vitest'
import { createSSEParser, SSE_DONE } from '../api'

/**
 * Golden SSE fixtures, replayed byte-split at EVERY offset.
 *
 * Frame splitting is pure string handling, so it is fully deterministic even though the
 * payloads come from a model. This is the test that would have caught the chat reader
 * dropping tokens: it split each network chunk on "\n" with no carry-over buffer, so any
 * frame straddling two reads was silently discarded.
 *
 * If you change the reader, this must stay green for every split point — not just the
 * convenient ones.
 */

/** One recorded chat turn: routing → steps → reasoning → tokens → done. */
const CHAT_TURN = [
  { type: 'routing', agent: 'doubt', reason: 'conceptual question' },
  { type: 'step', id: 'route', label: "Working out what you're really asking", status: 'done' },
  { type: 'step', id: 'work', label: 'Thinking it through', status: 'active' },
  { type: 'reasoning', content: 'Checking what they already know about closures.' },
  { type: 'step', id: 'work', label: 'Thinking it through', status: 'done' },
  { type: 'token', content: 'A closure is a function ' },
  { type: 'token', content: 'that captures its surrounding scope — ' },
  // Deliberately awkward payloads: unicode, quotes, braces, a newline inside a string.
  { type: 'token', content: 'e.g. `{ "x": 1 }` … and "quoted" text.\nStill the same frame.' },
  { type: 'done', steps: 1, total_ms: 4210 },
]

/** One recorded interview turn: evaluation, then the next question. */
const INTERVIEW_TURN = [
  { type: 'evaluation', score: 7.5, feedback: 'Solid, but you skipped the base case.' },
  { type: 'question', id: 'q2', text: 'How would you make that iterative?' },
  { type: 'done' },
]

function encode(events: object[]): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('') + `data: ${SSE_DONE}\n\n`
}

/** Drive the parser with a fixed chunk size, returning the parsed events. */
function drain(wire: string, chunkSize: number): object[] {
  const parser = createSSEParser()
  const out: object[] = []
  for (let i = 0; i < wire.length; i += chunkSize) {
    for (const payload of parser.push(wire.slice(i, i + chunkSize))) {
      if (payload === SSE_DONE) return out
      out.push(JSON.parse(payload))
    }
  }
  return out
}

describe('createSSEParser', () => {
  it('parses a chat turn delivered as one chunk', () => {
    expect(drain(encode(CHAT_TURN), Number.MAX_SAFE_INTEGER)).toEqual(CHAT_TURN)
  })

  it('parses a chat turn at every chunk size, including 1 byte at a time', () => {
    const wire = encode(CHAT_TURN)
    for (let size = 1; size <= wire.length; size += 1) {
      expect(drain(wire, size), `chunk size ${size}`).toEqual(CHAT_TURN)
    }
  })

  it('parses an interview turn at every chunk size', () => {
    const wire = encode(INTERVIEW_TURN)
    for (let size = 1; size <= wire.length; size += 1) {
      expect(drain(wire, size), `chunk size ${size}`).toEqual(INTERVIEW_TURN)
    }
  })

  it('splits a single frame across an arbitrary boundary without losing it', () => {
    const wire = encode([{ type: 'token', content: 'hello world' }])
    // Every possible two-way split of the wire.
    for (let at = 1; at < wire.length; at += 1) {
      const parser = createSSEParser()
      const payloads = [...parser.push(wire.slice(0, at)), ...parser.push(wire.slice(at))]
      const events = payloads.filter((p) => p !== SSE_DONE).map((p) => JSON.parse(p))
      expect(events, `split at ${at}`).toEqual([{ type: 'token', content: 'hello world' }])
    }
  })

  it('holds back a trailing partial frame instead of emitting it', () => {
    const parser = createSSEParser()
    expect(parser.push('data: {"type":"tok')).toEqual([])
    expect(parser.push('en","content":"hi"}\n\n')).toEqual(['{"type":"token","content":"hi"}'])
  })

  it('ignores comment and non-data lines', () => {
    const parser = createSSEParser()
    expect(parser.push(': keep-alive\n\nevent: ping\n\ndata: {"type":"done"}\n\n'))
      .toEqual(['{"type":"done"}'])
  })

  it('yields the DONE sentinel so callers can stop reading', () => {
    const parser = createSSEParser()
    expect(parser.push(`data: ${SSE_DONE}\n\n`)).toEqual([SSE_DONE])
  })

  it('keeps two frames arriving in one chunk in order', () => {
    const parser = createSSEParser()
    expect(parser.push('data: {"n":1}\n\ndata: {"n":2}\n\n')).toEqual(['{"n":1}', '{"n":2}'])
  })
})
