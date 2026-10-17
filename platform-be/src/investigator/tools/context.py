"""Who is asking and what the case may touch. Built by the backend, never by the model."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from investigator.directory.models import Directory, SourceFilter


class CaseScope(BaseModel):
    """Identifiers of the case. A record that names a different customer or
    project is dropped, whatever a connector returned."""

    customer_id: str | None = None
    project_id: str | None = None


class AccessContext(BaseModel):
    model_config = {"frozen": True}

    user_id: str
    # Reads the stored fictional corpus instead of the live sources.
    demo: bool = False
    # Sources this user may read. Empty means nothing is readable (fail closed).
    permitted_sources: frozenset[str] = Field(default_factory=frozenset)
    # Sources the investigation was narrowed to; None means all permitted.
    source_scope: frozenset[str] | None = None
    # The case's search window; model-requested dates are clamped into it.
    window_from: date | None = None
    window_to: date | None = None
    scope: CaseScope = Field(default_factory=CaseScope)
    # Customers, projects and people, so a case can be narrowed and authors identified.
    directory: Directory | None = None
    # What the person chose to search in each source (channels, projects, labels, spaces).
    # An empty filter is a decision too: search all of that source.
    source_filters: dict[str, SourceFilter] = Field(default_factory=dict)

    def filter_for(self, source: str) -> SourceFilter | None:
        """How this case is narrowed in a source: what the person chose, else what the
        directory maps. None means the source is searched whole."""
        chosen = self.source_filters.get(source)
        if chosen is not None:
            return None if chosen.is_empty() else chosen
        if self.directory is None:
            return None
        return self.directory.filter_for(
            source, self.scope.customer_id, self.scope.project_id
        )
