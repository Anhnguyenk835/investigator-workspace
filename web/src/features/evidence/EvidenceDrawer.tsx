import { Button, Drawer, EmptyState } from '@/components/ui'
import { useOpenEvidence } from '@/features/evidence/EvidenceCitation'
import { EvidenceDetail } from '@/features/evidence/EvidenceDetail'
import { useEvidenceIndex } from '@/features/evidence/EvidenceIndex'

/** Global drawer driven by the ?evidence=<id> query parameter, so links are shareable. */
export function EvidenceDrawerHost() {
  const { openId, close } = useOpenEvidence()
  return openId ? <EvidenceDrawerBody key={openId} id={openId} onClose={close} /> : null
}

function EvidenceDrawerBody({ id, onClose }: { id: string; onClose: () => void }) {
  const index = useEvidenceIndex()
  const record = index.get(id)

  return (
    <Drawer
      open
      onClose={onClose}
      title="Evidence"
      description="Check the claim against the original record."
      footer={
        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
      }
    >
      {record && index.bundle ? <EvidenceDetail record={record} bundle={index.bundle} /> : null}
      {!record && index.ready ? (
        <EmptyState
          icon="alert"
          title="Record not found"
          body={`This investigation holds no evidence record with ID ${id}. The citation may point to a record that was not kept.`}
        />
      ) : null}
      {!index.ready ? (
        <EmptyState icon="investigations" title="Open an investigation first" body="Evidence belongs to the investigation that collected it. Open that investigation to read this record." />
      ) : null}
    </Drawer>
  )
}
