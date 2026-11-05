import { describe, expect, it } from "vitest"
import { daysUntil, judgeOption, nearestQuote, quotesFor, type JudgeInput, type PriceBoard } from "./priceCheck"
import { defaultSettings, toJobConfig } from "./settings"

function base(overrides: Partial<JudgeInput> = {}): JudgeInput {
  return {
    spot: 20,
    iv: 0.4,
    hv20: 0.4,
    hv60: 0.4,
    ivPercentile: 50,
    bid: 1,
    ask: 1.1,
    oi: 500,
    dte: 30,
    earningsDays: null,
    earningsWindow: 14,
    ...overrides,
  }
}

describe("judgeOption", () => {
  it("calls a contract cheap when the priced-in move is well under the stock's usual move", () => {
    const result = judgeOption(base({ iv: 0.3 }))
    expect(result.verdict).toBe("Cheap")
    expect(result.reason).toBe(
      "This looks cheap because it prices in about a $1.72 move, and this stock's usual move over 30 days is about $2.29.",
    )
  })

  it("calls a contract fair when the two moves are close", () => {
    const result = judgeOption(base())
    expect(result.verdict).toBe("Fair")
    expect(result.reason).toBe(
      "This looks fair because it prices in about a $2.29 move, close to this stock's usual $2.29 move over 30 days.",
    )
  })

  it("calls a contract expensive when the priced-in move is much larger", () => {
    const result = judgeOption(base({ iv: 0.7 }))
    expect(result.verdict).toBe("Expensive")
    expect(result.reason).toContain("about a $4.01 move")
    expect(result.reason).toContain("usual move over 30 days is about $2.29")
  })

  it("treats a rich price before earnings as fair unless it is extreme", () => {
    const softened = judgeOption(base({ iv: 0.7, earningsDays: 4 }))
    expect(softened.verdict).toBe("Fair")
    expect(softened.reason).toContain("earnings are in 4 days")
    expect(softened.reason).toContain("announcement")

    const extreme = judgeOption(base({ iv: 0.9, earningsDays: 3 }))
    expect(extreme.verdict).toBe("Expensive")
    expect(extreme.reason).toContain("even with earnings in 3 days")
  })

  it("ignores earnings that fall after this expiration", () => {
    const result = judgeOption(base({ iv: 0.7, earningsDays: 10, dte: 5 }))
    expect(result.verdict).toBe("Expensive")
    expect(result.reason).not.toContain("earnings")
  })

  it("steps the verdict toward expensive when the bid-ask gap is wide", () => {
    const fairGoesRich = judgeOption(base({ bid: 0.3, ask: 0.7 }))
    expect(fairGoesRich.verdict).toBe("Expensive")
    expect(fairGoesRich.reason).toContain("ask is 80% above the bid")

    const cheapGoesFair = judgeOption(base({ iv: 0.3, bid: 0.2, ask: 0.6 }))
    expect(cheapGoesFair.verdict).toBe("Fair")
    expect(cheapGoesFair.reason).toContain("pay up")
  })

  it("steps a thin wide market toward expensive and mentions a thin tight market", () => {
    const thinWide = judgeOption(base({ oi: 12, bid: 0.42, ask: 0.5 }))
    expect(thinWide.verdict).toBe("Expensive")
    expect(thinWide.reason).toContain("only 12 contracts are open")

    const thinTight = judgeOption(base({ oi: 12 }))
    expect(thinTight.verdict).toBe("Fair")
    expect(thinTight.reason).toContain("only 12 contracts are open")
  })

  it("lets a year of the stock's own swings pull an extreme price back to fair", () => {
    const quietYear = judgeOption(base({ iv: 0.7, ivPercentile: 10 }))
    expect(quietYear.verdict).toBe("Fair")
    expect(quietYear.reason).toContain("higher than only 10%")

    const wildYear = judgeOption(base({ iv: 0.3, ivPercentile: 90 }))
    expect(wildYear.verdict).toBe("Fair")
    expect(wildYear.reason).toContain("higher than 90%")
  })

  it("mentions the rank when it agrees with an expensive price", () => {
    const result = judgeOption(base({ iv: 0.7, ivPercentile: 90 }))
    expect(result.verdict).toBe("Expensive")
    expect(result.reason).toContain("higher than 90% of this stock's own swings")
  })

  it("moves a fair price toward expensive when a day of decay is a large share of the premium", () => {
    const fast = judgeOption(base({ iv: 0.4, dte: 7, bid: 0.4, ask: 0.44, strike: 20, side: "call" }))
    expect(fast.verdict).toBe("Expensive")
    expect(fast.reason).toContain("loses about $3.26 a day")
    expect(fast.reason).toContain("8% of what you pay")
    expect(fast.greeks?.warnings).toEqual([])
    expect(fast.greeks?.thetaLine).toContain("lost per day per contract")

    const sameDecayOnAPriceyContract = judgeOption(base({ iv: 0.4, dte: 7, bid: 2, ask: 2.2, strike: 20, side: "call" }))
    expect(sameDecayOnAPriceyContract.verdict).toBe("Fair")
    expect(sameDecayOnAPriceyContract.greeks?.warnings).toEqual([])
  })

  it("warns when decay is high but the price was already expensive", () => {
    const result = judgeOption(base({ iv: 0.7, dte: 7, bid: 0.48, ask: 0.52, strike: 20, side: "call" }))
    expect(result.verdict).toBe("Expensive")
    expect(result.reason).not.toContain("a day")
    expect(result.greeks?.warnings.join(" ")).toContain("Time decay is high")
  })

  it("keeps a cheap long shot from reading as a bargain", () => {
    const result = judgeOption(base({ iv: 0.3, dte: 90, bid: 0.38, ask: 0.42, strike: 26, side: "call" }))
    expect(result.verdict).toBe("Fair")
    expect(result.reason).toContain("only about 5%")
    expect(result.reason).toContain("long shot")
    expect(result.greeks?.delta).toBeCloseTo(0.0526, 3)
    expect(result.greeks?.warnings).toEqual([])
  })

  it("warns on a low chance without changing a fair price", () => {
    const result = judgeOption(base({ iv: 0.4, dte: 90, bid: 0.38, ask: 0.42, strike: 26, side: "call" }))
    expect(result.verdict).toBe("Fair")
    expect(result.reason).not.toContain("long shot")
    expect(result.greeks?.warnings.join(" ")).toContain("long shot")
  })

  it("leaves the verdict alone when no strike was passed", () => {
    const result = judgeOption(base())
    expect(result.greeks).toBeNull()
    expect(result.verdict).toBe("Fair")
  })

  it("refuses a verdict when the quote or the history is missing", () => {
    expect(judgeOption(base({ iv: null })).verdict).toBeNull()
    expect(judgeOption(base({ bid: 0 })).reason).toContain("bid and ask")
    expect(judgeOption(base({ hv20: null, hv60: null })).verdict).toBeNull()
    expect(judgeOption(base({ dte: 0 })).verdict).toBeNull()
  })

  it("still works when only the 20-day swings are known", () => {
    const result = judgeOption(base({ hv60: null, iv: 0.3 }))
    expect(result.verdict).toBe("Cheap")
  })
})

