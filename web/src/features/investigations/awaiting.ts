import type { Awaiting } from '@/types/investigator'

/** What a paused investigation is waiting for, in the words shown to people. */
export const awaitingLabel: Record<Awaiting, string> = {
  clarification: 'Waiting for your answer',
  review: 'Waiting for findings review',
  draft_approval: 'Waiting for draft approval',
}
