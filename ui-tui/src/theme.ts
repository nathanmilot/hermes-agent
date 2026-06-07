export interface ThemeColors {
  primary: string
  accent: string
  border: string
  text: string
  muted: string
  completionBg: string
  completionCurrentBg: string
  completionMetaBg: string
  completionMetaCurrentBg: string

  label: string
  ok: string
  error: string
  warn: string

  prompt: string
  sessionLabel: string
  sessionBorder: string

  statusBg: string
  statusFg: string
  statusGood: string
  statusWarn: string
  statusBad: string
  statusCritical: string
  selectionBg: string

  diffAdded: string
  diffRemoved: string
  diffAddedWord: string
  diffRemovedWord: string

  shellDollar: string

  assistantText: string
  /** Tool-call markers (● bullet, tool spinner). Defaults to accent. */
  tool: string
  /** Reasoning/thinking body text. Defaults to muted. */
  thinking: string
  /** Code-block syntax highlights. */
  syntaxString: string
  syntaxNumber: string
  syntaxKeyword: string
  syntaxComment: string
}

export interface ThemeBrand {
  name: string
  icon: string
  prompt: string
  welcome: string
  goodbye: string
  tool: string
  helpHeader: string
}

export interface Theme {
  color: ThemeColors
  brand: ThemeBrand
  bannerLogo: string
  bannerHero: string
  bannerHeroSmall: string
}

// ── Color math ───────────────────────────────────────────────────────

function parseHex(h: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(h)

  if (!m) {
    return null
  }

  const n = parseInt(m[1]!, 16)

  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff]
}

function mix(a: string, b: string, t: number) {
  const pa = parseHex(a)
  const pb = parseHex(b)

  if (!pa || !pb) {
    return a
  }

  const lerp = (i: 0 | 1 | 2) => Math.round(pa[i] + (pb[i] - pa[i]) * t)

  return '#' + ((1 << 24) | (lerp(0) << 16) | (lerp(1) << 8) | lerp(2)).toString(16).slice(1)
}

const XTERM_6_LEVELS = [0, 95, 135, 175, 215, 255] as const
const ANSI_LIGHT_MAX_LUMINANCE = 0.72
const ANSI_LIGHT_TARGET_LUMINANCE = 0.34
const ANSI_LIGHT_MIN_SATURATION = 0.22
const ANSI_MUTED_BUCKET = 245

const ANSI_NORMALIZED_FOREGROUNDS: readonly (keyof ThemeColors)[] = [
  'text',
  'label',
  'ok',
  'error',
  'warn',
  'prompt',
  'statusFg',
  'statusGood',
  'statusWarn',
  'statusBad',
  'statusCritical',
  'shellDollar',
  'tool'
]

const ANSI_MUTED_FOREGROUNDS: readonly (keyof ThemeColors)[] = ['muted', 'sessionLabel', 'sessionBorder', 'thinking']

function xtermEightBitRgb(colorNumber: number): [number, number, number] {
  if (colorNumber >= 232) {
    const value = 8 + (colorNumber - 232) * 10

    return [value, value, value]
  }

  if (colorNumber >= 16) {
    const offset = colorNumber - 16

    return [
      XTERM_6_LEVELS[Math.floor(offset / 36) % 6]!,
      XTERM_6_LEVELS[Math.floor(offset / 6) % 6]!,
      XTERM_6_LEVELS[offset % 6]!
    ]
  }

  return [0, 0, 0]
}

function channelLuminance(value: number): number {
  const normalized = value / 255

  return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4
}

function relativeLuminance(red: number, green: number, blue: number): number {
  return 0.2126 * channelLuminance(red) + 0.7152 * channelLuminance(green) + 0.0722 * channelLuminance(blue)
}

function rgbToHsl(red: number, green: number, blue: number): [number, number, number] {
  const rn = red / 255
  const gn = green / 255
  const bn = blue / 255
  const max = Math.max(rn, gn, bn)
  const min = Math.min(rn, gn, bn)
  const lightness = (max + min) / 2

  if (max === min) {
    return [0, 0, lightness]
  }

  const delta = max - min
  const saturation = lightness > 0.5 ? delta / (2 - max - min) : delta / (max + min)

  const hue =
    max === rn
      ? (gn - bn) / delta + (gn < bn ? 6 : 0)
      : max === gn
        ? (bn - rn) / delta + 2
        : (rn - gn) / delta + 4

  return [hue / 6, saturation, lightness]
}

