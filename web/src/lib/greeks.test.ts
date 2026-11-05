import { describe, expect, it } from "vitest"
import { blackScholesGreeks } from "./greeks"

describe("blackScholesGreeks", () => {
  it("matches a one-year at-the-money call", () => {
    const greeks = blackScholesGreeks({ spot: 100, strike: 100, iv: 0.2, dte: 365, side: "call", rate: 0.04 })
    expect(greeks).not.toBeNull()
    expect(greeks!.delta).toBeCloseTo(0.6179, 3)
    expect(greeks!.gamma).toBeCloseTo(0.0191, 3)
    expect(greeks!.vegaPerPoint).toBeCloseTo(38.14, 1)
    expect(greeks!.dollarsLostPerDay).toBeCloseTo(1.61, 1)
    expect(greeks!.deltaLine).toContain("rough chance of finishing in the money is about 62%")
    expect(greeks!.vegaLine).toContain("from 20% to 21%")
    expect(greeks!.gammaLine).toContain("If the stock moves $1")
    expect(greeks!.thetaLine).toContain("lost per day per contract")
  })

  it("uses the same gamma and vega for the put, with a negative delta", () => {
    const call = blackScholesGreeks({ spot: 20, strike: 20, iv: 0.4, dte: 30, side: "call" })!
    const put = blackScholesGreeks({ spot: 20, strike: 20, iv: 0.4, dte: 30, side: "put" })!
    expect(call.delta).toBeCloseTo(0.5343, 3)
    expect(put.delta).toBeCloseTo(-0.4657, 3)
    expect(call.delta - put.delta).toBeCloseTo(1, 3)
    expect(put.gamma).toBeCloseTo(call.gamma, 6)
    expect(put.vegaPerPoint).toBeCloseTo(call.vegaPerPoint, 4)
    expect(put.dollarsLostPerDay).toBeGreaterThan(0)
    expect(put.deltaLine).toContain("Delta is -0.47")
  })

  it("refuses a contract with no time or no volatility", () => {
    expect(blackScholesGreeks({ spot: 20, strike: 20, iv: 0.4, dte: 0, side: "call" })).toBeNull()
    expect(blackScholesGreeks({ spot: 20, strike: 20, iv: 0, dte: 30, side: "call" })).toBeNull()
    expect(blackScholesGreeks({ spot: 0, strike: 20, iv: 0.4, dte: 30, side: "call" })).toBeNull()
  })
})
