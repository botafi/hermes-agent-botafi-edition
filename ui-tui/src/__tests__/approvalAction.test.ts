import { describe, expect, it } from 'vitest'

import { approvalAction, approvalOptions } from '../components/prompts.js'

describe('approvalAction — pure key dispatch for ApprovalPrompt', () => {
  it('maps Esc to deny — parity with global Ctrl+C cancellation', () => {
    expect(approvalAction('', { escape: true }, 0)).toEqual({ kind: 'choose', choice: 'deny' })
    expect(approvalAction('', { escape: true }, 2)).toEqual({ kind: 'choose', choice: 'deny' })
  })

  it('maps number keys 1..4 to once/session/always/deny in registration order', () => {
    expect(approvalAction('1', {}, 0)).toEqual({ kind: 'choose', choice: 'once' })
    expect(approvalAction('2', {}, 0)).toEqual({ kind: 'choose', choice: 'session' })
    expect(approvalAction('3', {}, 0)).toEqual({ kind: 'choose', choice: 'always' })
    expect(approvalAction('4', {}, 0)).toEqual({ kind: 'choose', choice: 'deny' })
  })

  it('ignores out-of-range numbers', () => {
    expect(approvalAction('0', {}, 1)).toEqual({ kind: 'noop' })
    expect(approvalAction('5', {}, 1)).toEqual({ kind: 'noop' })
    expect(approvalAction('9', {}, 1)).toEqual({ kind: 'noop' })
  })

  it('confirms the current selection on Enter', () => {
    expect(approvalAction('', { return: true }, 0)).toEqual({ kind: 'choose', choice: 'once' })
    expect(approvalAction('', { return: true }, 3)).toEqual({ kind: 'choose', choice: 'deny' })
  })

  it('moves selection up/down within bounds', () => {
    expect(approvalAction('', { upArrow: true }, 2)).toEqual({ kind: 'move', delta: -1 })
    expect(approvalAction('', { downArrow: true }, 1)).toEqual({ kind: 'move', delta: 1 })
  })

  it('clamps selection movement at the edges', () => {
    expect(approvalAction('', { upArrow: true }, 0)).toEqual({ kind: 'noop' })
    expect(approvalAction('', { downArrow: true }, 3)).toEqual({ kind: 'noop' })
  })

  it('Esc beats numeric/return — denying is always the first interpretation', () => {
    // If a terminal somehow delivers Esc + a digit in the same event, deny
    // wins.  Documents the precedence so a future refactor doesn't flip it.
    expect(approvalAction('1', { escape: true }, 0)).toEqual({ kind: 'choose', choice: 'deny' })
    expect(approvalAction('', { escape: true, return: true }, 1)).toEqual({ kind: 'choose', choice: 'deny' })
  })

  it('returns noop for unrelated keystrokes (printable letters etc.)', () => {
    expect(approvalAction('a', {}, 0)).toEqual({ kind: 'noop' })
    expect(approvalAction(' ', {}, 0)).toEqual({ kind: 'noop' })
  })

  it('omits always for file local-backend approval options', () => {
    const opts = approvalOptions({ approval_kind: 'file_backend_local' })

    expect(opts).toEqual(['once', 'session', 'session_all', 'deny'])
    expect(approvalAction('1', {}, 0, opts)).toEqual({ kind: 'choose', choice: 'once' })
    expect(approvalAction('2', {}, 0, opts)).toEqual({ kind: 'choose', choice: 'session' })
    expect(approvalAction('3', {}, 0, opts)).toEqual({ kind: 'choose', choice: 'session_all' })
    expect(approvalAction('4', {}, 0, opts)).toEqual({ kind: 'choose', choice: 'deny' })
    expect(approvalAction('5', {}, 0, opts)).toEqual({ kind: 'noop' })
  })

  it('omits always for legacy file pattern-key approval payloads', () => {
    expect(approvalOptions({ pattern_key: 'file:read_file' })).toEqual(['once', 'session', 'session_all', 'deny'])
  })
})
