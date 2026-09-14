export const LARGE_PASTE = { lines: 5 }

export const LIVE_RENDER_MAX_CHARS = 16_000
export const LIVE_RENDER_MAX_LINES = 240

// Persisted verbose tool-trail blocks (Args/Result embedded in a completed
// tool line) are kept for the WHOLE session in transcript Msg.tools[] and used
// to be rendered expanded by default, so a render-node tree was built for every
// one of up to MAX_HISTORY messages at once. Capping these to the live-render
// budget (16KB) let a heavy browser/large-output session retain ~12MB of
// strings that exploded into a few hundred MB of Ink nodes and silently OOM-
// killed the Node parent (→ stdin EOF, gateway death; issue #34095).
//
// The row no longer renders the block by default: it shows a one-line summary and
// the block is drawn only for the row the user expanded, one at a time. So this
// constant is now just the inline preview (what the summary is built from), while
// the untruncated block rides on the line capped at the LIVE_RENDER budget below.
// Full output remains in the agent context and the SQLite session; the trail is a
// glance, and a per-row inspection, not a log.
// ponytail: retained raw text is LIVE_RENDER_MAX_CHARS per tool row for the whole
// session (~16KB × rows, all collapsed so the render tree stays small). Lower the
// cap in buildVerboseToolTrailLine if a long session's RSS becomes a problem.
export const VERBOSE_TRAIL_MAX_CHARS = 800
export const VERBOSE_TRAIL_MAX_LINES = 12

export const LONG_MSG = 300
export const MAX_HISTORY = 800
export const THINKING_COT_MAX = 160

// Rows per wheel event (pre-accel). 1 keeps Ink's DECSTBM fast path live
// (each scroll < viewport-1) and produces smooth motion. wheelAccel.ts
// ramps this on sustained scrolls.
export const WHEEL_SCROLL_STEP = 1