function circularDistance(a: number, b: number): number {
  const distance = Math.abs(a - b)

  return Math.min(distance, 1 - distance)
}

// Mirrors @hermes/ink's colorize.ts. Keep local: app code compiles from
// ui-tui/src, while @hermes/ink is bundled separately from packages/.
function richEightBitColorNumber(red: number, green: number, blue: number): number {
  const [, saturation, lightness] = rgbToHsl(red, green, blue)

  if (saturation < 0.15) {
    const gray = Math.round(lightness * 25)

    return gray === 0 ? 16 : gray === 25 ? 231 : 231 + gray
  }

  const sixRed = red < 95 ? red / 95 : 1 + (red - 95) / 40
  const sixGreen = green < 95 ? green / 95 : 1 + (green - 95) / 40
  const sixBlue = blue < 95 ? blue / 95 : 1 + (blue - 95) / 40

  return 16 + 36 * Math.round(sixRed) + 6 * Math.round(sixGreen) + Math.round(sixBlue)
}

function bestReadableAnsiColor(red: number, green: number, blue: number): number {
  const [hue, saturation, lightness] = rgbToHsl(red, green, blue)
  let bestColor = richEightBitColorNumber(red, green, blue)
  let bestScore = Number.POSITIVE_INFINITY

  for (let colorNumber = 16; colorNumber <= 255; colorNumber += 1) {
    const [candidateRed, candidateGreen, candidateBlue] = xtermEightBitRgb(colorNumber)
    const candidateLuminance = relativeLuminance(candidateRed, candidateGreen, candidateBlue)

    if (candidateLuminance > ANSI_LIGHT_MAX_LUMINANCE) {
      continue
    }

    const [candidateHue, candidateSaturation, candidateLightness] = rgbToHsl(
      candidateRed,
      candidateGreen,
      candidateBlue
    )

    const saturationFloorPenalty =
      candidateSaturation < ANSI_LIGHT_MIN_SATURATION ? (ANSI_LIGHT_MIN_SATURATION - candidateSaturation) * 3 : 0

    const score =
      circularDistance(candidateHue, hue) * 4 +
      Math.abs(candidateSaturation - Math.max(ANSI_LIGHT_MIN_SATURATION, saturation)) * 0.8 +
      Math.abs(candidateLightness - Math.min(lightness, ANSI_LIGHT_TARGET_LUMINANCE)) * 2 +
      saturationFloorPenalty

    if (score < bestScore) {
      bestColor = colorNumber
      bestScore = score
    }
  }

  return bestColor
}

function normalizeAnsiForeground(color: string): string {
  const rgb = parseHex(color)

  if (!rgb) {
    return color
  }

  const richAnsi = richEightBitColorNumber(rgb[0], rgb[1], rgb[2])
  const richRgb = xtermEightBitRgb(richAnsi)

  const ansi = relativeLuminance(richRgb[0], richRgb[1], richRgb[2]) > ANSI_LIGHT_MAX_LUMINANCE
    ? bestReadableAnsiColor(rgb[0], rgb[1], rgb[2])
    : richAnsi

  return `ansi256(${ansi})`
}

const ANSI256_RE = /^ansi256\((\d{1,3})\)$/

/**
 * The literal `#rrggbb` a theme tone paints as, or '' when it has none.
 *
 * The inverse of `normalizeAnsiForeground`: tones are not uniformly hex, since
 * a limited-palette terminal rewrites the foregrounds to `ansi256(N)`.
 * Consumers needing a real color — OSC 10/11, which only speak `#rrggbb` —
 * resolve through here rather than hex-testing the tone, which would silently
 * skip exactly the terminals that did the quantizing.
 */
export function themeToneHex(tone: string): string {
  const ansi = ANSI256_RE.exec(tone.trim())

  if (ansi) {
    const n = Number(ansi[1])

    return n <= 255 ? toHex(xtermEightBitRgb(n)) : ''
  }

  const rgb = parseColor(tone)

  return rgb ? toHex(rgb) : ''
}

// ── Defaults ─────────────────────────────────────────────────────────

