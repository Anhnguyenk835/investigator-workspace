import { Badge, Button, Icon } from '@/components/ui'
import { ProviderMark } from '@/components/shared/ProviderMark'
import { useToast } from '@/components/ui/Toast'
import { useFormat } from '@/hooks/useSettings'
import { copyText, recordTypeLabel } from '@/lib/labels'
import { providerMeta } from '@/lib/providers'
import { safeHref } from '@/lib/url'
import type { EvidenceRecord, InvestigationBundle } from '@/types/investigator'

const SIDE = { customer: 'customer side', internal: 'our team', third_party: 'other party' } as const

export function citationText(r: EvidenceRecord, when: string): string {
  return `${providerMeta[r.provider].name} · ${recordTypeLabel[r.recordType]} · "${r.title}"${r.author ? ` · ${r.author}` : ''} · ${when} · ${r.id}`
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 border-b border-line-subtle py-2 text-caption last:border-b-0">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="min-w-0 break-words text-ink">{children}</dd>
    </div>
  )
}

/** The passages of this record that claims in the investigation rest on. */
function quotesFor(id: string, b: InvestigationBundle): { claim: string; quote: string }[] {
  const out: { claim: string; quote: string }[] = []
  const add = (claim: string, support: { evidenceId: string; quote?: string }[]) => {
    for (const c of support) if (c.evidenceId === id && c.quote) out.push({ claim, quote: c.quote })
  }
  for (const f of b.findings) add(f.claim, f.support)
  for (const c of b.commitments) add(c.statement, c.support)
  for (const t of b.timeline) add(`${t.title}: ${t.description}`, t.support)
  return out
}

/** The excerpt with the cited passages marked. Matching ignores line breaks and case. */
function Highlighted({ text, quotes }: { text: string; quotes: string[] }) {
  const escape = (w: string) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const patterns = quotes.map((q) => q.trim().split(/\s+/).map(escape).join('\\s+')).filter(Boolean)
  if (patterns.length === 0) return <>{text}</>
  const parts = text.split(new RegExp(`(${patterns.join('|')})`, 'gi'))
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="bg-primary/25 text-ink">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  )
}

/** The excerpt in order, with ranges that read as instructions to an AI set apart. */
function WithFlags({ record, quotes }: { record: EvidenceRecord; quotes: string[] }) {
  const spans = [...record.flaggedSpans].sort((a, b) => a.start - b.start)
  if (spans.length === 0) return <Highlighted text={record.excerpt} quotes={quotes} />
  const parts: { text: string; flagged: boolean }[] = []
  let at = 0
  for (const s of spans) {
    if (s.start < at) continue
    if (s.start > at) parts.push({ text: record.excerpt.slice(at, s.start), flagged: false })
    parts.push({ text: record.excerpt.slice(s.start, s.end), flagged: true })
    at = s.end
  }
  if (at < record.excerpt.length) parts.push({ text: record.excerpt.slice(at), flagged: false })
  return (
    <>
      {parts.map((p, i) =>
        p.flagged ? (
          <mark key={i} className="border-b-2 border-warning bg-warning/15 text-ink" title="Reads as instructions to an AI">
            {p.text}
          </mark>
        ) : (
          <Highlighted key={i} text={p.text} quotes={quotes} />
        ),
      )}
    </>
  )
}

/** Where else this record is used in the open investigation. */
function relatedTo(id: string, b: InvestigationBundle) {
  return {
    findings: b.findings.filter((f) => f.supportingEvidenceIds.includes(id) || f.contradictingEvidenceIds.includes(id)),
    events: b.timeline.filter((e) => e.evidenceIds.includes(id)),
    commitments: b.commitments.filter((c) => c.evidenceIds.includes(id) || c.fulfilledByEvidenceIds.includes(id)),
  }
}

