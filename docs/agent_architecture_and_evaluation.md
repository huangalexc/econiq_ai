# Agent Architecture and Evaluation Framework

**Status:** Working design specification\
**Version:** 0.1\
**Purpose:** Define the agents, their placement in the Economic
Process--Asset ontology, responsibilities, example prompts, outputs,
failure modes, and evaluation metrics.

------------------------------------------------------------------------

## 1. Executive Summary

The system should not be implemented as one general-purpose "investment
agent." It should be composed of specialized agents operating at clearly
defined points in the ontology.

The core principle is:

> **Each agent should perform a narrow transformation for which its
> output can be independently evaluated.**

The overall pipeline is:

``` text
DOCUMENT
   ↓
DOCUMENT EXTRACTION
   ↓
CLAIM
   ↓
EVENT
   ↓
ECONOMIC PROCESS
   ↓
PROCESS STATE
   ↓
BOTTLENECK
   ↓
CAPABILITY REQUIREMENT
   ↓
ASSET UNIVERSE
   ↓
ASSET ANALYSIS
   ↓
HISTORICAL ANALOGS
   ↓
EMPIRICAL OUTCOME DISTRIBUTION
   ↓
THESIS / ASSET RANKING
```

The architecture separates:

1.  **Extraction agents** --- turn documents into structured
    observations.
2.  **Inference agents** --- infer Events, Processes, States,
    Bottlenecks, and Capabilities.
3.  **Discovery agents** --- identify relevant Assets.
4.  **Quantitative services** --- measure numerical relationships and
    rank Assets.
5.  **Historical agents** --- retrieve and align precedents.
6.  **Critique agents** --- challenge assumptions and contradictions.
7.  **Synthesis agents** --- produce human-readable explanations.
8.  **Governance agents** --- audit provenance, leakage, and
    calibration.

No single LLM should have authority over the entire chain.

------------------------------------------------------------------------

# 2. Design Principles

## 2.1 Narrow responsibility

An agent should answer one class of question.

Bad:

> "Analyze this article and tell me what stocks will go up."

Better:

> "Extract atomic factual Claims from this document."

Then:

> "Determine whether these Claims constitute a novel Event."

Then:

> "Determine which existing Economic Processes are affected."

------------------------------------------------------------------------

## 2.2 Structured outputs

Agents should generally return typed JSON or equivalent structured
objects rather than prose.

Example:

``` json
{
  "process_id": "proc_ai_infrastructure",
  "state": "infrastructure_expansion",
  "confidence": 0.82,
  "evidence": ["claim_1842", "claim_1851"],
  "state_changes": {
    "capex_acceleration": 0.14,
    "supply_tightness": 0.08
  }
}
```

Prose should normally be generated from the structured state later.

------------------------------------------------------------------------

## 2.3 LLMs propose; deterministic systems verify

Whenever a proposition can be evaluated mechanically, it should be.

Examples:

-   financial arithmetic;
-   historical returns;
-   date ordering;
-   valuation calculations;
-   technical indicators;
-   portfolio weights;
-   entity identifiers.

The LLM should formulate and interpret quantitative questions, while
code performs the calculations.

------------------------------------------------------------------------

## 2.4 Every inference requires provenance

A material statement should be traceable:

``` text
Statement
   ↓
Inference
   ↓
Supporting Claims
   ↓
Events
   ↓
Documents / datasets
```

------------------------------------------------------------------------

## 2.5 Uncertainty must be explicit

Agents should distinguish:

-   observed;
-   inferred;
-   hypothesized;
-   contradicted;
-   unknown.

A model confidence score should not be called a probability unless
empirically calibrated.

------------------------------------------------------------------------

# 3. Agent Map

  -----------------------------------------------------------------------------
  \#                Agent / Service   Ontology Location Primary Function
  ----------------- ----------------- ----------------- -----------------------
  1                 Document          Document          Route documents
                    Classifier                          

  2                 Document          Document → Claim  Extract atomic factual
                    Extraction Agent                    Claims

  3                 Quantitative ETL  Quantitative      Normalize numerical
                    Service           Document → Data   information

  4                 Event Resolution  Claim → Event     Cluster Claims into
                    Agent                               Events

  5                 Event             Event             Determine materiality
                    Significance                        
                    Agent                               

  6                 Process Discovery Event → Process   Create/find affected
                    Agent                               Processes

  7                 Process Update    Event → Process   Update existing
                    Agent                               Processes

  8                 Process Archetype Process           Classify Process
                    Agent                               Archetype

  9                 Process State     Process           Estimate current State
                    Agent                               

  10                Process Critic    Process           Falsify/challenge
                    Agent                               thesis

  11                Bottleneck        Process →         Identify constraints
                    Identification    Bottleneck        
                    Agent                               

  12                Capability        Bottleneck →      Identify required
                    Mapping Agent     Capability        Capabilities

  13                Capability        Capability        Identify multiple
                    Confluence Agent                    upstream Processes

  14                Asset Discovery   Capability →      Find relevant Asset
                    Agent             Asset             universe

  15                Asset Exposure    Asset             Estimate
                    Agent                               Process/Capability
                                                        exposure

  16                Asset Quant Agent Asset             Fundamental/technical
                                                        analysis

  17                Asset Quality     Asset             Qualitative Asset
                    Agent                               characteristics

  18                Historical        Process State     Retrieve historical
                    Process Retrieval                   analogs
                    Service                             

  19                Historical State  State ↔           Align developmental
                    Alignment Agent   Historical State  stages

  20                Historical Asset  Historical State  Match historical Assets
                    Matching Agent    → Asset           

  21                Historical        Historical Asset  Calculate subsequent
                    Outcome Engine    → Outcome         returns

  22                Analog Forecast   Historical        Build empirical
                    Agent             Episodes →        distributions
                                      Forecast          

  23                Counterfactual    Process           Search for failure
                    Agent                               scenarios

  24                Evidence          Evidence          Detect
                    Independence                        duplicate/dependent
                    Agent                               evidence

  25                Thesis Scoring    Process           Score Thesis Quality
                    Agent                               

  26                Asset Ranking     Asset Universe    Rank Process
                    Agent                               expressions

  27                Thesis Synthesis  Process           Produce human-readable
                    Agent                               thesis

  28                Asset Synthesis   Asset             Explain Asset
                    Agent                               expression

  29                Forecast          Forecast          Explain historical
                    Explanation Agent                   basis

  30                Calibration Agent System            Measure forecast
                                                        calibration

  31                Research Quality  System            Detect
                    Auditor                             structural/research
                                                        errors

  32                Orchestrator      Cross-cutting     Schedule and coordinate
                                                        agents
  -----------------------------------------------------------------------------