const BRAND: ThemeBrand = {
  name: 'Hermes Agent',
  icon: '⚕',
  prompt: '❯',
  welcome: 'Type your message or /help for commands.',
  goodbye: 'Goodbye! ⚕',
  tool: '┊',
  helpHeader: '(^_^)? Commands'
}

const cleanPromptSymbol = (s: string | undefined, fallback: string) => {
  const cleaned = String(s ?? '')
    .replace(/\s+/g, ' ')
    .trim()

  return cleaned || fallback
}

export const DARK_THEME: Theme = {
  color: {
    primary: '#FFD700',
    accent: '#FFBF00',
    border: '#CD7F32',
    text: '#FFF8DC',
    muted: '#CC9B1F',
    // Bumped from the old `#B8860B` darkgoldenrod (~53% luminance) which
    // read as barely-visible on dark terminals for long body text.  The
    // new value sits ~60% luminance — readable without losing the "muted /
    // secondary" semantic.  Field labels still use `label` (65%) which
    // stays brighter so hierarchy holds.
    completionBg: '#1a1a2e',
    completionCurrentBg: '#333355',
    completionMetaBg: '#1a1a2e',
    completionMetaCurrentBg: '#333355',

    label: '#DAA520',
    ok: '#4caf50',
    error: '#ef5350',
    warn: '#ffa726',

    prompt: '#FFF8DC',
    // sessionLabel/sessionBorder intentionally track the `dim` value — they
    // are "same role, same colour" by design.  fromSkin's banner_dim fallback
    // relies on this pairing (#11300).
    sessionLabel: '#CC9B1F',
    sessionBorder: '#CC9B1F',

    statusBg: '#1a1a2e',
    statusFg: '#C0C0C0',
    statusGood: '#8FBC8F',
    statusWarn: '#FFD700',
    statusBad: '#FF8C00',
    statusCritical: '#FF6B6B',
    selectionBg: '#3a3a55',

    diffAdded: 'rgb(220,255,220)',
    diffRemoved: 'rgb(255,220,220)',
    diffAddedWord: 'rgb(36,138,61)',
    diffRemovedWord: 'rgb(207,34,46)',
    shellDollar: '#4dabf7',
    assistantText: '#6366f1',
    tool: '#FFBF00',
    thinking: '#CC9B1F',
    syntaxString: '#FFBF00',
    syntaxNumber: '#FFF8DC',
    syntaxKeyword: '#CD7F32',
    syntaxComment: '#CC9B1F'
  },

  brand: BRAND,

  bannerLogo: '',
  bannerHero: '',
  bannerHeroSmall: ''
}

// Light-terminal palette: darker golds/ambers that stay legible on white
// backgrounds. Same shape as DARK_THEME so `fromSkin` still layers on top
// cleanly (#11300).
export const LIGHT_THEME: Theme = {
  color: {
    primary: '#8B6914',
    accent: '#A0651C',
    border: '#7A4F1F',
    text: '#3D2F13',
    muted: '#7A5A0F',
    completionBg: '#F5F5F5',
    completionCurrentBg: mix('#F5F5F5', '#A0651C', 0.25),
    completionMetaBg: '#F5F5F5',
    completionMetaCurrentBg: mix('#F5F5F5', '#A0651C', 0.25),

    label: '#7A5A0F',
    ok: '#2E7D32',
    error: '#C62828',
    warn: '#E65100',

    prompt: '#2B2014',
    sessionLabel: '#7A5A0F',
    sessionBorder: '#7A5A0F',

    statusBg: '#F5F5F5',
    statusFg: '#333333',
    statusGood: '#2E7D32',
    statusWarn: '#8B6914',
    statusBad: '#D84315',
    statusCritical: '#B71C1C',
    selectionBg: '#D4E4F7',

    diffAdded: 'rgb(200,240,200)',
    diffRemoved: 'rgb(240,200,200)',
    diffAddedWord: 'rgb(27,94,32)',
    diffRemovedWord: 'rgb(183,28,28)',
    shellDollar: '#1565C0',
    assistantText: '#4f46e5',
    tool: '#A0651C',
    thinking: '#7A5A0F',
    syntaxString: '#A0651C',
    syntaxNumber: '#3D2F13',
    syntaxKeyword: '#7A4F1F',
    syntaxComment: '#7A5A0F'
  },

  brand: BRAND,

  bannerLogo: '',
  bannerHero: '',
  bannerHeroSmall: ''
}

