/** Black-Scholes greeks from a free quote. No network and no dividend. */

export const RISK_FREE_RATE = 0.04

export type GreekSide = "call" | "put"

export type GreekInput = {
  spot: number
  strike: number
  iv: number
  dte: number
  side: GreekSide
  rate?: number
}

export type Greeks = {
  delta: number
  gamma: number
  /** Dollars per contract per day. Negative means the contract loses value as time passes. */
  thetaPerDay: number
  /** Positive dollars lost per contract per day. Zero when time is not a cost. */
  dollarsLostPerDay: number
  /** Dollars per contract if implied volatility moves by 1 point (0.01). */
  vegaPerPoint: number
  deltaLine: string
  gammaLine: string
  thetaLine: string
  vegaLine: string
  warnings: string[]
}

export function blackScholesGreeks(input: GreekInput): Greeks | null {
  const rate = input.rate ?? RISK_FREE_RATE
  if (!(input.spot > 0) || !(input.strike > 0) || !(input.iv > 0) || !(input.dte >= 1)) return null
  const years = input.dte / 365
  const root = Math.sqrt(years)
  const vol = input.iv
  const d1 = (Math.log(input.spot / input.strike) + (rate + 0.5 * vol * vol) * years) / (vol * root)
  const d2 = d1 - vol * root
  const density = normalPdf(d1)
  const discount = Math.exp(-rate * years)
  const call = input.side === "call"
  const delta = call ? normalCdf(d1) : normalCdf(d1) - 1
  const gamma = density / (input.spot * vol * root)
  const vega = input.spot * density * root
  const thetaPerYear = call
    ? -(input.spot * density * vol) / (2 * root) - rate * input.strike * discount * normalCdf(d2)
    : -(input.spot * density * vol) / (2 * root) + rate * input.strike * discount * normalCdf(-d2)
  const thetaPerDay = (thetaPerYear / 365) * 100
  const dollarsLostPerDay = Math.max(0, -thetaPerDay)
  const vegaPerPoint = vega * 0.01 * 100
  return {
    delta,
    gamma,
    thetaPerDay,
    dollarsLostPerDay,
    vegaPerPoint,
    deltaLine: deltaLine(delta),
    gammaLine: gammaLine(gamma),
    thetaLine: thetaLine(dollarsLostPerDay, thetaPerDay),
    vegaLine: vegaLine(vegaPerPoint, vol),
    warnings: [],
  }
}

export function deltaLine(delta: number): string {
  const chance = Math.round(Math.abs(delta) * 100)
  return `Delta is ${delta.toFixed(2)}. A rough chance of finishing in the money is about ${chance}%.`
}

export function gammaLine(gamma: number): string {
  const shown = formatGamma(gamma)
  return `Gamma is ${shown}. If the stock moves $1, delta changes by about ${shown}.`
}

export function thetaLine(dollarsLostPerDay: number, thetaPerDay: number): string {
  if (thetaPerDay > 0.005) {
    return `Theta adds about ${money(thetaPerDay)} per day per contract if the stock sits still.`
  }
  return `Theta is about ${money(dollarsLostPerDay)} lost per day per contract if the stock sits still.`
}

export function vegaLine(vegaPerPoint: number, iv: number): string {
  const now = Math.round(iv * 100)
  return `Vega is about ${money(vegaPerPoint)} per IV point. If the expected yearly swing moves by 1 point, from ${now}% to ${now + 1}%, the contract changes by about ${money(vegaPerPoint)}.`
}

function formatGamma(gamma: number): string {
  return gamma >= 0.1 ? gamma.toFixed(2) : gamma.toFixed(3)
}

function money(value: number): string {
  const amount = Math.abs(value)
  if (amount >= 100) return `$${Math.round(amount)}`
  if (amount >= 10) return `$${amount.toFixed(1)}`
  return `$${amount.toFixed(2)}`
}

/** Abramowitz and Stegun approximation of the normal curve. */
function normalCdf(x: number): number {
  return 0.5 * (1 + erf(x / Math.SQRT2))
}

function erf(x: number): number {
  const sign = x < 0 ? -1 : 1
  const ax = Math.abs(x)
  const a1 = 0.254829592
  const a2 = -0.284496736
  const a3 = 1.421413741
  const a4 = -1.453152027
  const a5 = 1.061405429
  const p = 0.3275911
  const t = 1 / (1 + p * ax)
  const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-ax * ax)
  return sign * y
}

function normalPdf(x: number): number {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI)
}
