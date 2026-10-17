import { useState } from 'react'
import { api } from '@/api/client'
import { Button, Input } from '@/components/ui'
import { Field } from '@/components/shared/Field'
import type { Suggestion } from '@/types/directory'

export const toList = (text: string): string[] => [...new Set(text.split(/[\n,]/).map((s) => s.trim()).filter(Boolean))]
export const fromList = (items: string[]): string => items.join(', ')

const SOURCE_NAME: Record<string, string> = { slack: 'Slack', jira: 'Jira', gmail: 'Gmail', confluence: 'Confluence' }

/** A comma-separated list, with the option to pick from what the connected source actually has. */
export function ListField({
  label,
  hint,
  value,
  onChange,
  source,
}: {
  label: string
  hint?: string
  value: string
  onChange: (next: string) => void
  /** When set, a "Browse" button lists what exists in that source. */
  source?: 'slack' | 'jira' | 'gmail' | 'confluence'
}) {
  const [options, setOptions] = useState<Suggestion[] | undefined>(undefined)
  const [loading, setLoading] = useState(false)
  const [problem, setProblem] = useState<string | undefined>(undefined)

  const browse = async () => {
    if (!source) return
    setLoading(true)
    setProblem(undefined)
    try {
      const res = await api.getSuggestions(source)
      if (res.status === 'ok') setOptions(res.options)
      else setProblem(res.status === 'not_connected' ? `${SOURCE_NAME[source]} is not connected.` : `${SOURCE_NAME[source]} could not be read.`)
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'The list could not be loaded.')
    } finally {
      setLoading(false)
    }
  }

  const chosen = new Set(toList(value))
  const toggle = (id: string) => {
    const next = new Set(chosen)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(fromList([...next]))
  }

  return (
    <div className="flex flex-col gap-2">
      <Field label={label} hint={hint}>
        <Input value={value} onChange={(e) => onChange(e.target.value)} />
      </Field>
      {source ? (
        <div className="flex flex-col gap-2">
          <div>
            <Button type="button" size="sm" variant="outline" disabled={loading} onClick={() => void browse()}>
              {loading ? 'Loading…' : `Browse ${SOURCE_NAME[source]}`}
            </Button>
          </div>
          {problem ? <p className="text-caption text-ink-muted">{problem}</p> : null}
          {options ? (
            options.length === 0 ? (
              <p className="text-caption text-ink-muted">Nothing to pick from here.</p>
            ) : (
              <ul className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto" aria-label={`${SOURCE_NAME[source]} options`}>
                {options.map((o) => (
                  <li key={o.id}>
                    <button
                      type="button"
                      aria-pressed={chosen.has(o.id)}
                      onClick={() => toggle(o.id)}
                      className={`border px-2 py-1 text-caption ${chosen.has(o.id) ? 'border-primary bg-primary/10 text-ink' : 'border-line bg-surface text-ink hover:bg-surface-muted'}`}
                    >
                      {o.label}
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