// ── Background-aware readability adaptation ─────────────────────────
//
// Mirrors the desktop app's theme contract (apps/desktop/src/themes): skins
// contribute accent IDENTITY; readability against the actual background is
// the theme engine's job, enforced in one place. Two guards, in the desktop's
// vocabulary:
//
//   * `ensureContrast` — foreground-role colors are step-mixed toward the
//     readable pole (black on light, white on dark) until they clear a
//     minimum WCAG contrast ratio against the real (or assumed) background.
//     Hue survives; washout doesn't.
//   * Fill polarity — background-role colors (completion menu, status bar,
//     selection) must match the terminal's polarity. Unlike the desktop, the
//     TUI does not own its canvas — panels sit directly on the terminal's
//     background — so a wrong-polarity fill (navy menu on a white terminal)
//     falls back to the base palette even when the skin authored it.

// Display shim — the "rendering gotcha" layer, calibrated against the look
// the maintainers standardized on (pixel-sampled from the reference
// screenshot): the beloved cross-polarity rendering is the AUTHORED palette
// displayed RAW — slate's ~1.5:1 pastels on white read as deliberate airy
// hierarchy, not a bug. So the floors are barely-visible rescues only:
//   * DISPLAY 1.45 sits just above slate-pastel territory (#c9d1d9 = 1.54,
//     passes raw, byte-identical) but just below true invisibility
//     (default's cream #FFF8DC = 1.08, gets rescued).
//   * SEMANTIC 2.2 for alert colors (ok/error/warn/status) — they carry
//     meaning and must never vanish.
// The lift itself is xterm.js's own multiplicative algorithm
// (liftForContrast), so on hosts that run their own minimumContrastRatio the
// two adjustments agree instead of fighting.
// Foreground floors are polarity-aware. On a DARK background the authored
// palette is already bright, so a modest floor only rescues the rare dark
// tone. On a LIGHT background — which in practice means a TRANSPARENT Cursor/
// terminal window compositing over a light editor, where xterm applies NO
// contrast lift of its own (there is no solid bg to measure against) — the
// beloved classic look is the authored palette rendered essentially RAW:
// vivid #FFD700 gold (~1.36:1), not a WCAG-darkened mustard. So the light
// floor is a near-invisible rescue only (catches cream #FFF8DC at 1.08 but
// leaves the golds untouched). Pixel-sampled target: #F5C242 (L61 S90),
// which the previous 1.45 floor crushed to #867000 (L26) — the reported mud.
const DISPLAY_MIN_CONTRAST = 1.45
const SEMANTIC_MIN_CONTRAST = 2.2
const LIGHT_DISPLAY_MIN_CONTRAST = 1.18
const LIGHT_SEMANTIC_MIN_CONTRAST = 1.6

const DISPLAY_FOREGROUNDS: readonly (keyof ThemeColors)[] = [
  'primary',
  'accent',
  'text',
  'label',
  'prompt',
  'statusFg',
  'border',
  'muted',
  'sessionLabel',
  'sessionBorder',
  'shellDollar'
]

const SEMANTIC_FOREGROUNDS: readonly (keyof ThemeColors)[] = [
  'ok',
  'error',
  'warn',
  'statusGood',
  'statusWarn',
  'statusBad',
  'statusCritical'
]

const ADAPTIVE_BACKGROUNDS: readonly (keyof ThemeColors)[] = [
  'completionBg',
  'completionCurrentBg',
  'completionMetaBg',
  'completionMetaCurrentBg',
  'statusBg',
  'selectionBg'
]

// Fill polarity limits: on light terminals a fill must stay light, and vice
// versa — there is no readable middle for a panel fill on the wrong pole.
const LIGHT_BG_MIN_LUMINANCE = 0.4
const DARK_BG_MAX_LUMINANCE = 0.35

