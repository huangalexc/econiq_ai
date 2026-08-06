"""Prompts for the Document and Evidence agents (agent doc §4).

Every prompt here is registered with a version. The shared epistemic preamble
(``econiq_llm.prompts.SHARED_AGENT_PREAMBLE``) is appended automatically by the
``Agent`` base class, so these say only what is specific to the task.

Prompt text follows the sample prompts in the agent doc closely — including the
prohibitions, which are the parts that keep an agent inside its layer.
"""

from __future__ import annotations

from econiq_llm import PROMPTS, PromptTemplate

DOCUMENT_CLASSIFIER_V1 = PROMPTS.register(
    PromptTemplate(
        name="document_classifier",
        version="1.0.0",
        description="Route a document by type and information mode (agent doc §4.1).",
        template="""\
Classify this document so the system can route it to the right extraction \
pipeline.

Return:
- document_type: what kind of document this is
- source_type: the kind of publisher (wire_service, regulator, issuer, \
research_provider, statistical_agency, other)
- primary_information_mode: textual, quantitative, or mixed. Choose \
quantitative when the substance is figures in tables or statements, textual \
when the substance is prose, mixed when both carry meaning.
- named_entities: the companies, governments, commodities and technologies the \
document is about
- likely_event_types: the kinds of real-world occurrence this document might \
describe
- extraction_strategy: one sentence on how this document should be processed
- confidence

Judge what the document IS, not what it implies. Do not infer investment \
implications, and do not speculate about market impact.\
""",
    )
)


CLAIM_EXTRACTION_V1 = PROMPTS.register(
    PromptTemplate(
        name="claim_extraction",
        version="1.0.0",
        description="Extract atomic factual Claims with exact source spans (agent doc §4.2).",
        template="""\
Extract atomic factual Claims from this document.

A Claim is one discrete proposition. Split compound statements: "the government \
acquired a stake and committed to a price floor" is two Claims. Each must stand \
alone well enough that someone reading only the Claim knows what was asserted.

For every Claim provide:
- text: the proposition, stated plainly
- assertion_source: who is asserting it —
    observed_fact       the document reports something as having happened
    reported_statement  the document reports what someone said
    company_forecast    a company's expectation about its own future
    government_forecast a government body's projection
    analyst_opinion     a third party's judgement
    inference           a conclusion the document draws rather than reports
- source_location: quote the exact span you took it from, plus the section \
heading or paragraph number if the document has them. The quote must appear \
verbatim in the document.
- entities: the real-world entities the Claim is about
- stated_at: the date the Claim is about, if the document states one
- attributed_to: who made the statement, if the document attributes it
- extraction_confidence

Extract what the document says. Do not add facts it does not contain, do not \
resolve tickers or identifiers, do not merge separate statements into a \
summary, and do not infer investment implications. Background and context that \
assert nothing new are not Claims — omit them.

If the document contains no factual claims, return an empty list and abstain \
with a reason.\
""",
    )
)


EVENT_RESOLUTION_V1 = PROMPTS.register(
    PromptTemplate(
        name="event_resolution",
        version="1.0.0",
        description="Cluster Claims into canonical Events (agent doc §5.1).",
        template="""\
Determine which of these Claims refer to the same underlying real-world Event.

An Event is one discrete occurrence. Two Claims belong together when they \
describe the same occurrence, even if they word it differently, disagree on \
detail, or come from different publishers. They belong apart when they describe \
different occurrences, however related — an acquisition and the share-price \
reaction to it are two Events.

For each cluster return:
- canonical_title and description: what happened, stated once, neutrally
- event_type
- timestamp: when the occurrence happened, not when it was reported
- supporting_claim_ids: every Claim in the cluster
- distinct_publishers: the publishers behind the cluster. When several outlets \
carry the same wire story, name the originating publisher once — do not list \
each outlet that reprinted it.
- contradictions: points on which the Claims disagree
- entities
- confidence: your belief the occurrence is real as described
- merge_into_event_id: set when this cluster is new evidence for one of the \
known Events supplied below, rather than a new Event

Claims that describe no discrete occurrence — background, context, standing \
policy — belong in unassigned_claim_ids, not in a cluster.

Do not count repeated reporting of the same source as independent evidence. Do \
not merge two occurrences because they involve the same company. Do not infer \
consequences, and do not mention investment implications.\
""",
    )
)


EVENT_SIGNIFICANCE_V1 = PROMPTS.register(
    PromptTemplate(
        name="event_significance",
        version="1.0.0",
        description="Decide whether an Event warrants propagation (agent doc §5.2).",
        template="""\
Evaluate whether this Event should trigger an update to the Process graph.

Most Events should not. Propagation is expensive and a graph that reacts to \
every headline is noise, so the bar is whether this changes what a careful \
analyst would believe.

Score each dimension 0-10, with the evidence for the score in its rationale:
- novelty: how much this changes what was already known. Confirmation of \
something already reported scores low even when the underlying fact is large.
- economic_materiality: the economic significance if true
- credibility: how much the sourcing supports believing it
- persistence_potential: whether this is a durable change or a transient one
- process_relevance: how directly this bears on an economic Process
- asset_relevance: whether specific Assets are implicated. Say only that they \
are implicated — do not predict direction, magnitude or returns.

Then set should_trigger_update and explain the decision in trigger_rationale.

Judge the Event as given. Do not speculate about follow-on events, and do not \
recommend any action.\
""",
    )
)
