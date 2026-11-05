export function premium(value: number): string {
  return `$${value.toFixed(2)}`
}

export function dollars(value: number): string {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  })
}

export function longDate(iso: string | null | undefined): string {
  if (!iso) return "Unknown date"
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number)
  if (!year || !month || !day) return iso
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  })
}

export function ranAt(iso: string | null | undefined): string {
  if (!iso) return "Not finished yet"
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
    timeZoneName: "short",
  })
}

export function dayMove(pct: number | null | undefined): string | null {
  if (pct == null || Number.isNaN(pct)) return null
  const word = pct > 0.05 ? "Up" : pct < -0.05 ? "Down" : "About flat"
  return `${word} ${Math.abs(pct).toFixed(1)}% on the last daily bar`
}

export function takeProfitPlain(mid: number, contracts: number): string {
  const doubled = mid * 2
  if (contracts >= 2) {
    const half = Math.floor(contracts / 2)
    const back = half * doubled * 100
    return `You have ${contracts} contracts, so sell half (${half}) if the option doubles to about ${premium(doubled)}. That half returns about ${dollars(back)}. Keep the rest until the stop or the last exit date.`
  }
  return `You only have 1 contract, and you cannot sell half of one contract. Sell the whole contract if it doubles to about ${premium(doubled)} (about ${dollars(doubled * 100)} back).`
}

export function stopPlain(mid: number, contracts: number): string {
  const price = mid * 0.5
  const left = price * 100 * contracts
  return `Sell everything if the option loses half its value, near ${premium(price)} (about ${dollars(left)} left).`
}

export function voteWord(vote: string): string {
  if (vote === "yes") return "Yes"
  if (vote === "no") return "No"
  return "Pass"
}

export function outcomePlain(outcome: string): string {
  if (outcome === "target") return "Hit the double"
  if (outcome === "stop") return "Hit the half-loss stop"
  if (outcome === "time") return "Closed on the last exit date"
  if (outcome === "expiry") return "Closed at expiration"
  return outcome || "Closed"
}

export function payoffRows(
  side: string,
  strike: number,
  premiumPrice: number,
  contracts: number,
  spot: number,
  moves: number[],
) {
  const cost = premiumPrice * 100 * contracts
  return moves.map((pct) => {
    const future = spot * (1 + pct / 100)
    const intrinsic = side === "call" ? Math.max(0, future - strike) : Math.max(0, strike - future)
    const value = intrinsic * 100 * contracts
    return {
      pct,
      stock: Math.round(future * 100) / 100,
      value: Math.round(value * 100) / 100,
      pnl: Math.round((value - cost) * 100) / 100,
    }
  })
}

export function daySpan(iso: string): number {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number)
  const target = Date.UTC(year, month - 1, day)
  const now = new Date()
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  return Math.round((target - today) / 86400000)
}
