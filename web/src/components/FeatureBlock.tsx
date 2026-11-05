import { useState, type ReactNode } from "react"
import { Button } from "./ui/button"
import { Switch } from "./ui/switch"

type Props = {
  id: string
  kicker?: string
  title: string
  description: string
  enabled: boolean
  onToggle: (next: boolean) => void
  settings?: ReactNode
  help: ReactNode
  children?: ReactNode
}

export function FeatureBlock({ id, kicker, title, description, enabled, onToggle, settings, help, children }: Props) {
  const [showSettings, setShowSettings] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  return (
    <section id={id} className="border-t border-line py-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          {kicker ? <p className="text-xs font-medium uppercase tracking-[0.16em] text-copper">{kicker}</p> : null}
          <h2 className="mt-1 text-3xl text-ink">{title}</h2>
        </div>
        <label className="flex min-h-11 shrink-0 items-center gap-3 text-sm font-medium">
          <span className="text-muted">{enabled ? "On" : "Off"}</span>
          <Switch checked={enabled} onCheckedChange={onToggle} aria-label={`${title} ${enabled ? "on" : "off"}`} />
        </label>
      </div>
      <p className="mt-3 max-w-3xl text-base leading-relaxed text-ink">{description}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="ghost" aria-expanded={showSettings} onClick={() => setShowSettings((open) => !open)}>
          {showSettings ? "Hide settings" : "Settings"}
        </Button>
        <Button variant="ghost" aria-expanded={showHelp} onClick={() => setShowHelp((open) => !open)}>
          {showHelp ? "Hide help" : "Help"}
        </Button>
      </div>
      {showSettings ? <div className="mt-3 rounded-lg border border-line bg-card p-4">{settings ?? <p className="text-sm text-muted">Nothing to change here.</p>}</div> : null}
      {showHelp ? <div className="mt-3 rounded-lg border border-dashed border-line bg-card/70 p-4 text-sm leading-relaxed text-ink">{help}</div> : null}
      <div className="mt-6">
        {enabled ? children : <p className="text-sm text-muted">This part is off. Turn it on to see it.</p>}
      </div>
    </section>
  )
}