Not every item should be an LLM. Several should be deterministic
services.

------------------------------------------------------------------------

# 4. Document and Evidence Agents

## 4.1 Document Classifier

### Ontology

``` text
Raw Document
    ↓
Document Type
```

### Purpose

Determine how an incoming document should be processed.

### Responsibilities

-   classify source and document type;
-   identify textual vs quantitative content;
-   identify entities;
-   route to appropriate extraction pipeline.

### Sample prompt

``` text
Classify this document.

Return:
- document_type
- source_type
- primary_information_mode: textual / quantitative / mixed
- named_entities
- likely_event_types
- extraction_strategy

Do not infer investment implications.
```

### Metrics

-   document-type accuracy;
-   entity precision/recall;
-   routing accuracy;
-   false-routing rate.

------------------------------------------------------------------------

## 4.2 Document Extraction Agent

### Ontology

``` text
Document
    ↓
Claim
```

### Purpose

Convert documents into atomic factual Claims.

### Responsibilities

Extract:

-   factual statements;
-   dates;
-   entities;
-   commitments;
-   regulatory requirements;
-   numerical facts;
-   explicitly stated forecasts.

Do not infer investment implications.

### Sample prompt

``` text
Extract atomic factual Claims from this document.

For every Claim provide:
- proposition
- source span
- entities
- date
- claim type
- attribution
- whether it is an observed fact, reported statement,
  company forecast, government forecast, analyst opinion,
  or inference.

Do not add facts not contained in the document.
```

### Metrics

-   extraction precision;
-   extraction recall;
-   source-span accuracy;
-   attribution accuracy;
-   hallucination rate.

------------------------------------------------------------------------

## 4.3 Quantitative ETL Service

### Ontology

``` text
Numerical Documents
    ↓
Canonical Quantitative Data
```

This should primarily be deterministic software.

### Responsibilities

-   parse financial statements;
-   normalize units/currencies;
-   normalize periods;
-   calculate standard derived metrics;
-   preserve source provenance;
-   handle revisions and restatements.

### Metrics

-   numerical accuracy;
-   reconciliation accuracy;
-   unit conversion accuracy;
-   period alignment accuracy;
-   completeness;
-   provenance accuracy.

------------------------------------------------------------------------

# 5. Event Agents

## 5.1 Event Resolution Agent

### Ontology

``` text
Claims
   ↓
Canonical Event
```

### Purpose

Cluster multiple Claims referring to the same real-world occurrence.

Example:

``` text
Article A: Government buys stake in MP Materials
Article B: Pentagon takes equity position
Article C: US invests in rare-earth producer
        ↓
Canonical Event
```

### Sample prompt

``` text
Determine which Claims refer to the same underlying real-world Event.

For each cluster:
- define canonical event;
- list supporting Claims;
- identify contradictions;
- determine event timestamp;
- identify independent reporting;
- estimate event confidence.

Do not count repeated reporting of the same source as independent evidence.
```

### Metrics

-   cluster precision/recall;
-   duplicate suppression rate;
-   false merge rate;
-   false split rate;
-   timestamp accuracy;
-   independent-source accuracy.

------------------------------------------------------------------------

## 5.2 Event Significance Agent

### Ontology

``` text
Event
   ↓
Materiality / Novelty
```

### Purpose

Determine whether an Event warrants propagation through the graph.

### Dimensions

-   novelty;
-   economic materiality;
-   credibility;
-   persistence potential;
-   direct Process relevance;
-   direct Asset relevance.

### Sample prompt

``` text
Evaluate whether this Event should trigger an update.

Score:
- novelty
- economic materiality
- credibility
- persistence potential
- Process relevance
- Asset relevance

Explain the evidence for each score.
Do not predict asset returns.
```

### Metrics

-   precision of triggered updates;
-   missed material-event rate;
-   unnecessary update rate;
-   downstream state-change hit rate.

------------------------------------------------------------------------

# 6. Economic Process Agents

## 6.1 Process Discovery Agent

### Ontology

``` text
Event
   ↓
Economic Process
```

### Purpose

Determine whether an Event:

1.  creates a new Process;
2.  materially changes an existing Process;
3.  provides evidence for an existing Process;
4.  has no meaningful Process implication.

### Sample prompt