function adaptColorsToBackground(colors: ThemeColors, isLight: boolean, base: ThemeColors, bg: string): ThemeColors {
  const out = { ...colors }
  const displayFloor = isLight ? LIGHT_DISPLAY_MIN_CONTRAST : DISPLAY_MIN_CONTRAST
  const semanticFloor = isLight ? LIGHT_SEMANTIC_MIN_CONTRAST : SEMANTIC_MIN_CONTRAST

  for (const key of DISPLAY_FOREGROUNDS) {
    out[key] = liftForContrast(out[key], bg, displayFloor)
  }

  for (const key of SEMANTIC_FOREGROUNDS) {
    out[key] = liftForContrast(out[key], bg, semanticFloor)
  }

  for (const key of ADAPTIVE_BACKGROUNDS) {
    const luminance = relativeLuminance(out[key])

    if (luminance === null) {
      continue
    }

    if (isLight ? luminance < LIGHT_BG_MIN_LUMINANCE : luminance > DARK_BG_MAX_LUMINANCE) {
      out[key] = base[key]
    }
  }

  return out
}

/** The background hex adaptation measures contrast against: the OSC-11
 *  answer when known (cached in HERMES_TUI_BACKGROUND), else the mode's
 *  assumed pole. */
function referenceBackground(isLight: boolean, env: NodeJS.ProcessEnv = process.env): string {
  const cached = (env.HERMES_TUI_BACKGROUND ?? '').trim()

  if (cached && backgroundLuminance(cached) !== null) {
    return cached.startsWith('#') ? cached : `#${cached}`
  }

  return isLight ? '#ffffff' : '#101014'
}

// ── Derived tone ladder (the desktop color-mix system) ──────────────
//
// A theme is a handful of SEEDS (text, primary, accent, border, status hues);
// every secondary tone — muted text, labels, surfaces, selection chips — is a
// color-mix derivative of those seeds against the real terminal background,
// exactly like the desktop's `--theme-*` seeds → `--ui-*` color-mix ladder in
// apps/desktop/src/styles.css. Skins therefore cannot ship an incoherent
// "dim": if they don't author a tone, it is DERIVED from their own identity,
// never inherited from another skin's palette.
//
// Mix knobs are the single source of truth for tone hierarchy. (The classic
// prompt_toolkit CLI still reads the built-in skins' complete authored
// palettes; those were generated with the same math.)

export interface ThemeTones {
  /** Secondary/dim text: receded accent (dark) / primary-ink blend (light). */
  muted: string
  /** Field labels: one step brighter than muted, same family. */
  label: string
  /** Status-bar default text: the gray of slightly-receded text. */
  statusFg: string
  /** Raised panel fill: background nudged toward the (softened) accent. */
  surface: string
  /** Active list-row chip: surface tinted with accent. */
  activeRow: string
  /** Text-selection highlight: bg tinted with the theme's blue (light) or accent (dark). */
  selection: string
  /** Border fallback: accent receded toward the background. */
  border: string
}

/**
 * The fitted tone ladder. Knobs are REVERSE-ENGINEERED from the original
 * hand-tuned palettes (grid-search over mix/desaturate formula families
 * against the pre-refactor literals + every authored skin palette; see the
 * "reproduces the original hand-tuned tones" test for the contract):
 *
 *   dark muted  #CC9B1F ≈ desaturate(mix(accent, bg, .19), .16)  (err 3)
 *   dark label  #DAA520 ≈ desaturate(mix(accent, bg, .13), .16)  (err 3)
 *   dark status #C0C0C0 = grayOf(mix(text, bg, .24))             (err 0)
 *   light muted #946C08 ≈ desaturate(accent, .05)                (err 2)
 *   light label #8E6B13 ≈ desaturate(mix(accent, text, .03), .15) (err 2)
 *   light status #6F6F6F = grayOf(mix(text, bg, .30))            (err 1)
 *   light surface #F5F5F5 ≈ bg + softened accent                 (err 5)
 *   light chip  #E0D1BF = mix(surface, accent, .25)              (err 8)
 *   light selection #D4E4F7 ≈ mix(bg, shellDollar, .20)          (err 7)
 *
 * The light targets are the LIFT CANON: liftForContrast(dark literal,
 * white, 4.5) — what xterm's minimumContrastRatio showed on light hosts
 * for years — not hand-picked browns (those read as desaturated mud).
 *
 * The classic dark navy fills (#1a1a2e/#333355/#3a3a55) are IRREDUCIBLE from
 * gold seeds — the search bottoms out at gray, err 10–17 — so they remain
 * explicit identity seeds on DARK_SEEDS rather than pretending to be math.
 */
