import { PassThrough } from 'stream'

import { renderSync } from '@hermes/ink'
import React from 'react'
import { describe, expect, it } from 'vitest'

import { ToolTrail } from '../components/thinking.js'
import { buildToolTrailLine, buildVerboseToolTrailLine, stripAnsi } from '../lib/text.js'
import { DEFAULT_THEME } from '../theme.js'

const flushEffects = async () => {
  // Passive effects + the re-render they trigger need a few macrotask
  // turns (React's scheduler uses MessageChannel) before the next frame
  // paints — setTimeout(0)-class waits, not setImmediate (which can land
  // in the wrong phase and observe the pre-effect frame).
  for (let i = 0; i < 10; i++) {
    await new Promise(resolve => setTimeout(resolve, 5))
  }
}

const mountTrail = (reasoningActive: boolean, sections?: Record<string, string>) => {
  const stdout = new PassThrough()
  const stdin = new PassThrough()
  const stderr = new PassThrough()
  let output = ''

  Object.assign(stdout, { columns: 60, isTTY: false, rows: 20 })
  Object.assign(stdin, { isTTY: false })
  Object.assign(stderr, { isTTY: false })
  stdout.on('data', chunk => {
    output += chunk.toString()
  })

  const trail = (active: boolean) => (
    <ToolTrail
      reasoning="Live reasoning text."
      reasoningActive={active}
      sections={sections ?? { thinking: 'collapsed' }}
      t={DEFAULT_THEME}
    />
  )

  const instance = renderSync(trail(reasoningActive), {
    patchConsole: false,
    stderr: stderr as NodeJS.WriteStream,
    stdin: stdin as NodeJS.ReadStream,
    stdout: stdout as NodeJS.WriteStream
  })

  // The PassThrough accumulates every repaint, and a collapsed panel stops
  // repainting entirely once settled — so assert on the FINAL chevron state
  // in the accumulated output rather than the tail after a clear().
  const finalChevronOpen = () => stripAnsi(output).lastIndexOf('▾ ') > stripAnsi(output).lastIndexOf('▸ ')

  return { finalChevronOpen, instance, trail }
}

describe('ToolTrail — collapsed mode stays manual while reasoning is live', () => {
  it('stays closed (▸) while reasoningActive is true under sections.thinking: collapsed', async () => {
    const { finalChevronOpen, instance } = mountTrail(true)

    await flushEffects()

    expect(finalChevronOpen()).toBe(false)

    instance.unmount()
    instance.cleanup()
  })

  it('stays closed after the reasoning phase ends mid-turn (rerender)', async () => {
    const { finalChevronOpen, instance, trail } = mountTrail(true)

    await flushEffects()

    // Reasoning phase finished (final answer / tool call started) — the
    // panel must remain closed: collapsed is entirely manual.
    instance.rerender(trail(false))

    await flushEffects()

    expect(finalChevronOpen()).toBe(false)

    instance.unmount()
    instance.cleanup()
  })

  it('leaves expanded-mode panels fully manual (no forced collapse)', async () => {
    const { finalChevronOpen, instance } = mountTrail(false, { thinking: 'expanded' })

    await flushEffects()

    // `expanded` is a manual preference: reasoningActive=false must NOT
    // force it closed.
    expect(finalChevronOpen()).toBe(true)

    instance.unmount()
    instance.cleanup()
  })
})

describe('ToolTrail — a tool row keeps its output until the row is opened', () => {
  const mountToolRow = (resultText: string, cols = 60) => {
    const stdout = new PassThrough()
    const stdin = new PassThrough()
    const stderr = new PassThrough()
    let output = ''

    Object.assign(stdout, { columns: cols, isTTY: false, rows: 20 })
    Object.assign(stdin, { isTTY: false })
    Object.assign(stderr, { isTTY: false })
    stdout.on('data', chunk => {
      output += chunk.toString()
    })

    const line = buildVerboseToolTrailLine('terminal', 'npm test', false, 1.2, undefined, resultText)

    const instance = renderSync(<ToolTrail sections={{ tools: 'expanded' }} t={DEFAULT_THEME} trail={[line]} />, {
      patchConsole: false,
      stderr: stderr as NodeJS.WriteStream,
      stdin: stdin as NodeJS.ReadStream,
      stdout: stdout as NodeJS.WriteStream
    })

    return { instance, rendered: () => stripAnsi(output) }
  }

  it('summarises the row and marks it expandable instead of rendering the whole block', async () => {
    const { instance, rendered } = mountToolRow(`${'A'.repeat(4_000)}TAIL-MARKER`)

    await flushEffects()

    const out = rendered()

    expect(out).toContain('Terminal("npm test")')
    expect(out).toContain('▸ ')
    // Layer 1 shows the concatenated line; the retained block is layer 2 and stays
    // out of the render tree until the user opens that row.
    expect(out).not.toContain('TAIL-MARKER')

    instance.unmount()
    instance.cleanup()
  })

  it('gives an output that already fits the preview the same toggle', async () => {
    // A wide terminal so the compacted result stays on the row's single line.
    const { instance, rendered } = mountToolRow('ok: 3 files changed', 200)

    await flushEffects()

    const out = rendered()

    expect(out).toContain('▸ ')
    expect(out).toContain('ok: 3 files changed')

    instance.unmount()
    instance.cleanup()
  })

  it('leaves a row with nothing to show as a bare single line', async () => {
    const stdout = new PassThrough()
    const stdin = new PassThrough()
    const stderr = new PassThrough()
    let output = ''

    Object.assign(stdout, { columns: 60, isTTY: false, rows: 20 })
    Object.assign(stdin, { isTTY: false })
    Object.assign(stderr, { isTTY: false })
    stdout.on('data', chunk => {
      output += chunk.toString()
    })

    const instance = renderSync(
      <ToolTrail
        sections={{ tools: 'expanded' }}
        t={DEFAULT_THEME}
        trail={[buildToolTrailLine('terminal', 'pwd', false, '', 0.3)]}
      />,
      {
        patchConsole: false,
        stderr: stderr as NodeJS.WriteStream,
        stdin: stdin as NodeJS.ReadStream,
        stdout: stdout as NodeJS.WriteStream
      }
    )

    await flushEffects()

    const out = stripAnsi(output)

    expect(out).toContain('Terminal("pwd")')
    expect(out).not.toContain('▸ ')

    instance.unmount()
    instance.cleanup()
  })
})