``` text
Given this Event and the existing Process graph:

Identify:
1. new Processes that should be created;
2. existing Processes that should be updated;
3. Processes that are unaffected.

For each proposed relationship:
- describe the causal mechanism;
- identify directionality;
- cite supporting Claims;
- state uncertainty.

Do not identify stocks yet.
```

### Metrics

-   Process discovery precision/recall;
-   causal relationship precision;
-   false Process creation rate;
-   expert agreement.

------------------------------------------------------------------------

## 6.2 Process Update Agent

### Ontology

``` text
Event
   ↓
Existing Economic Process
```

### Purpose

Apply a delta to an existing Process rather than rewriting the thesis
wholesale.

### Example output

``` text
Process:
AI Infrastructure

State:
Infrastructure Expansion → stronger Infrastructure Expansion

Evidence:
+2 supporting
+1 contradictory

Feature changes:
demand_acceleration +0.08
supply_tightness +0.04

Confidence:
0.78 → 0.82
```

### Sample prompt

``` text
Update the existing Economic Process using the supplied Event.

Determine:
- which beliefs are strengthened;
- which are weakened;
- which are unchanged;
- whether Process State changes;
- whether Bottlenecks change;
- whether Capabilities change;
- whether evidence contradicts existing beliefs.

Do not rewrite unaffected portions.
Every update must cite supporting Claims.
```

### Metrics

-   update accuracy;
-   unnecessary-state-change rate;
-   missed-state-change rate;
-   evidence attribution;
-   temporal consistency;
-   expert agreement.

------------------------------------------------------------------------

## 6.3 Process Archetype Agent

### Ontology

``` text
Economic Process
    ↓
Process Archetype
```

### Initial Archetypes

-   Infrastructure / S-curve;
-   Commodity Supply Cycle;
-   Industrial Bottleneck;
-   Regulatory Implementation;
-   Business Model Disruption.

### Sample prompt

``` text
Classify this Economic Process.

Choose the most appropriate primary Archetype from:
- infrastructure_s_curve
- commodity_supply_cycle
- industrial_bottleneck
- regulatory_implementation
- business_model_disruption

Return:
- primary archetype;
- secondary archetypes;
- evidence;
- reasons;
- rejected alternatives.

Do not choose an Archetype merely because it creates an attractive investment narrative.
```

### Metrics

-   classification accuracy;
-   confusion matrix;
-   inter-rater agreement;
-   downstream forecast performance by Archetype.

------------------------------------------------------------------------

## 6.4 Process State Agent

### Ontology

``` text
Economic Process
    ↓
Process State
```

### Purpose

Estimate where the Process is in its lifecycle.

### Sample prompt

``` text
Estimate the current State of this Process.

Use:
- current evidence;
- quantitative features;
- Archetype-specific state definitions;
- historical state examples.

Return:
- current State;
- confidence;
- state features;
- supporting evidence;
- contradictory evidence;
- indicators of transition;
- indicators of reversal.

Do not estimate stock returns.
```

### Metrics

-   historical State classification accuracy;
-   transition lead time;
-   false transition rate;
-   state persistence;
-   expert agreement.

------------------------------------------------------------------------

## 6.5 Process Critic Agent

### Ontology

``` text
Economic Process
    ↓
Adversarial Critique
```

### Purpose

Actively search for reasons the Process is wrong.

This is particularly important because LLMs are naturally good at
constructing coherent narratives.

### Sample prompt

``` text
Attempt to falsify the following Economic Process.

Identify:
1. unsupported assumptions;
2. missing causal links;
3. contradictory evidence;
4. alternative explanations;
5. historical counterexamples;
6. indicators that would falsify the Process;
7. correlations that may not be causal.

Do not rescue the thesis.
Your objective is to find reasons it may be wrong.
```

### Metrics

-   expert-rated usefulness;
-   genuine contradiction discovery rate;
-   false-positive contradiction rate;
-   diversity of alternative hypotheses;
-   reduction in out-of-sample Process failures.

------------------------------------------------------------------------

# 7. Bottleneck and Capability Agents

## 7.1 Bottleneck Identification Agent

### Ontology

``` text
Process
   ↓
Bottleneck
```

### Purpose

Identify the constraint limiting further Process development.

### Sample prompt

``` text
Identify the current binding Bottleneck.

Consider:
- physical constraints;
- production capacity;
- capital;
- permitting;
- labor;
- specialized inputs;
- infrastructure;
- technology;
- regulation.

For each candidate:
- explain why it is limiting;
- identify supporting evidence;
- state whether it is currently binding or merely potential;
- identify evidence that would prove it has been relieved.
```

### Metrics

-   bottleneck accuracy;
-   lead time before bottleneck becomes economically important;
-   false-bottleneck rate;
-   downstream Capability prediction accuracy.

------------------------------------------------------------------------

## 7.2 Capability Mapping Agent

### Ontology

``` text
Bottleneck
    ↓
Capability Requirement
```

### Purpose

Translate a Bottleneck into the minimum economic capabilities required
to resolve it.

### Sample prompt

``` text
Translate this Bottleneck into the minimum set of Capabilities required to resolve it.

Distinguish:
- necessary;
- sufficient;
- complementary;
- substitute capabilities.

Represent logical requirements explicitly using:
AND / OR / OPTIONAL.

Do not identify companies yet.
```

### Metrics

-   Capability precision;
-   Capability recall;
-   logical AND/OR accuracy;
-   expert agreement;
-   downstream Asset discovery precision.

------------------------------------------------------------------------

## 7.3 Capability Confluence Agent

### Ontology