export function deriveTones(seeds: {
  accent: string
  bg: string
  primary: string
  shellDollar?: string
  text: string
}): ThemeTones {
  const { accent, bg, text } = seeds
  const isLight = (relativeLuminance(bg) ?? 0) > 0.5
  // Fill tint keeps most of the accent's chroma — a heavier desaturate here
  // read as washed-out ("a little too desat") next to authored fills.
  const surface = mix(bg, desaturate(accent, 0.15), isLight ? 0.045 : 0.09)

  return {
    // Light knobs are fitted to the lift canon (xterm minimumContrastRatio
    // 4.5 of the classic dark golds against white — see LIGHT_SEEDS), not
    // to ink blends: muted #946C08 ≈ desat(accent .05), label #8E6B13 ≈
    // desat(mix(accent, text, .03), .15), statusFg #6F6F6F ≈ gray 30% lift.
    muted: isLight ? desaturate(accent, 0.05) : desaturate(mix(accent, bg, 0.19), 0.16),
    label: isLight ? desaturate(mix(accent, text, 0.03), 0.15) : desaturate(mix(accent, bg, 0.13), 0.16),
    statusFg: grayOf(mix(text, bg, isLight ? 0.3 : 0.24)),
    surface,
    activeRow: mix(surface, accent, 0.25),
    selection: isLight && seeds.shellDollar ? mix(bg, seeds.shellDollar, 0.2) : mix(surface, accent, 0.28),
    border: mix(accent, bg, 0.25)
  }
}

const TRUE_RE = /^(?:1|true|yes|on)$/
const FALSE_RE = /^(?:0|false|no|off)$/

// TERM_PROGRAM fallback allow-list for terminals whose default profile is
// light and which may not expose COLORFGBG. This currently includes Apple
// Terminal. Explicit HERMES_TUI_THEME / COLORFGBG signals above still win,
// so dark Apple Terminal profiles that advertise a dark background stay dark.
const LIGHT_DEFAULT_TERM_PROGRAMS = new Set<string>(['Apple_Terminal'])

// Best-effort RGB → luminance check.  Currently only accepts a 3- or
// 6-digit hex value (with or without a leading `#`); the env var name
// `HERMES_TUI_BACKGROUND` is intentionally generic so a future OSC11
// query helper can cache its answer there too, but additional formats
// (rgb()/hsl()/named colours) would need explicit parsing here first.
const LUMA_LIGHT_THRESHOLD = 0.6

// Strict allow-list: parseInt(..., 16) silently truncates at the first
// non-hex character (e.g. `fffgff` would parse as `fff` and yield a
// false-positive "white" reading), so reject anything that doesn't match
// the canonical 3- or 6-digit shape up front.
const HEX_3_RE = /^[0-9a-f]{3}$/
const HEX_6_RE = /^[0-9a-f]{6}$/

function backgroundLuminance(raw: string): null | number {
  const v = raw.trim().toLowerCase()

  if (!v) {
    return null
  }

  const hex = v.startsWith('#') ? v.slice(1) : v

  const rgb = HEX_6_RE.test(hex)
    ? [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)]
    : HEX_3_RE.test(hex)
      ? [parseInt(hex[0]! + hex[0]!, 16), parseInt(hex[1]! + hex[1]!, 16), parseInt(hex[2]! + hex[2]!, 16)]
      : null

  if (!rgb) {
    return null
  }

  // Rec. 709 luma — close enough for "is this background bright".
  return (0.2126 * rgb[0]! + 0.7152 * rgb[1]! + 0.0722 * rgb[2]!) / 255
}

