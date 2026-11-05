import { describe, expect, it, vi } from "vitest"
import {
  buildLookupBoard,
  cboeSymbol,
  extractJson,
  lookupTicker,
  normalizeTicker,
  parseCboeChain,
  parseCboeOptionSymbol,
  parseYahooChart,
  percentileBelow,
  readerUrl,
  realizedVol,
  yahooSymbol,
} from "./lookup"

const closes = [9.8, 10.5, 10, 10.7, 10.2, 10.9, 10.4, 11.1, 10.6, 11.3, 10.8, 11.5, 11, 11.7, 11.2, 11.9, 11.4, 12.1, 11.6, 12.3, 11.8, 12.5, 12, 12.7, 12.2, 12.9, 12.4, 13.1, 12.6, 13.3, 12.8, 13.5, 13, 13.7, 13.2, 13.9, 13.4, 14.1, 13.6, 14.3]

describe("ticker names", () => {
  it("accepts a plain US ticker and a share class", () => {
    expect(normalizeTicker(" f ")).toBe("F")
    expect(normalizeTicker("brk.b")).toBe("BRK.B")
    expect(cboeSymbol("BRK.B")).toBe("BRKB")
    expect(yahooSymbol("BRK.B")).toBe("BRK-B")
    expect(normalizeTicker("not a stock")).toBeNull()
    expect(normalizeTicker("123")).toBeNull()
  })
})

describe("free quote parsers", () => {
  it("reads a Cboe contract symbol", () => {
    expect(parseCboeOptionSymbol("F261113C00012500")).toEqual({
      expiry: "2026-11-13",
      side: "call",
      strike: 12.5,
    })
    expect(parseCboeOptionSymbol("F261113P00013000")?.side).toBe("put")
  })

  it("pulls JSON out of the reader's wrapped page", () => {
    const payload = extractJson('Title:\n\nURL Source: https://example.test\n\nMarkdown Content:\n{"data":{"ok":true}}')
    expect(payload).toEqual({ data: { ok: true } })
  })

  it("builds a board from a delayed chain and daily prices", () => {
    const chain = parseCboeChain({
      data: {
        current_price: 12.68,
        options: [
          { option: "F261106C00012500", bid: 0.25, ask: 0.28, open_interest: 100, iv: 0.4 },
          { option: "F261106C00012500", bid: 0.25, ask: 0.28, open_interest: 10, iv: 0.4 },
          { option: "F261106P00013000", bid: 0.34, ask: 0.38, open_interest: 80, iv: 0.42 },
          { option: "F261104C00012500", bid: 0.2, ask: 0.3, open_interest: 50, iv: 0.4 },
          { option: "F261113C00020000", bid: 0, ask: 0.1, open_interest: 5, iv: 0.5 },
        ],
      },
    })
    expect(chain.price).toBe(12.68)
    const chart = parseYahooChart({
      chart: {
        result: [
          {
            meta: { regularMarketPrice: 12.67, shortName: "Ford" },
            timestamp: closes.map((_, index) => index),
            indicators: { quote: [{ close: closes }] },
          },
        ],
      },
    })
    const board = buildLookupBoard({
      ticker: "F",
      company: chart.name,
      price: chain.price ?? 0,
      closes: chart.closes,
      contracts: chain.contracts,
      today: "2026-11-05",
    })
    expect(board?.company).toBe("Ford")
    expect(board?.fresh).toBe(true)
    expect(board?.hv20).toBeCloseTo(0.7536, 3)
    expect(board?.earningsDate).toBeNull()
    expect(board?.expirations.map((row) => row.expiry)).toEqual(["2026-11-06"])
    expect(board?.expirations[0].calls).toHaveLength(1)
    expect(board?.expirations[0].calls[0].oi).toBe(100)
    expect(board?.expirations[0].puts[0].strike).toBe(13)
    expect(realizedVol(closes, 60)).toBeNull()
    expect(percentileBelow([0.2, 0.3], 0.4)).toBeNull()
    expect(percentileBelow(Array.from({ length: 40 }, () => 0.2), 0.5)).toBe(100)
  })
})

describe("lookupTicker", () => {
  it("asks the reader for the chain and the daily prices", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      expect(url.startsWith(readerUrl("https://"))).toBe(true)
      if (url.includes("cdn.cboe.com")) {
        return new Response(
          JSON.stringify({
            data: {
              current_price: 20,
              options: [{ option: "SOFI261218C00020000", bid: 1, ask: 1.1, open_interest: 200, iv: 0.35 }],
            },
          }),
        )
      }
      return new Response(
        'Markdown Content:\n{"chart":{"result":[{"meta":{"regularMarketPrice":20,"shortName":"SoFi"},"timestamp":[1],"indicators":{"quote":[{"close":' +
          JSON.stringify(closes) +
          "}]}}]}}",
      )
    })
    const board = await lookupTicker("sofi", "2026-11-05", fetchImpl as typeof fetch)
    expect(board.ticker).toBe("SOFI")
    expect(board.company).toBe("SoFi")
    expect(board.expirations[0].calls[0].strike).toBe(20)
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })

  it("says when the reader does not answer", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("offline")
    })
    await expect(lookupTicker("F", "2026-11-05", fetchImpl as typeof fetch)).rejects.toThrow(/free reader/i)
  })

  it("rejects a ticker that is not a stock symbol", async () => {
    const fetchImpl = vi.fn()
    await expect(lookupTicker("hello there", "2026-11-05", fetchImpl as typeof fetch)).rejects.toThrow(/US ticker/i)
    expect(fetchImpl).not.toHaveBeenCalled()
  })
})
