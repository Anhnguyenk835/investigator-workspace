import { Badge, type BadgeProps } from '@/components/ui/Badge'
import { Icon, type IconName } from '@/components/ui/Icon'
import type {
  CommitmentStatus,
  ConnectorStatus,
  CoverageStatus,
  FindingStatus,
  InvestigationStatus,
  SupportStatus,
} from '@/types/investigator'

type Tone = NonNullable<BadgeProps['tone']>
interface Def {
  label: string
  tone: Tone
  icon: IconName
}

export const investigationStatus: Record<InvestigationStatus, Def> = {
  queued: { label: 'Queued', tone: 'muted', icon: 'clock' },
  investigating: { label: 'Investigating', tone: 'infoSoft', icon: 'refresh' },
  needs_review: { label: 'Needs review', tone: 'warningSoft', icon: 'alert' },
  blocked: { label: 'Blocked', tone: 'dangerSoft', icon: 'ban' },
  resolved: { label: 'Resolved', tone: 'successSoft', icon: 'circleCheck' },
  failed: { label: 'Failed', tone: 'dangerSoft', icon: 'x' },
}

export const findingStatus: Record<FindingStatus, Def> = {
  verified: { label: 'Verified', tone: 'successSoft', icon: 'circleCheck' },
  needs_verification: { label: 'Needs verification', tone: 'warningSoft', icon: 'alert' },
  conflicting: { label: 'Conflicting evidence', tone: 'dangerSoft', icon: 'x' },
  unknown: { label: 'Unknown', tone: 'muted', icon: 'help' },
}

export const commitmentStatus: Record<CommitmentStatus, Def> = {
  confirmed: { label: 'Confirmed', tone: 'infoSoft', icon: 'check' },
  fulfilled: { label: 'Fulfilled', tone: 'successSoft', icon: 'circleCheck' },
  at_risk: { label: 'At risk', tone: 'warningSoft', icon: 'alert' },
  overdue: { label: 'Overdue', tone: 'dangerSoft', icon: 'clock' },
  unverified: { label: 'Unverified', tone: 'muted', icon: 'help' },
}

export const coverageStatus: Record<CoverageStatus, Def> = {
  searched: { label: 'Searched successfully', tone: 'successSoft', icon: 'circleCheck' },
  partial: { label: 'Partially searched', tone: 'warningSoft', icon: 'alert' },
  not_connected: { label: 'Not connected', tone: 'muted', icon: 'minus' },
  permission_denied: { label: 'Permission denied', tone: 'dangerSoft', icon: 'lock' },
  search_failed: { label: 'Search failed', tone: 'dangerSoft', icon: 'x' },
  no_matches: { label: 'No matching records', tone: 'infoSoft', icon: 'search' },
}

export const connectorStatus: Record<ConnectorStatus, Def> = {
  not_connected: { label: 'Not connected', tone: 'muted', icon: 'minus' },
  connected: { label: 'Connected', tone: 'successSoft', icon: 'circleCheck' },
  reauth_required: { label: 'Reconnect needed', tone: 'warningSoft', icon: 'alert' },
  unavailable: { label: 'Not available', tone: 'muted', icon: 'lock' },
}

export const supportStatus: Record<SupportStatus, Def> = {
  supported: { label: 'Backed by its records', tone: 'successSoft', icon: 'circleCheck' },
  partial: { label: 'Only partly backed', tone: 'warningSoft', icon: 'alert' },
  unsupported: { label: 'Not backed by its records', tone: 'dangerSoft', icon: 'x' },
  unchecked: { label: 'Not checked', tone: 'muted', icon: 'help' },
}

export function StatusBadge({ def, className }: { def: Def; className?: string }) {
  return (
    <Badge tone={def.tone} className={className}>
      <Icon name={def.icon} className="size-2.5" />
      {def.label}
    </Badge>
  )
}