``` text
Multiple Processes
       ↓
Capability
```

### Purpose

Identify when independent upstream Processes converge on one Capability.

Example:

``` text
AI Infrastructure ──────┐
CHIPS Act ───────────────┼──> Domestic Semiconductor Fabs
National Security ──────┘
```

### Sample prompt

``` text
For this Capability, identify all upstream Processes that materially support it.

Determine:
- independent Processes;
- correlated Processes;
- redundant evidence;
- AND requirements;
- reinforcing relationships;
- interfering relationships.

Do not count multiple reports from the same Process as independent support.
```

### Metrics

-   upstream relationship precision;
-   confluence recall;
-   independence classification;
-   false-reinforcement rate.

------------------------------------------------------------------------

# 8. Asset Agents

## 8.1 Asset Discovery Agent

### Ontology

``` text
Capability
    ↓
Asset Universe
```

### Purpose

Find investable Assets providing meaningful exposure to a Capability.

### Sample prompt

``` text
Identify the investable Asset universe associated with this Capability.

For each Asset:
- describe the exposure pathway;
- identify direct vs indirect exposure;
- identify geographic relevance;
- assess whether exposure is material or incidental;
- identify major dependencies.

Do not rank Assets yet.
```

### Metrics

-   candidate recall;
-   material-exposure precision;
-   false-exposure rate;
-   geographic constraint accuracy.

------------------------------------------------------------------------

## 8.2 Asset Exposure Agent

### Ontology

``` text
Capability
    ↓
Asset
```

### Purpose

Estimate the strength and type of Asset exposure.

Dimensions:

-   revenue exposure;
-   earnings exposure;
-   incremental earnings exposure;
-   capacity;
-   market share;
-   strategic importance;
-   geography;
-   operating leverage.

### Sample prompt

``` text
Estimate this Asset's exposure to the specified Capability.

Separate:
- direct exposure;
- indirect exposure;
- optionality;
- dependencies;
- offsetting exposures.

Use quantitative evidence wherever available.
Do not infer exposure merely from company marketing language.
```

### Metrics

-   exposure accuracy;
-   revenue/earnings attribution accuracy;
-   expert agreement;
-   subsequent Asset sensitivity to Process outcomes.

------------------------------------------------------------------------

## 8.3 Asset Quant Agent

### Ontology

``` text
Asset Universe
    ↓
Quantitative Comparison
```

### Purpose

Perform reproducible numerical comparison of Assets.

### Analysis

-   growth;
-   margins;
-   valuation;
-   balance sheet;
-   technicals;
-   institutional ownership;
-   crowding;
-   relative strength;
-   volatility.

### Sample prompt

``` text
Compare these Assets as expressions of the specified Capability.

Compute:
- growth;
- margins;
- valuation;
- balance-sheet quality;
- relative strength;
- volatility;
- ownership/crowding;
- relevant technical indicators.

Return:
- structured metrics;
- methodology;
- data timestamps;
- missing data;
- ranking inputs.

Do not manually calculate values in prose.
```

### Metrics

-   numerical correctness;
-   reproducibility;
-   data freshness;
-   ranking stability;
-   out-of-sample ranking performance.

------------------------------------------------------------------------

## 8.4 Asset Quality Agent

### Ontology

``` text
Asset
    ↓
Qualitative Asset Characteristics
```

### Purpose

Evaluate characteristics not captured fully by standard financial
metrics.

Examples:

-   first-mover advantage;
-   vertical integration;
-   market share;
-   switching costs;
-   intellectual property;
-   strategic importance;
-   execution quality;
-   supply-chain position.

### Sample prompt

``` text
Evaluate this Asset as an expression of the specified Capability.

Assess:
- first-mover advantage;
- vertical integration;
- market share;
- competitive moat;
- strategic importance;
- operating leverage;
- execution risk;
- dependency risk.

Separate observed facts from inference.
Identify counterarguments.
```

### Metrics

-   factual support rate;
-   expert agreement;
-   winner/loser discrimination;
-   incremental predictive value over quantitative factors.

------------------------------------------------------------------------

# 9. Historical Learning Agents

## 9.1 Historical Process Retrieval Service

### Ontology

``` text
Current Process State
        ↓
Historical Process Candidates
```

### Purpose

Retrieve historical Process episodes with similar Archetype and State.

Retrieval priority:

1.  Same Archetype + same State.
2.  Same Archetype + adjacent State.
3.  Structurally similar Process.
4.  Broad base-rate examples.

This should primarily be a search/ranking system rather than an LLM-only
task.

### Metrics

-   precision@K;
-   expert relevance rating;
-   State-match accuracy;
-   forecast improvement.

------------------------------------------------------------------------

## 9.2 Historical State Alignment Agent

### Ontology

``` text
Current Process State
        ↕
Historical State Snapshot
```

### Purpose

Determine whether a historical Process was actually at an equivalent
developmental stage.

### Sample prompt

``` text
Compare the current Process State with this historical State.

Assess:
- demand growth;
- penetration;
- supply response;
- CapEx;
- capacity constraints;
- pricing;
- adoption;
- speculation;
- competition.

Determine:
1. whether the states are comparable;
2. strongest similarities;
3. material differences;
4. whether to include the historical case;
5. similarity score by dimension.
```

### Metrics

-   expert-rated analog quality;
-   forecast improvement;
-   false-analog rate;
-   similarity ranking quality.

------------------------------------------------------------------------

## 9.3 Historical Asset Matching Agent

### Ontology

