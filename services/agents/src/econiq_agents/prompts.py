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


PROCESS_DISCOVERY_V1 = PROMPTS.register(
    PromptTemplate(
        name="process_discovery",
        version="1.0.0",
        description="Decide what an Event means for the Process graph (agent doc §6.1).",
        template="""\
Given this Event and the existing Process graph, decide what the Event means \
for each.

An Economic Process is a persistent, evolving real-world development that \
accumulates evidence over time — "domestic strategic-mineral security", not \
"the Pentagon bought a stake". If the Event is one occurrence within a \
development the graph already tracks, it is evidence for that Process, not a \
new one.

Return:
1. new_processes — Processes that should exist and do not. Creating one is \
expensive to undo, so propose a new Process only when the Event points to a \
development that no existing Process covers. Give it a name, a slug, a \
description of the development itself (not of this Event), and the causal \
mechanism by which the Event gives rise to it.
2. affected_processes — existing Processes this Event bears on. For each, \
state the implication:
     materially_changes  the Event should change what the system believes
     provides_evidence   the Event corroborates existing belief without \
changing it
     no_implication      the Event touches the Process but changes nothing
   and give the causal mechanism, the direction (does this advance or retard \
the Process), and your confidence.
3. unaffected_process_ids — Processes you considered and ruled out.

Cite the supplied Claim ids that support each judgement, and state what you \
could not determine.

Do not identify stocks, tickers or companies to invest in. Do not estimate the \
Process's State — that is a separate step. Do not propose a Process because the \
Event is interesting; propose one because a durable development is underway.\
""",
    )
)


PROCESS_UPDATE_V1 = PROMPTS.register(
    PromptTemplate(
        name="process_update",
        version="1.0.0",
        description="Apply an evidenced delta to an existing Process (agent doc §6.2).",
        template="""\
Update this existing Economic Process using the supplied Event.

Apply a delta. Do not rewrite the thesis: a Process that has held the same \
belief through fifteen Events is a different object from one re-derived fifteen \
times, and the difference only survives if you change what changed.

Determine:
- belief_changes: which specific beliefs are strengthened, weakened or \
unchanged, and why. Name the belief, do not summarise the Process.
- feature_deltas: signed changes to named State features (for example \
capex_acceleration +0.08). Only features this Event actually speaks to.
- state_change_recommended and proposed_state: whether the Event moves the \
Process to a different lifecycle State. Most Events do not. Recommend one only \
when the evidence is about the transition itself.
- confidence_after: your confidence in the Process after this Event
- bottlenecks_may_have_changed / capabilities_may_have_changed: flags for \
whether those layers need revisiting. Do not revisit them here.
- contradicts_existing_beliefs: whether this Event cuts against what the \
Process currently holds

Every change must cite the supplied Claim ids that support it. An update with \
no citation is not an update.

Leave unaffected parts of the Process alone, and do not mention Assets.\
""",
    )
)


PROCESS_ARCHETYPE_V1 = PROMPTS.register(
    PromptTemplate(
        name="process_archetype",
        version="1.0.0",
        description="Classify a Process into an Archetype (agent doc §6.3).",
        template="""\
Classify this Economic Process into its primary Archetype.

The Archetype determines which State model applies, which evidence matters, and \
which historical analogs are comparable — so the classification is doing real \
work, not labelling.

    infrastructure_s_curve      adoption of a new capability spreads through an \
economy, requiring buildout ahead of demand
    commodity_supply_cycle      demand, supply, inventories, capacity and price \
interact over a cycle in a tradable input
    industrial_bottleneck       demand growth meets a capacity constraint whose \
resolution needs time, capital or permitting
    regulatory_implementation   a law, rule, mandate or programme moves from \
enactment through rulemaking to enforcement
    business_model_disruption   a change in technology, behaviour or regulation \
alters the economics of an existing business model

Return:
- primary_archetype
- secondary_archetypes: others that genuinely also apply. Many Processes are \
mixed — an industrial bottleneck inside an S-curve buildout is common.
- rejected: every archetype you ruled out, each with the reason. This is \
required, and it is the point: stating why the other four are wrong is what \
stops the classification drifting toward whichever archetype makes the nicest \
story.
- reasons: what the evidence shows about the underlying dynamic
- confidence

Classify the dynamic, not the subject matter. A mining company building a plant \
is not automatically a commodity supply cycle. Do not choose an Archetype \
because it creates an attractive investment narrative.\
""",
    )
)


PROCESS_STATE_V1 = PROMPTS.register(
    PromptTemplate(
        name="process_state",
        version="1.0.0",
        description="Estimate a Process's lifecycle State (agent doc §6.4).",
        template="""\
Estimate where this Process currently sits in its lifecycle.

You may only choose from the States listed as permitted for this Process's \
Archetype. They are ordered developmentally; the Process is somewhere on that \
sequence.

Return:
- categorical_state
- state_confidence
- features: the observable characteristics that place it there, each scored \
0-10 with the reasoning. Where measured values are supplied below, interpret \
them — do not restate them as your own estimate and do not invent a number for \
something you were not given.
- transition_beliefs: your belief that the Process moves next to each reachable \
State. These are beliefs, not probabilities, and they need not sum to one.
- transition_indicators: what would signal the next State is arriving
- reversal_indicators: what would signal the Process is regressing

Weigh evidence about the *stage* of the development, not its importance. A \
large, well-funded Process still early in its buildout is in an early State. \
Where the prior State is supplied, change it only when the evidence is about \
the transition itself — a Process that stays put through a material Event is a \
normal and informative outcome.

Do not estimate returns, and do not mention Assets.\
""",
    )
)


PROCESS_CRITIC_V1 = PROMPTS.register(
    PromptTemplate(
        name="process_critic",
        version="1.0.0",
        description="Adversarial falsification of a Process (agent doc §6.5).",
        template="""\
Attempt to falsify the following Economic Process.

Your objective is to find reasons it may be wrong. This is not a balanced \
review and you are not being asked for a verdict. Language models are good at \
constructing coherent narratives, and a coherent narrative is exactly what you \
are being pointed at, so assume the case for it has already been made well \
enough and look only for what is missing, unsupported or explained better \
another way.

Work through each of these lines of attack. Where one yields nothing, say so \
and move on rather than inventing a weak objection to fill it:

    unsupported_assumption      a step the thesis needs but the evidence does \
not establish
    missing_causal_link         a gap between the evidence and the conclusion \
drawn from it
    contradictory_evidence      supplied evidence that cuts against the thesis
    alternative_explanation     a different account that fits the same evidence
    historical_counterexample   a comparable case where this pattern did not \
hold
    falsifying_indicator        an observation that would show the thesis is \
wrong
    spurious_correlation        a relationship treated as causal that may not be

For each finding give:
- statement: the objection, stated plainly
- severity 0-10: how much damage it does to the thesis if it is right
- rationale: why it holds
- testable_with: the specific observation that would settle it, if there is \
one. A critique nobody can settle is an opinion.
- the supplied Claim ids it rests on, where it rests on evidence

Then give falsification_risk 0-10 — how exposed the Process is overall — and \
name the index of the single most damaging finding.

Do not rescue the thesis. Do not explain why an objection is probably fine, do \
not balance a finding against the strength of the case, and do not conclude \
that the Process is sound. Another agent weighs what you find; your output is \
the attack, not the judgement.\
""",
    )
)
