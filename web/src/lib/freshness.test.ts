import { describe, expect, it } from "vitest"
import { freshnessNote } from "./freshness"

describe("freshnessNote", () => {
  it("says Monday afternoon is still showing Friday night", () => {
    const note = freshnessNote("2026-11-06T21:57:28.215503-05:00", new Date("2026-11-09T20:14:00Z"))
    expect(note).toContain("10:15 a.m. Eastern")
    expect(note).toContain("previous list")
  })

  it("stays quiet when the file is after the latest slot", () => {
    const note = freshnessNote("2026-11-06T21:57:00-05:00", new Date("2026-11-07T03:10:00Z"))
    expect(note).toBeNull()
  })

  it("waits through the first minutes after a slot", () => {
    const note = freshnessNote("2026-11-06T21:57:00-05:00", new Date("2026-11-09T15:20:00Z"))
    expect(note).toBeNull()
  })
})