``` text
Historical State Snapshot
        ↓
Historical Capability
        ↓
Historical Asset Universe
        ↓
Comparable Historical Assets
```

### Purpose

Find historical Assets resembling current Assets at the equivalent
Process State.

### Sample prompt

``` text
Identify historical Assets comparable to the current candidate at the equivalent Process State.

Match on:
- Capability;
- exposure;
- market share;
- growth;
- valuation;
- operating leverage;
- balance sheet;
- competitive position;
- technical state;
- market regime.

Use only information available as of the historical observation date.

Do not use eventual success as a matching criterion.
```

### Metrics

-   point-in-time integrity;
-   analog precision;
-   expert relevance;
-   leakage rate;
-   subsequent ranking performance.

------------------------------------------------------------------------

## 9.4 Historical Outcome Engine

### Ontology

``` text
Historical Asset Snapshot
        ↓
Historical Outcome
```

This should be deterministic.

### Outcomes

-   1M;
-   3M;
-   6M;
-   12M;
-   24M returns;
-   maximum drawdown;
-   maximum upside;
-   volatility;
-   benchmark-relative return.

### Critical rule

The observation date must be frozen before outcome calculation.

### Metrics

-   return accuracy;
-   corporate-action adjustment accuracy;
-   survivorship-bias checks;
-   point-in-time correctness.

------------------------------------------------------------------------

## 9.5 Analog Forecast Agent

### Ontology

``` text
Comparable Historical Episodes
        ↓
Empirical Conditional Distribution
```

### Purpose

Construct the current forecast from comparable historical outcomes
rather than free-form LLM prediction.

### Sample prompt

``` text
Using only the supplied comparable State-Conditioned Asset Episodes:

Calculate empirical distributions for:
- 1 month
- 3 months
- 6 months
- 12 months
- 24 months

Report:
- sample size;
- median;
- P25;
- P75;
- P90;
- probability of positive return;
- probability of >25%;
- probability of >50%;
- probability of >100%;
- maximum historical drawdown.

Do not invent probabilities outside the empirical evidence.
State clearly when the sample is insufficient.
```

### Metrics

-   calibration;
-   Brier score;
-   log loss;
-   CRPS;
-   quantile coverage;
-   interval calibration;
-   out-of-sample discrimination.

------------------------------------------------------------------------

# 10. Critique and Evidence Agents

## 10.1 Counterfactual / Falsification Agent

### Ontology

``` text
Process
    ↓
Counterfactuals
```

### Purpose

Test whether the Process survives plausible alternative worlds.

### Sample prompt

``` text
Construct the strongest plausible counterfactuals to this Process.

For each:
- state the assumption being challenged;
- describe the alternative world;
- identify affected causal links;
- identify Assets harmed;
- identify observable indicators that would reveal the counterfactual.

Do not use straw-man alternatives.
```

### Metrics

-   counterfactual diversity;
-   expert-rated strength;
-   failure detection rate;
-   false-negative rate for invalidating scenarios.

------------------------------------------------------------------------

## 10.2 Evidence Independence Agent

### Ontology

``` text
Claims / Events
    ↓
Evidence Independence
```

### Purpose

Determine whether apparently numerous evidence items are genuinely
independent.

### Sample prompt

``` text
Determine the independence structure of these evidence items.

Identify:
- shared source;
- derivative reporting;
- independent observations;
- repeated claims;
- genuinely new information.

Return an evidence-dependence graph.
```

### Metrics

-   duplicate detection;
-   independent-source precision;
-   false-independence rate;
-   improvement in evidence weighting.

------------------------------------------------------------------------

# 11. Scoring and Synthesis Agents

## 11.1 Thesis Scoring Agent

### Ontology

``` text
Economic Process
    ↓
Thesis Quality
```

### Purpose

Score the underlying Process independently of Asset quality.

Suggested 0--10 axes:

-   logical coherence;
-   accumulated evidence;
-   Process State confidence;
-   historical precedent;
-   counterfactual robustness;
-   independent evidence;
-   causal coherence;
-   data quality;
-   contradiction burden;
-   uncertainty.

### Sample prompt

``` text
Score this Economic Process independently of any Asset.

Evaluate each axis from 0–10:
- logical coherence
- accumulated evidence
- Process State confidence
- historical precedent
- counterfactual robustness
- independent evidence
- causal coherence
- data quality
- contradiction burden
- uncertainty

For every score:
- provide evidence;
- explain why it is not higher;
- distinguish fact from inference.

Do not consider valuation or technical setup.
```

### Metrics

The most important question is whether the score predicts future Process
persistence or downstream opportunity.

Additional metrics:

-   inter-rater reliability;
-   score stability;
-   future Process persistence;
-   incremental predictive value;
-   calibration by score bucket.

------------------------------------------------------------------------

## 11.2 Asset Ranking Agent

### Ontology

``` text
Capability
    ↓
Candidate Assets
    ↓
Asset Ranking
```

### Purpose

Rank Assets as expressions of the same underlying Capability.

### Sample prompt

``` text
Rank these Assets as expressions of the specified Capability.

Keep separate:
A. Process/Capability exposure
B. Asset quality
C. valuation
D. market structure
E. technical confirmation

Return:
- ranking;
- factor scores;
- evidence;
- major weaknesses;
- comparison against next-best Asset.

Do not change the underlying Process score based on Asset ranking.
```

### Metrics

-   information coefficient;
-   rank correlation with future returns;
-   top-decile excess return;
-   top-vs-bottom spread;
-   turnover;
-   ranking stability;
-   incremental value over simple sector/market factors.