export function EvidenceDetail({ record, bundle }: { record: EvidenceRecord; bundle: InvestigationBundle }) {
  const fmt = useFormat()
  const toast = useToast()
  const when = fmt.stamp(record.timestamp, record.timestampPrecision)
  const href = safeHref(record.url)
  const related = relatedTo(record.id, bundle)
  const cited = quotesFor(record.id, bundle)

  const copy = async () => {
    const ok = await copyText(citationText(record, when))
    if (ok) toast.success('Citation copied')
    else toast.error('Could not copy', 'Clipboard access was blocked by the browser.')
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <ProviderMark provider={record.provider} />
        <span className="text-caption font-medium text-ink">{providerMeta[record.provider].name}</span>
        <Badge tone="muted">{recordTypeLabel[record.recordType]}</Badge>
      </div>

      <h3 className="text-heading text-ink">{record.title}</h3>

      {record.trust !== 'normal' ? (
        <section aria-label="Warning" role="note" className="border-l-2 border-warning bg-surface-muted px-3 py-2 text-caption text-ink">
          <p className="text-overline uppercase text-warning">Contains instructions aimed at an AI</p>
          <p className="mt-1">
            {record.trust === 'tainted'
              ? 'The marked text was withheld from the AI when it analysed this record, and findings that rest on it are flagged for review. It is shown here in full.'
              : 'The marked text reads as instructions to an AI. It has not been withheld from the AI in this deployment.'}{' '}
            Do not act on it; read it as part of what the sender wrote.
          </p>
        </section>
      ) : null}

      <section aria-label="Excerpt">
        <p className="mb-1 text-overline uppercase text-ink-muted">Excerpt</p>
        <blockquote className="whitespace-pre-wrap border-l-2 border-primary/50 bg-surface-muted px-4 py-3 text-body text-ink">
          <WithFlags record={record} quotes={cited.map((c) => c.quote)} />
        </blockquote>
        {cited.length > 0 ? <p className="mt-2 text-caption text-ink-muted">Highlighted: the passage{cited.length === 1 ? '' : 's'} this investigation's claims rest on.</p> : null}
        <p className="mt-2 text-caption text-ink-muted">Source text is shown as retrieved and can be cut short. Open the original to read all of it.</p>
      </section>

      <dl>
        <Row label="Author">
          {record.author ?? 'Unknown'}
          {record.authorSide ? <span className="ml-2 text-ink-muted">· {SIDE[record.authorSide]}{record.authorRole ? ` (${record.authorRole})` : ''}</span> : null}
        </Row>
        <Row label="Timestamp">
          {when}
          {record.timestampPrecision !== 'exact' ? (
            <span className="block text-ink-muted">Time of day is not available for this record; none has been assumed.</span>
          ) : null}
        </Row>
        <Row label="Record ID">
          <code className="font-mono">{record.id}</code>
        </Row>
        {record.threadId ? (
          <Row label="Thread">
            <code className="font-mono">{record.threadId}</code>
          </Row>
        ) : null}
      </dl>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={copy}>
          <Icon name="copy" /> Copy citation
        </Button>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex h-control-sm items-center justify-center gap-2 border border-line bg-surface px-3 text-caption font-medium text-ink hover:bg-surface-muted"
          >
            <Icon name="external" /> Open original source
          </a>
        ) : (
          <Button variant="outline" size="sm" disabled title="The source gave no link for this record.">
            <Icon name="external" /> Open original source
          </Button>
        )}
      </div>

      <section aria-label="Used in this investigation" className="flex flex-col gap-4 border-t border-line-subtle pt-4">
        <div>
          <p className="mb-1 text-overline uppercase text-ink-muted">Findings</p>
          {related.findings.length === 0 ? (
            <p className="text-caption text-ink-muted">No finding cites this record.</p>
          ) : (
            <ul className="flex list-disc flex-col gap-1 pl-4 text-caption text-ink">
              {related.findings.map((f) => (
                <li key={f.id}>{f.title}</li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <p className="mb-1 text-overline uppercase text-ink-muted">Timeline events</p>
          {related.events.length === 0 ? (
            <p className="text-caption text-ink-muted">No timeline event uses this record.</p>
          ) : (
            <ul className="flex list-disc flex-col gap-1 pl-4 text-caption text-ink">
              {related.events.map((e) => (
                <li key={e.id}>
                  {e.title} <span className="text-ink-muted">· {fmt.stamp(e.occurredAt, e.precision)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <p className="mb-1 text-overline uppercase text-ink-muted">Commitments</p>
          {related.commitments.length === 0 ? (
            <p className="text-caption text-ink-muted">No commitment cites this record.</p>
          ) : (
            <ul className="flex list-disc flex-col gap-1 pl-4 text-caption text-ink">
              {related.commitments.map((c) => (
                <li key={c.id}>{c.statement}</li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  )
}