// Pick light vs dark with ordered, explainable signals (#11300):
//
//   1. `HERMES_TUI_LIGHT` boolean — `1`/`true`/`yes`/`on` → light;
//      `0`/`false`/`no`/`off` → dark.  Either explicit value wins
//      regardless of any later signal.
//   2. `HERMES_TUI_THEME` named override — `light` / `dark` win over
//      every signal below.
//   3. `HERMES_TUI_BACKGROUND` hex hint (3- or 6-digit) — luminance
//      ≥ LUMA_LIGHT_THRESHOLD → light.
//   4. `COLORFGBG` last field — XFCE / rxvt / Terminal.app emit
//      slot 7 or 15 on light profiles; 0–15 ranges are otherwise
//      treated as authoritatively dark so the TERM_PROGRAM
//      allow-list below cannot override an explicit dark profile.
//   5. `TERM_PROGRAM` light-default allow-list.
//
// Anything we can't decide stays dark — the default Hermes palette
// is the dark one.
export function detectLightMode(
  env: NodeJS.ProcessEnv = process.env,
  // Injectable so tests can prove the COLORFGBG-over-TERM_PROGRAM
  // precedence rule even though the production allow-list is empty.
  lightDefaultTermPrograms: ReadonlySet<string> = LIGHT_DEFAULT_TERM_PROGRAMS
): boolean {
  const lightFlag = (env.HERMES_TUI_LIGHT ?? '').trim().toLowerCase()

  if (TRUE_RE.test(lightFlag)) {
    return true
  }

  if (FALSE_RE.test(lightFlag)) {
    return false
  }

  const themeFlag = (env.HERMES_TUI_THEME ?? '').trim().toLowerCase()

  if (themeFlag === 'light') {
    return true
  }

  if (themeFlag === 'dark') {
    return false
  }

  const bgHint = backgroundLuminance(env.HERMES_TUI_BACKGROUND ?? '')

  if (bgHint !== null) {
    return bgHint >= LUMA_LIGHT_THRESHOLD
  }

  const colorfgbg = (env.COLORFGBG ?? '').trim()

  if (colorfgbg) {
    // Validate as a decimal integer before coercing — `Number('')` is 0,
    // so a malformed `COLORFGBG='15;'` would otherwise look like an
    // authoritative dark slot and incorrectly block the TERM_PROGRAM
    // allow-list.  Anything that isn't pure digits falls through.
    const lastField = colorfgbg.split(';').at(-1) ?? ''

    if (/^\d+$/.test(lastField)) {
      const bg = Number(lastField)

      if (bg === 7 || bg === 15) {
        return true
      }

      // Slots 0–6 and 8–14 are the dark half of the 0–15 ANSI range.
      // When COLORFGBG is set we trust it as authoritative — a non-light
      // value here shouldn't get overridden by the TERM_PROGRAM allow-list.
      if (bg >= 0 && bg < 16) {
        return false
      }
    }
  }

  const termProgram = (env.TERM_PROGRAM ?? '').trim()

  return lightDefaultTermPrograms.has(termProgram)
}

function shouldNormalizeAnsiLightTheme(env: NodeJS.ProcessEnv = process.env, isLight = detectLightMode(env)): boolean {
  const colorTerm = (env.COLORTERM ?? '').trim().toLowerCase()
  const termProgram = (env.TERM_PROGRAM ?? '').trim()

  return termProgram === 'Apple_Terminal' && colorTerm !== 'truecolor' && colorTerm !== '24bit' && isLight
}

export function normalizeThemeForAnsiLightTerminal(
  theme: Theme,
  env: NodeJS.ProcessEnv = process.env,
  isLight = detectLightMode(env)
): Theme {
  if (!shouldNormalizeAnsiLightTheme(env, isLight)) {
    return theme
  }

  const color = { ...theme.color }

  for (const key of ANSI_NORMALIZED_FOREGROUNDS) {
    color[key] = normalizeAnsiForeground(color[key])
  }

  for (const key of ANSI_MUTED_FOREGROUNDS) {
    color[key] = `ansi256(${ANSI_MUTED_BUCKET})`
  }

  return { ...theme, color }
}

const DEFAULT_LIGHT_MODE = detectLightMode()

export const DEFAULT_THEME: Theme = normalizeThemeForAnsiLightTerminal(
  DEFAULT_LIGHT_MODE ? LIGHT_THEME : DARK_THEME,
  process.env,
  DEFAULT_LIGHT_MODE
)

// ── Skin → Theme ─────────────────────────────────────────────────────

