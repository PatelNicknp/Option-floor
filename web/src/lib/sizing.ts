/** Match the Python job: spend band, and never more than 10% of the account. */
export function sizeTrade(mid: number, account: number, minSpend: number, maxSpend: number): number | null {
  if (mid <= 0 || account <= 0 || maxSpend <= 0) return null
  const cost = mid * 100
  const cap = Math.min(maxSpend, account * 0.1)
  let floor = minSpend
  if (cap <= 0) return null
  if (floor > cap) floor = cap
  if (cost > cap + 1e-9) return null
  const target = (floor + cap) / 2
  let best: number | null = null
  let bestDist: number | null = null
  let contracts = 1
  while (contracts <= 20 && contracts * cost <= cap + 1e-6) {
    const spend = contracts * cost
    if (spend + 1e-9 >= floor) {
      const dist = Math.abs(spend - target)
      if (bestDist === null || dist < bestDist - 1e-9) {
        bestDist = dist
        best = contracts
      }
    }
    contracts += 1
  }
  return best
}
