from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from investigator.agents.investigation.schemas import CaseContext
from investigator.agents.investigation.state import InvestigationState
from investigator.investigations import Awaiting, Investigation, InvestigationRunStatus
from investigator.investigations.models import RESULT_FIELDS


class MemoryStore:
    def __init__(self) -> None:
        self.items: dict[UUID, Investigation] = {}

    def _put(self, inv: Investigation, **changes: object) -> None:
        self.items[inv.id] = inv.model_copy(
            update={"updated_at": datetime.now(UTC), **changes}
        )

    async def create(
        self, question: str, context: CaseContext, owner_id: str | None = None
    ) -> Investigation:
        now = datetime.now(UTC)
        inv = Investigation(
            id=uuid4(),
            question=question,
            status="queued",
            context=context,
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
        )
        self.items[inv.id] = inv
        return inv

    async def get(self, investigation_id: UUID) -> Investigation | None:
        return self.items.get(investigation_id)

    async def list(
        self, limit: int = 50, owner_ids: Sequence[str | None] | None = None
    ) -> list[Investigation]:
        found = [
            i
            for i in self.items.values()
            if owner_ids is None or i.owner_id in owner_ids
        ]
        return sorted(found, key=lambda i: i.created_at, reverse=True)[:limit]

    async def delete_owned(self, owner_id: str) -> int:
        gone = [k for k, v in self.items.items() if v.owner_id == owner_id]
        for k in gone:
            del self.items[k]
        return len(gone)

    async def count_by_owner(self, owner_id: str) -> int:
        return sum(1 for i in self.items.values() if i.owner_id == owner_id)

    async def set_status(
        self, investigation_id: UUID, status: InvestigationRunStatus
    ) -> None:
        self._put(
            self.items[investigation_id], status=status, awaiting=None, pending=None
        )

    async def save_result(
        self,
        investigation_id: UUID,
        state: InvestigationState,
        *,
        status: InvestigationRunStatus,
        awaiting: Awaiting | None = None,
        pending: dict[str, Any] | None = None,
    ) -> None:
        result = {k: getattr(state, k) for k in RESULT_FIELDS}
        self._put(
            self.items[investigation_id],
            status=status,
            awaiting=awaiting,
            pending=pending,
            error=state.error,
            **result,
        )

    async def fail(self, investigation_id: UUID, error: str) -> None:
        self._put(
            self.items[investigation_id],
            status="failed",
            error=error,
            awaiting=None,
            pending=None,
        )

    async def fail_unfinished(self, error: str) -> int:
        return 0

    async def set_owner(self, investigation_id: UUID, owner: str | None) -> None:
        self._put(self.items[investigation_id], owner=owner)

    async def next_run(self, investigation_id: UUID) -> int:
        inv = self.items[investigation_id]
        self._put(
            inv,
            run_no=inv.run_no + 1,
            status="queued",
            awaiting=None,
            pending=None,
            error=None,
        )
        return inv.run_no + 1
