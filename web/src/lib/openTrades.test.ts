import { describe, expect, it } from "vitest"
import { barPosition, daysBetween, openTotals, sparkPath, statusSentence, tradeHistory, viewTrade } from "./openTrades"
import type { PaperTrade } from "../types"

const base: PaperTrade = {
  id: "ATEC-call-7.5-2026-11-20",
  ticker: "ATEC",
  action: "BUY CALL",
  strike: 7.5,
  expiry: "2026-11-20",
  entry: 0.5,
  lastMark: 0.9,
  contracts: 1,
  remainingContracts: 1,
  openedAt: "2026-11-05T18:30:00-05:00",
  lastChecked: "2026-11-10",
  lastExitDate: "2026-11-18",
}

describe("open trade view", () => {
  it("works out dollars and percent from contracts times 100", () => {
    const view = viewTrade(base, Date.UTC(2026, 10, 11))
    expect(view.cost).toBeCloseTo(50)
    expect(view.value).toBeCloseTo(90)
    expect(view.pnl).toBeCloseTo(40)
    expect(view.pct).toBeCloseTo(80)
    expect(view.daysHeld).toBe(6)
    expect(view.daysLeft).toBe(7)
    expect(view.status).toContain("Up 80%, getting close to the double target.")
    expect(view.status).toContain("7 days left")
  })

  it("places the marker between the half-loss exit and the double", () => {
    expect(barPosition(-50)).toBe(0)
    expect(barPosition(0)).toBeCloseTo(33.33, 1)
    expect(barPosition(100)).toBe(100)
    expect(barPosition(250)).toBe(100)
    expect(barPosition(-90)).toBe(0)
    expect(barPosition(null)).toBeNull()
  })

  it("writes plain status sentences", () => {
    expect(statusSentence(-40, 30)).toBe("Down 40%, getting close to the half-loss exit.")
    expect(statusSentence(0.5, 30)).toBe("About flat, close to what it cost.")
    expect(statusSentence(120, 30)).toContain("past the double")
    expect(statusSentence(null, null)).toContain("unknown")
  })

  it("only uses stored prices for the chart", () => {
    expect(tradeHistory(base).map((point) => point.mark)).toEqual([0.5, 0.9])
    const stored = { ...base, markHistory: [{ at: "a", mark: 0.5 }, { at: "b", mark: 0.6 }, { at: "c", mark: 0.9 }] }
    expect(tradeHistory(stored)).toHaveLength(3)
    const sameDay = { ...base, lastChecked: "2026-11-05" }
    expect(tradeHistory(sameDay)).toHaveLength(1)
  })

  it("adds up the open totals and skips unpriced trades", () => {
    const other: PaperTrade = { ...base, id: "x", entry: 0.4, lastMark: 0.3, remainingContracts: 2 }
    const unpriced: PaperTrade = { ...base, id: "y", lastMark: undefined }
    const totals = openTotals([base, other, unpriced])
    expect(totals.cost).toBeCloseTo(130)
    expect(totals.value).toBeCloseTo(150)
    expect(totals.pnl).toBeCloseTo(20)
    expect(totals.priced).toBe(2)
    expect(totals.count).toBe(3)
  })

  it("draws a path for one or many points", () => {
    expect(sparkPath([], 100, 40)).toBeNull()
    expect(sparkPath([1], 100, 40)?.line).toMatch(/^M/)
    const shape = sparkPath([1, 2, 1.5], 100, 40)!
    expect(shape.points).toHaveLength(3)
    expect(shape.points[1][1]).toBeLessThan(shape.points[0][1])
  })

  it("counts days on calendar dates", () => {
    expect(daysBetween("2026-11-05T23:00:00-05:00", Date.UTC(2026, 10, 6))).toBe(1)
  })
})