------------------------------------------------------------------------

## 11.3 Thesis Synthesis Agent

### Ontology

``` text
Economic Process
    ↓
Human-readable Thesis
```

### Purpose

Convert structured Process state into an evidence-linked narrative.

### Sample prompt

``` text
Write a human-readable thesis for this Economic Process.

Structure:
1. What is happening?
2. Why is it happening?
3. What State is it in?
4. What evidence supports it?
5. What evidence contradicts it?
6. What is the current Bottleneck?
7. What Capabilities are required?
8. What historical analogs are relevant?
9. What would falsify the thesis?

Every factual statement must be traceable to supplied evidence.
Do not introduce new facts.
Do not recommend securities.
```

### Metrics

-   factual support rate;
-   citation completeness;
-   unsupported assertion rate;
-   human readability;
-   contradiction omission rate.

------------------------------------------------------------------------

## 11.4 Asset Synthesis Agent

### Ontology

``` text
Asset
    ↓
Human-readable Asset Thesis
```

### Purpose

Explain why an Asset is a strong or weak expression of a Capability.

### Sample prompt

``` text
Explain why this Asset is or is not an attractive expression of the specified Capability.

Cover:
- exposure;
- operating leverage;
- competitive advantages;
- valuation;
- financial quality;
- technical state;
- crowding;
- principal risks.

Separate Process strength from Asset-specific characteristics.
Do not provide an options strategy.
```

### Metrics

-   factual accuracy;
-   evidence completeness;
-   ranking consistency;
-   expert agreement.

------------------------------------------------------------------------

## 11.5 Forecast Explanation Agent

### Ontology

``` text
Empirical Forecast
    ↓
Explanation
```

### Purpose

Explain why historical episodes were selected and what they imply.

### Sample prompt

``` text
Explain this empirical forecast using only the supplied historical episodes.

Include:
- why each analog was selected;
- major similarities;
- major differences;
- historical Asset characteristics;
- subsequent outcomes;
- sample-size limitations;
- reasons the current case may diverge.

Do not make additional predictions beyond the supplied analysis.
```

### Metrics

-   explanation faithfulness;
-   citation completeness;
-   numerical consistency;
-   human comprehension.

------------------------------------------------------------------------

# 12. Governance Agents

## 12.1 Calibration Agent

### Ontology

``` text
Historical Forecasts
        ↓
Realized Outcomes
        ↓
Calibration
```

### Purpose

Measure whether forecast distributions correspond to reality.

### Metrics

#### Binary forecasts

-   Brier score;
-   log loss;
-   reliability diagrams.

#### Distribution forecasts

-   CRPS;
-   quantile coverage;
-   interval score;
-   calibration by horizon.

#### Rankings

-   information coefficient;
-   rank correlation;
-   top-decile excess return;
-   extreme-winner precision/recall.

#### Stability

-   rolling calibration;
-   calibration by Archetype;
-   calibration by Process State;
-   calibration by market regime.

------------------------------------------------------------------------

## 12.2 Research Quality Auditor

### Ontology

``` text
Entire Research Graph
        ↓
Audit
```

### Purpose

Detect structural errors that could invalidate downstream conclusions.

### Checks

#### Provenance

-   unsupported Claims;
-   broken citations;
-   missing source locations.

#### Temporal integrity

-   future information in historical analysis;
-   publication-date errors;
-   restatement leakage.

#### Graph integrity

-   circular causality;
-   duplicate Processes;
-   orphaned Assets;
-   impossible relationships.

#### Evidence integrity

-   duplicated evidence;
-   correlated sources;
-   over-weighted repeated reporting.

#### Quantitative integrity

-   incorrect calculations;
-   missing data;
-   survivorship bias;
-   look-ahead bias.

### Sample prompt

``` text
Audit this research chain for:
- unsupported assertions;
- temporal leakage;
- circular reasoning;
- duplicated evidence;
- contradictions;
- inappropriate causal links;
- numerical inconsistencies.

Return each issue with:
- severity;
- affected object;
- evidence;
- recommended remediation.
```

### Metrics

-   defect detection precision;
-   defect detection recall;
-   false-negative rate on injected defects;
-   leakage detection rate.

------------------------------------------------------------------------

## 12.3 Orchestrator

### Ontology

Cross-cutting.

### Purpose

Coordinate all other agents without becoming a general-purpose
investment reasoner.

Responsibilities:

-   scheduling;
-   dependencies;
-   retries;
-   versioning;
-   update triggers;
-   deduplication;
-   cost/token budgets;
-   state transitions;
-   job prioritization.

Example:

``` text
New Document
    ↓
Classify
    ↓
Extract Claims
    ↓
Resolve Event
    ↓
Assess Materiality
    ↓
Update affected Processes
    ↓
Re-estimate State
    ↓
Identify Bottleneck
    ↓
Update Capabilities
    ↓
Update Assets
    ↓
Run Quant
    ↓
Retrieve Historical Analogs
    ↓
Update Forecast
    ↓
Critique
    ↓
Update Summary
```

------------------------------------------------------------------------

# 13. Update and Trigger Architecture

The system should not propagate every document through the entire graph
immediately.

Instead:

``` text
Documents
    ↓
Claims
    ↓
Event clustering
    ↓
Event accumulation
    ↓
Process update trigger
    ↓
Process-level evidence accumulation
    ↓
Asset update trigger
    ↓
Asset-level quantitative analysis
```

Triggers can be:

### Time-triggered

Example:

``` text
Process updates: daily
Asset updates: daily
Historical forecast: weekly
```

### Delta-triggered

Examples:

``` text
State confidence changes > threshold
New material Event
New Bottleneck
New Capability
Major quantitative divergence
```

### Event-triggered

Examples:

-   legislation enacted;
-   earnings released;
-   government transaction;
-   major supply disruption;
-   acquisition;
-   regulatory decision.

------------------------------------------------------------------------

# 14. Agent Interaction Pattern

Agents should communicate through typed objects rather than unrestricted
prose.

Preferred:

``` text
Agent A
  ↓
Typed Object
  ↓
Schema Validation
  ↓
Agent B
```

Example:

``` text
Document Extraction Agent
        ↓
Claim[]
        ↓
Schema Validation
        ↓
Event Resolution Agent
```

This makes every boundary independently testable.

------------------------------------------------------------------------

# 15. Debate and Adjudication

For high-impact judgments:

``` text
Pro-Thesis Agent
        ↓
Counter-Thesis Agent
        ↓
Quantitative Evidence
        ↓
Adjudicator
        ↓
Process Update
```

The adjudicator should identify:

-   agreement;
-   disagreement;
-   evidence conflicts;
-   assumptions driving disagreement;
-   whether disagreement is empirically resolvable.

Simply asking one LLM "are you sure?" is not an adequate independence
mechanism.

------------------------------------------------------------------------

# 16. Preventing Agentic Overreach

Agents should stop at their ontology boundary.

Examples:

The Document Extraction Agent should not say:

> "Therefore NVDA is a buy."

The Bottleneck Agent should not say:

> "Buy MP Materials."

The Historical Retrieval Agent should not say:

> "This stock will 10x."

The Historical Outcome Engine should not infer causality from returns.

The Asset Ranking Agent should not silently change the Process thesis.

This separation is essential for:

-   debugging;
-   attribution;
-   evaluation;
-   reproducibility;
-   preventing narrative contamination.

------------------------------------------------------------------------

# 17. Evaluation Hierarchy

Evaluation should occur at four levels.

## Level 1 --- Component Accuracy

Does the agent perform its assigned task?

Examples:

-   extraction precision;
-   event clustering;
-   State classification.

## Level 2 --- Structural Accuracy

Does its output improve the graph?

Examples:

-   correct Process creation;
-   correct Bottleneck;
-   correct Capability;
-   correct Asset exposure.

## Level 3 --- Predictive Utility

Does its output improve downstream forecasts?

Examples:

-   historical analog selection;
-   Asset ranking;
-   Process persistence prediction.

## Level 4 --- Investment Outcome

Does the complete system identify superior opportunities?

Examples:

-   excess return;
-   hit rate;
-   tail-winner discovery;
-   drawdown;
-   risk-adjusted performance.

The system should not optimize directly for Level 4 before Levels 1--3
are validated.

------------------------------------------------------------------------

# 18. Evaluation Dataset Architecture

The system needs separate benchmark datasets.

## 18.1 Extraction Benchmark

Manually labeled:

-   Claims;
-   entities;
-   dates;
-   source spans;
-   Events.

## 18.2 Process Benchmark

Historical Events mapped to:

-   Processes;
-   Archetypes;
-   State transitions.

## 18.3 Capability Benchmark

Historical Processes mapped to:

-   Bottlenecks;
-   Capabilities;
-   AND/OR logical structures.

## 18.4 Asset Benchmark

Processes mapped to historically relevant Assets.

## 18.5 Forecast Benchmark

Historical State-Conditioned Asset Episodes with:

-   frozen observation dates;
-   point-in-time features;
-   subsequent outcomes.

The final benchmark must be strictly out-of-sample.

------------------------------------------------------------------------

# 19. Synthetic Fault Injection

The system should intentionally inject known errors into test
environments.

Examples:

``` text
Future financial metric
    ↓
Historical Asset Snapshot
```

Expected result:

> Research Quality Auditor detects temporal leakage.

Other injected faults:

-   duplicate evidence;
-   false Event merge;
-   unsupported Claim;
-   incorrect date;
-   circular Process;
-   false Capability;
-   incorrect State;
-   survivorship bias;
-   incorrect return calculation.

This produces an objective benchmark for system integrity.

------------------------------------------------------------------------

# 20. Backtesting and Temporal Integrity

At historical date `t`, the system may access:

``` text
Documents published ≤ t
Financial data available ≤ t
Market prices ≤ t
Corporate structure known ≤ t
```

It may not access:

``` text
Later filings
Future analyst revisions
Restated numbers unavailable at t
Future Process States
Future Asset classifications
Future company outcomes
```

This should be enforced programmatically wherever possible.

The point-in-time boundary is more important than simply having a "no
future dates" convention because many financial datasets contain
information that was revised after the original observation date.

------------------------------------------------------------------------

# 21. Agent and Prompt Versioning

Every output should contain:

``` text
agent_name
agent_version
model
prompt_version
timestamp
input_object_versions
output_schema_version
```

Prompts should be treated as code.

A prompt change can alter:

-   Process classification;
-   State estimation;
-   Bottleneck identification;
-   Capability mapping;
-   analog retrieval;
-   Asset ranking.

Therefore prompt versions must be attached to every historical output.

------------------------------------------------------------------------

# 22. Model Independence

For high-impact judgments, use genuinely different reasoning paths where
practical.

Example:

``` text
State Agent A
        +
State Agent B
        +
Quantitative State Features
        ↓
State Adjudication
```

