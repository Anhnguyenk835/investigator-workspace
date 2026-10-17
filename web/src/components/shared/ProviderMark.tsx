import { providerMeta } from '@/lib/providers'
import { cn } from '@/lib/cn'
import type { SourceProvider } from '@/types/investigator'
import confluence from '@/assets/providers/confluence.svg'
import gmail from '@/assets/providers/gmail.svg'
import googleDrive from '@/assets/providers/google-drive.svg'
import jira from '@/assets/providers/jira.svg'
import linear from '@/assets/providers/linear.svg'
import notion from '@/assets/providers/notion.svg'
import outlook from '@/assets/providers/outlook.svg'
import salesforce from '@/assets/providers/salesforce.svg'
import slack from '@/assets/providers/slack.svg'
import teams from '@/assets/providers/teams.svg'

export const providerLogos: Record<SourceProvider, string> = {
  gmail,
  outlook,
  slack,
  teams,
  jira,
  linear,
  confluence,
  notion,
  google_drive: googleDrive,
  salesforce,
}

/** Provider logo on a quiet tile. Decorative: the provider name is always shown beside it. */
export function ProviderMark({ provider, className }: { provider: SourceProvider; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn('inline-flex size-7 shrink-0 items-center justify-center border border-line-subtle bg-surface p-1', className)}
    >
      <img src={providerLogos[provider]} alt="" className="size-full object-contain" draggable={false} />
    </span>
  )
}

export function ProviderName({ provider, className }: { provider: SourceProvider; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <ProviderMark provider={provider} className="size-6" />
      <span>{providerMeta[provider].name}</span>
    </span>
  )
}
