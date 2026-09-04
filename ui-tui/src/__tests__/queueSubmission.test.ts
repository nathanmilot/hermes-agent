import { describe, expect, it } from 'vitest'

import type { ComposerToken } from '../app/interfaces.js'
import { busyQueueItem, expandPasteTokens, prepareSlashSubmission, queueItemFromSlash } from '../app/useSubmission.js'
import { imageToken } from '../domain/attachments.js'

describe('/queue collapsed paste submission', () => {
  it('keeps the collapsed argument for display and the full multiline payload for execution', () => {
    const display = '[[ first.. [3 lines] .. last ]]'

    expect(queueItemFromSlash(`/queue ${display}`, '/queue first\nmiddle\nlast')).toEqual({
      display,
      text: 'first\nmiddle\nlast'
    })
  })

  it('supports the /q alias and rejects an empty queue command', () => {
    expect(queueItemFromSlash('/q [[ payload ]]', '/q complete payload')).toEqual({
      display: '[[ payload ]]',
      text: 'complete payload'
    })
    expect(queueItemFromSlash('/queue', '/queue')).toBeUndefined()
  })

  it('expands paste tokens without consuming image tokens', () => {
    const paste: ComposerToken = { kind: 'paste', label: '[[ paste [2 lines] ]]', text: 'one\ntwo' }
    const image: ComposerToken = { kind: 'image', index: 1, label: imageToken(1), path: '/tmp/image.png' }

    expect(expandPasteTokens([paste, image])(`${paste.label} and ${image.label}`)).toBe(`one\ntwo and ${image.label}`)
  })
})

describe('prepareSlashSubmission', () => {
  const label = '[[ Done — verified.. [412 lines] .. already on it. ]]'
  const text = 'Done — verified through the real resolver\nline two\nline three'
  const tokens: ComposerToken[] = [{ kind: 'paste', label, text }]

  // The reported bug: `/pr-triage <paste>` dispatched the LABEL, so the skill
  // received "[412 lines]" as its argument and the agent reported the paste as
  // truncated. The command has to carry the full text; only the transcript
  // stays collapsed.
  it('dispatches the full paste while the transcript keeps the collapsed label', () => {
    expect(prepareSlashSubmission(`/pr-triage ${label}`, tokens)).toEqual({
      command: `/pr-triage ${text}`,
      display: `/pr-triage ${label}`
    })
  })

  it('leaves image tokens as labels — the gateway already holds the file', () => {
    const image: ComposerToken = { kind: 'image', index: 1, label: imageToken(1), path: '/tmp/shot.png' }

    expect(prepareSlashSubmission(`/pr-triage ${image.label}`, [image]).command).toBe(`/pr-triage ${image.label}`)
  })

  it('is a no-op on a token-free command', () => {
    expect(prepareSlashSubmission('/model opus', [])).toEqual({ command: '/model opus', display: '/model opus' })
  })
})

describe('busyQueueItem (submit-while-busy paste expansion)', () => {
  // Regression for the label-leak the user hit repeatedly: a collapsed paste
  // submitted while the turn is busy went through handleBusyInput's
  // send(item.text) AFTER clearIn() had wiped tokensRef, so the expansion was
  // a no-op and the agent received the literal [[ … ]] label and never saw
  // the pasted content.
  it('expands the payload to full paste content while keeping the label for display', () => {
    const label = '[[ See attached - -.. [94 lines] .. rivacy@convey.it. Thank You. ]]'
    const text = 'See attached -\n'.repeat(93) + 'Privacy@convey.it. Thank You.'
    const tokens: ComposerToken[] = [{ kind: 'paste', label, text }]

    const item = busyQueueItem(`here it is: ${label}`, tokens)

    expect(item.display).toBe(`here it is: ${label}`)
    expect(item.text).toBe(`here it is: ${text}`)
  })

  it('is a no-op for token-free text (recall round-trip)', () => {
    expect(busyQueueItem('plain old text', [])).toEqual({ display: 'plain old text', text: 'plain old text' })
  })

  it('leaves an unmatched label intact rather than dropping the user text', () => {
    const label = '[[ orphan [2 lines] ]]'
    expect(busyQueueItem(label, []).text).toBe(label)
  })
})