Independence is more valuable than repeatedly querying the same model.

Possible sources of diversity:

-   different model families;
-   different prompt structures;
-   separate evidence subsets;
-   LLM vs deterministic features;
-   retrieval-based vs generative reasoning.

------------------------------------------------------------------------

# 23. Human Review Boundaries

Human review should be concentrated where errors have large downstream
consequences.

Recommended review points:

### New Process creation

A false Process can contaminate the entire graph.

### Major State transition

State determines historical analog selection.

### New Bottleneck

Bottleneck determines Capability discovery.

### Major Capability confluence

Multiple Processes converging on one Capability can create unusually
strong signals.

### Extreme Asset ranking

Especially when historical sample sizes are small.

### Tail forecasts

Any apparent 10x/100x opportunity should receive additional scrutiny.

------------------------------------------------------------------------

# 24. Recommended MVP

A practical first implementation can begin with:

``` text
1. Document Extraction Agent
2. Event Resolution Agent
3. Process Update Agent
4. Process Archetype Agent
5. Process State Agent
6. Bottleneck Identification Agent
7. Capability Mapping Agent
8. Asset Discovery Agent
9. Asset Quant Service
10. Historical Process Retrieval
11. Historical State Alignment
12. Historical Asset Matching
13. Historical Outcome Engine
14. Analog Forecast Agent
15. Process Critic Agent
16. Thesis Synthesis Agent
17. Asset Ranking Agent
18. Research Quality Auditor
19. Orchestrator
```

Other components can initially be deterministic services or later-stage
agents.

------------------------------------------------------------------------

# 25. Suggested Execution Graph

``` text
                         DOCUMENT
                            │
                            ▼
                 DOCUMENT CLASSIFIER
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
        EXTRACTION AGENT          QUANT ETL
                │                       │
                ▼                       │
             CLAIMS                     │
                │                       │
                ▼                       │
        EVENT RESOLUTION                │
                │                       │
                ▼                       │
          EVENT SIGNIFICANCE            │
                │                       │
                └───────────┬───────────┘
                            ▼
                  PROCESS DISCOVERY
                            │
                            ▼
                   PROCESS UPDATE
                            │
                  ┌─────────┴─────────┐
                  ▼                   ▼
          ARCHETYPE AGENT       PROCESS CRITIC
                  │                   │
                  ▼                   │
             STATE AGENT              │
                  │                   │
                  └─────────┬─────────┘
                            ▼
                 BOTTLENECK AGENT
                            │
                            ▼
                 CAPABILITY MAPPING
                            │
                            ▼
              CAPABILITY CONFLUENCE
                            │
                            ▼
                 ASSET DISCOVERY
                            │
                   ┌────────┴────────┐
                   ▼                 ▼
              ASSET EXPOSURE     ASSET QUANT
                   │                 │
                   └────────┬────────┘
                            ▼
                    ASSET RANKING
                            │
                            ▼
              HISTORICAL RETRIEVAL
                            │
                            ▼
                STATE ALIGNMENT
                            │
                            ▼
               HISTORICAL ASSET
                   MATCHING
                            │
                            ▼
              HISTORICAL OUTCOMES
                            │
                            ▼
                ANALOG FORECAST
                            │
                            ▼
               THESIS / ASSET
                  SYNTHESIS
                            │
                            ▼
                 QUALITY AUDITOR
                            │
                            ▼
                         USER
```

------------------------------------------------------------------------

# 26. The Most Important Evaluation Principle

The central question for every agent is not:

> **"Does the output sound intelligent?"**

It is:

> **"Does this agent improve the accuracy, calibration, robustness, or
> efficiency of the downstream system?"**

For example, the Process Critic Agent should not be evaluated on how
sophisticated its critique sounds.

It should be evaluated on whether its critiques:

-   identify genuine weaknesses;
-   reduce false-positive Processes;
-   improve out-of-sample Process persistence;
-   improve downstream Asset selection.

Likewise, the Historical Analog Agent should not be evaluated because
its analogs sound intuitively similar.

It should be evaluated by whether:

> **Including those analogs improves out-of-sample forecast calibration
> and Asset ranking.**

------------------------------------------------------------------------

# 27. Final Architecture

The intended system is not an LLM that predicts stocks.

It is a layered research engine:

``` text
                 REAL WORLD
                     │
                     ▼
               DOCUMENTS
                     │
                     ▼
             STRUCTURED EVIDENCE
                     │
                     ▼
                   EVENTS
                     │
                     ▼
             ECONOMIC PROCESSES
                     │
             ┌───────┴────────┐
             ▼                ▼
        PROCESS STATE      CRITIQUE
             │
             ▼
         BOTTLENECK
             │
             ▼
        CAPABILITIES
             │
             ▼
           ASSETS
             │
       ┌─────┴─────┐
       ▼           ▼
    FUNDAMENTAL  TECHNICAL
       │           │
       └─────┬─────┘
             ▼
       ASSET RANKING
             │
             ▼
      HISTORICAL ANALOG
             │
             ▼
   STATE-CONDITIONED EPISODES
             │
             ▼
   EMPIRICAL OUTCOME DISTRIBUTION
             │
             ▼
       FORECAST / THESIS
             │
             ▼
          CALIBRATION
             │
             └──────────────► BACK INTO SYSTEM
```

The complete feedback loop is:

> **Observe → infer → measure → compare with history → express through
> Assets → observe outcomes → calibrate → improve.**

The agents exist to make that transformation sufficiently modular that
every step can be measured, audited, backtested, and improved
independently.
