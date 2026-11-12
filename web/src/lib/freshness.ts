import { ranAt } from "./format"

const OPEN = { hour: 10, minute: 15, label: "10:15 a.m. Eastern" }
const CLOSE = { hour: 18, minute: 30, label: "6:30 p.m. Eastern" }
const GRACE_MS = 25 * 60 * 1000

const HOLIDAYS = new Set([
  "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
  "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
  "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
  "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
])

type Slot = { time: Date; label: string }

function nyParts(moment: Date) {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  })
  const parts = Object.fromEntries(fmt.formatToParts(moment).map((part) => [part.type, part.value]))
  const weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(parts.weekday)
  return {
    weekday,
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    key: `${parts.year}-${parts.month}-${parts.day}`,
  }
}

/** UTC instant of a New York wall-clock time. */
function atNewYork(year: number, month: number, day: number, hour: number, minute: number): Date {
  const guess = Date.UTC(year, month - 1, day, hour + 5, minute)
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  })
  const parts = Object.fromEntries(fmt.formatToParts(new Date(guess)).map((part) => [part.type, part.value]))
  const shown = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute))
  const wanted = Date.UTC(year, month - 1, day, hour, minute)
  return new Date(guess + (wanted - shown))
}

function slotsOn(year: number, month: number, day: number, weekday: number, key: string): Slot[] {
  if (weekday === 0 || weekday === 6 || HOLIDAYS.has(key)) return []
  return [OPEN, CLOSE].map((slot) => ({
    time: atNewYork(year, month, day, slot.hour, slot.minute),
    label: slot.label,
  }))
}

export function lastExpectedSlot(now: Date, graceMs = GRACE_MS): Slot | null {
  const cutoff = now.getTime() - graceMs
  const start = nyParts(new Date(cutoff))
  for (let back = 0; back < 8; back += 1) {
    const probe = new Date(Date.UTC(start.year, start.month - 1, start.day - back, 17, 0))
    const parts = nyParts(probe)
    const due = slotsOn(parts.year, parts.month, parts.day, parts.weekday, parts.key).filter((slot) => slot.time.getTime() <= cutoff)
    if (due.length) return due[due.length - 1]
  }
  return null
}

/** Plain sentence when the file is older than the run that should already have replaced it. */
export function freshnessNote(generatedAt: string | null | undefined, now = new Date()): string | null {
  if (!generatedAt) return null
  const generated = new Date(generatedAt)
  if (Number.isNaN(generated.getTime())) return null
  const slot = lastExpectedSlot(now)
  if (!slot || generated.getTime() >= slot.time.getTime()) return null
  return `This file is from ${ranAt(generatedAt)}. The ${slot.label} run has not landed, so this is the previous list, not a new one.`
}
