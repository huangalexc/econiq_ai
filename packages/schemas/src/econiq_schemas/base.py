"""Base contracts for agent I/O.

Agents communicate through typed objects, never free prose (agent doc §14).
Two conventions are enforced here and relied on everywhere else:

1. **Every agent input carries an ``as_of`` timestamp.** An agent may only reason
   about information available at that moment. Passing the as-of date
   explicitly, rather than letting agents read "now", is what makes historical
   replay honest and leakage detectable (ontology §33; issue #39).
2. **Agents propose; code persists.** Outputs are ``Proposed*`` objects without
   identity — an agent never mints an id, never writes a row and never asserts a
   resolved identifier. Deterministic code validates a proposal and only then
   creates the ontology object (agent doc §2.3; tech rec §33).
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from econiq_ontology import Confidence, EvidenceRef, OntologyModel
from pydantic import Field, model_validator

#: Version of the agent I/O contract. Recorded on every agent run so a stored
#: output can be re-read with the schema that produced it (agent doc §21).
AGENT_SCHEMA_VERSION = "1.0.0"


class AgentIO(OntologyModel):
    schema_version: str = Field(default=AGENT_SCHEMA_VERSION)


class AgentInput(AgentIO):
    """Base for every agent input."""

    as_of: datetime = Field(
        description=(
            "Point-in-time cut-off. The agent may use no information published "
            "after this instant (ontology §33)."
        )
    )


class AgentOutput(AgentIO):
    """Base for every agent output.

    Abstention is a first-class outcome. An agent that cannot answer must say so
    rather than produce a confident-looking guess; the orchestrator treats
    abstention as a normal result, not an error.
    """

    abstained: bool = False
    abstention_reason: str | None = None
    uncertainty_notes: list[str] = Field(
        default_factory=list,
        description="Explicit statements of what the agent could not determine.",
    )

    @model_validator(mode="after")
    def _abstention_is_explained(self) -> Self:
        if self.abstained and not self.abstention_reason:
            raise ValueError("an abstaining agent must give a reason")
        if not self.abstained and self.abstention_reason:
            raise ValueError("abstention_reason set without abstaining")
        return self


class Cited(AgentIO):
    """Mixin for any proposal that must cite its support.

    ``supporting_claims`` are Claim ids the agent was shown. Requiring at least
    one is the mechanical half of "every material statement has provenance"
    (agent doc §2.4); the semantic half — that the claim actually supports the
    statement — is checked by the evaluation harness (issue #16).
    """

    supporting_claim_ids: list[str] = Field(
        default_factory=list,
        description="Ids of Claims, drawn from the input, that support this proposal.",
    )
    contradicting_claim_ids: list[str] = Field(
        default_factory=list,
        description="Ids of Claims from the input that count against it.",
    )
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ScoredJudgement(AgentIO):
    """A single scored judgement with its reasoning made explicit."""

    value: float = Field(ge=0.0, le=10.0)
    confidence: Confidence
    rationale: str = Field(min_length=1)
