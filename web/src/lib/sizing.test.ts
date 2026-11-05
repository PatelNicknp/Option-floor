import { describe, expect, it } from "vitest"
import { payoffRows } from "./format"
import { sizeTrade } from "./sizing"

describe("sizeTrade", () => {
  it("fits one contract inside the default band", () => {
    expect(sizeTrade(0.5, 800, 40, 80)).toBe(1)
  })

  it("uses three contracts when each one is $20", () => {
    expect(sizeTrade(0.2, 800, 40, 80)).toBe(3)
  })

  it("skips a contract that costs more than the cap", () => {
    expect(sizeTrade(0.85, 800, 40, 80)).toBeNull()
    expect(sizeTrade(0.6, 500, 40, 80)).toBeNull()
    expect(sizeTrade(0, 800, 40, 80)).toBeNull()
  })
})

describe("payoffRows", () => {
  it("matches the expiration math for a call", () => {
    const rows = Object.fromEntries(payoffRows("call", 20, 0.5, 1, 20, [-20, 20]).map((row) => [row.pct, row]))
    expect(rows[20]).toMatchObject({ stock: 24, value: 400, pnl: 350 })
    expect(rows[-20]).toMatchObject({ pnl: -50 })
  })
})