export function fromSkin(
  colors: Record<string, string>,
  branding: Record<string, string>,
  bannerLogo = '',
  bannerHero = '',
  toolPrefix = '',
  helpHeader = '',
  bannerHeroSmall = ''
): Theme {
  const d = DEFAULT_THEME
  const c = (k: string) => colors[k]
  const hasSkinColors = Object.keys(colors).length > 0

  const accent = c('ui_accent') ?? c('banner_accent') ?? d.color.accent
  const bannerAccent = c('banner_accent') ?? c('banner_title') ?? d.color.accent
  const muted = c('banner_dim') ?? d.color.muted
  const completionBg = c('completion_menu_bg') ?? d.color.completionBg

  const completionCurrentBg =
    c('completion_menu_current_bg') ??
    (hasSkinColors ? mix(completionBg, bannerAccent, 0.25) : d.color.completionCurrentBg)

  const completionMetaBg = c('completion_menu_meta_bg') ?? completionBg
  const completionMetaCurrentBg = c('completion_menu_meta_current_bg') ?? completionCurrentBg

  return normalizeThemeForAnsiLightTerminal({
    color: {
      primary: c('ui_primary') ?? c('banner_title') ?? d.color.primary,
      accent,
      border: c('ui_border') ?? c('banner_border') ?? d.color.border,
      text: c('ui_text') ?? c('banner_text') ?? d.color.text,
      muted,
      completionBg,
      completionCurrentBg,
      completionMetaBg,
      completionMetaCurrentBg,

      label: c('ui_label') ?? d.color.label,
      ok: c('ui_ok') ?? d.color.ok,
      error: c('ui_error') ?? d.color.error,
      warn: c('ui_warn') ?? d.color.warn,

      prompt: c('prompt') ?? c('banner_text') ?? d.color.prompt,
      sessionLabel: c('session_label') ?? muted,
      sessionBorder: c('session_border') ?? muted,

      statusBg: d.color.statusBg,
      statusFg: d.color.statusFg,
      statusGood: c('ui_ok') ?? d.color.statusGood,
      statusWarn: c('ui_warn') ?? d.color.statusWarn,
      statusBad: d.color.statusBad,
      statusCritical: d.color.statusCritical,
      selectionBg: c('selection_bg') ?? c('completion_menu_current_bg') ?? (hasSkinColors ? completionCurrentBg : d.color.selectionBg),

      diffAdded: c('diff_added') ?? d.color.diffAdded,
      diffRemoved: c('diff_removed') ?? d.color.diffRemoved,
      diffAddedWord: c('diff_added_word') ?? d.color.diffAddedWord,
      diffRemovedWord: c('diff_removed_word') ?? d.color.diffRemovedWord,
      shellDollar: c('shell_dollar') ?? d.color.shellDollar,
      assistantText: c('assistant_text') ?? d.color.assistantText,
      tool: c('ui_tool') ?? d.color.accent,
      thinking: c('ui_thinking') ?? c('banner_dim') ?? d.color.muted,
      syntaxString: c('syntax_string') ?? d.color.accent,
      syntaxNumber: c('syntax_number') ?? d.color.text,
      syntaxKeyword: c('syntax_keyword') ?? d.color.border,
      syntaxComment: c('syntax_comment') ?? d.color.muted
    },

    brand: {
      name: branding.agent_name ?? d.brand.name,
      icon: d.brand.icon,
      prompt: cleanPromptSymbol(branding.prompt_symbol, d.brand.prompt),
      welcome: branding.welcome ?? d.brand.welcome,
      goodbye: branding.goodbye ?? d.brand.goodbye,
      tool: toolPrefix || d.brand.tool,
      helpHeader: branding.help_header ?? (helpHeader || d.brand.helpHeader)
    },

    bannerLogo,
    bannerHero,
    bannerHeroSmall
  }, process.env, DEFAULT_LIGHT_MODE)
}
}

export function defaultThemeForCurrentBackground(env: NodeJS.ProcessEnv = process.env): Theme {
  const isLight = detectLightMode(env)
  return normalizeThemeForAnsiLightTerminal(isLight ? LIGHT_THEME : DARK_THEME, env, isLight)
}

export function skinIsLight(colors: Record<string, string>, env: NodeJS.ProcessEnv = process.env): boolean {
  const bg = (colors['background'] ?? '').trim()
  if (!bg) return detectLightMode(env)
  const lum = backgroundLuminance(bg)
  return lum !== null ? lum >= LUMA_LIGHT_THRESHOLD : detectLightMode(env)