describe("checker settings", () => {
  it("starts on and is included in the job file", () => {
    const settings = defaultSettings()
    expect(settings.features.priceCheck).toBe(true)
    expect(settings.checkerMinOi).toBe(0)
    expect(settings.checkerEarningsDays).toBe(14)
    expect(toJobConfig(settings).features.priceCheck).toBe(true)
  })
})

describe("daysUntil and strike picking", () => {
  const board: PriceBoard = {
    ticker: "SOFI",
    company: "SoFi",
    price: 20,
    hv20: 0.4,
    hv60: 0.4,
    earningsDate: "2026-11-20",
    expirations: [
      {
        expiry: "2026-12-18",
        calls: [
          { strike: 18, bid: 1, ask: 1.1, oi: 10, iv: 0.4, ivPercentile: 40 },
          { strike: 22, bid: 0.4, ask: 0.5, oi: 80, iv: 0.4, ivPercentile: 40 },
        ],
        puts: [{ strike: 19, bid: 0.4, ask: 0.45, oi: 5, iv: 0.42, ivPercentile: 40 }],
      },
    ],
  }

  it("counts calendar days from a fixed today", () => {
    expect(daysUntil("2026-12-18", "2026-11-05")).toBe(43)
    expect(daysUntil("2026-11-05", "2026-11-05")).toBe(0)
  })

  it("hides thin strikes and picks the strike nearest the stock", () => {
    expect(quotesFor(board, "call", "2026-12-18", 50).map((quote) => quote.strike)).toEqual([22])
    expect(nearestQuote(board.expirations[0].calls, 20)?.strike).toBe(18)
    expect(quotesFor(board, "put", "2026-12-18", 0)).toHaveLength(1)
  })
})
