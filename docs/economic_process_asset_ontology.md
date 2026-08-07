# Economic Process--Asset Research System

## Ontology and Historical Forecasting Architecture

**Status:** Working design specification\
**Version:** 0.1\
**Purpose:** Define the conceptual ontology for a research system that
converts heterogeneous information into economic-process theses,
identifies investable asset expressions, learns from historical
precedent, and produces empirically grounded forecasts.

------------------------------------------------------------------------

## 1. Executive Summary

The system is designed around a central proposition:

> **Investable opportunities are projections of evolving economic
> Processes into specific assets.**

The system therefore should not begin by asking:

> "Is Microsoft a good stock?"

Instead, it should ask:

> "What economic Process is developing, what State is that Process
> currently in, what Bottlenecks and Capabilities does it create, which
> assets are exposed to those Capabilities, and which of those assets
> currently offer the strongest expression of the Process?"

The system is organized around several separations that are essential to
avoiding common LLM-investing failure modes:

1.  **Evidence is separated from interpretation.**
2.  **Events are separated from Economic Processes.**
3.  **Economic Processes are separated from Capabilities and Assets.**
4.  **Thesis Quality is separated from Asset/Trade Quality.**
5.  **LLM reasoning is separated from deterministic quantitative
    computation.**
6.  **Current-state characterization is separated from historical
    outcome inference.**
7.  **Historical analogs are aligned to the same Process State rather
    than compared as whole narratives.**
8.  **Historical Asset Snapshots use only information available at the
    historical observation date.**
9.  **Forecast distributions are derived from comparable historical
    episodes rather than invented directly by an LLM.**

The resulting system is a form of **state-conditioned, case-based
forecasting**.

The core forecasting unit is a:

> **State-Conditioned Asset Episode**

A State-Conditioned Asset Episode records a historical Economic Process
at a particular point in its development, the relevant Capability, an
Asset exposed to that Capability, the information observable at that
time, and the subsequent return distribution of that Asset.

The forecasting system retrieves historical episodes similar to the
current Process State and Asset characteristics, then uses their
subsequent outcomes to construct an empirical conditional distribution.

------------------------------------------------------------------------

# 2. Design Principles

## 2.1 The system observes latent economic structure

News articles, filings, earnings releases, government actions, and other
documents are observations of an underlying economic reality.

The system attempts to infer:

``` text
Documents
    ↓
Claims
    ↓
Events
    ↓
Economic Processes
    ↓
Process States
    ↓
Bottlenecks
    ↓
Capabilities
    ↓
Assets
```

The system is therefore not fundamentally a news summarizer. It is a
**latent-state inference and investment-expression system**.

------------------------------------------------------------------------

## 2.2 Economic Processes are the primary generative unit

An Economic Process represents an evolving real-world mechanism rather
than a company-specific opinion.

Examples:

-   AI infrastructure adoption
-   Domestic semiconductor fabrication expansion
-   Strategic mineral supply-chain localization
-   Protectionism / trade fragmentation
-   JPY carry-trade unwinding
-   Pandemic-driven work-from-home adoption
-   Housing construction expansion
-   Commodity supply tightening

A Process has a State that describes where it currently sits in its
lifecycle.

------------------------------------------------------------------------

## 2.3 Assets are projections of Processes, not the Processes themselves

A Process may generate multiple downstream Capabilities and therefore
multiple possible Asset expressions.

For example:

``` text
AI Infrastructure Expansion
        │
        ├── Compute
        ├── Memory
        ├── Networking
        ├── Data Centers
        ├── Power Infrastructure
        ├── Semiconductor Manufacturing
        └── Foundation Models
```

The system should not collapse these into a single "AI thesis."

Instead:

``` text
AI Infrastructure Process
        ↓
Multiple downstream Processes / Capabilities
        ↓
Multiple Asset universes
```

This permits multiple upstream Processes to converge on the same
downstream Capability.

Example:

``` text
CHIPS Act ───────────────┐
                         ├──> Domestic Semiconductor Fabs
AI Infrastructure ───────┘
```

------------------------------------------------------------------------

## 2.4 LLMs characterize; quantitative systems measure

The LLM should primarily be responsible for:

-   interpreting documents;
-   extracting semantic meaning;
-   identifying Events;
-   proposing or updating Processes;
-   classifying Process Archetypes;
-   estimating qualitative State;
-   identifying Bottlenecks;
-   identifying Capability Requirements;
-   generating research questions;
-   interpreting quantitative results.

Deterministic or statistical systems should be responsible for:

-   financial calculations;
-   time-series transformations;
-   cross-sectional comparisons;
-   statistical tests;
-   historical retrieval;
-   return calculations;
-   empirical distributions;
-   calibration;
-   ranking calculations.

The fundamental rule is:

> **The LLM formulates and interprets quantitative questions; code
> computes the numbers.**

------------------------------------------------------------------------

# 3. Top-Level Ontology

The core ontology is:

``` text
Document
    ↓
Claim
    ↓
Event
    ↓
Economic Process
    ↓
Process State
    ↓
Bottleneck
    ↓
Capability Requirement
    ↓
Asset Candidate
    ↓
Asset
    ↓
Asset State
    ↓
Underlying Trade Expression
```

The historical-learning subsystem mirrors this structure:

``` text
Historical Process
    ↓
Historical Process State
    ↓
Historical State Snapshot
    ↓
Historical Capability
    ↓
Historical Asset Snapshot
    ↓
Historical Outcome
```

The forecasting object is:

``` text
State-Conditioned Asset Episode
```

which combines:

``` text
Process Archetype
+ Process State
+ Process Features
+ Bottleneck
+ Capability
+ Asset
+ Asset Features at t
+ Market Regime at t
+ Subsequent Outcomes
```

------------------------------------------------------------------------

# 4. Document

## Definition

A **Document** is an external information source ingested by the system.

Examples:

-   news article;
-   government announcement;
-   legislation;
-   regulatory filing;
-   earnings release;
-   earnings transcript;
-   investor presentation;
-   company filing;
-   industry report;
-   statistical release;
-   quantitative dataset.

A Document is not itself an Event or a Process.

It is evidence from which those objects may be inferred.

## Key properties

``` text
Document
├── document_id
├── source
├── publisher
├── publication_time
├── document_type
├── author
├── title
├── raw_content
├── extraction_status
└── provenance
```

Documents must retain immutable provenance.

------------------------------------------------------------------------

# 5. Claim

## Definition

A **Claim** is a discrete proposition extracted from a Document.

Examples:

-   "The US government acquired a stake in MP Materials."
-   "Microsoft increased expected capital expenditure."
-   "The new regulation requires domestic sourcing."
-   "Neodymium, terbium, and dysprosium are strategically important for
    permanent magnets."

Claims should be atomic enough to support later attribution.

A Claim should point back to its exact source location.

``` text
Claim
├── claim_id
├── document_id
├── text
├── source_location
├── extraction_confidence
├── claim_type
└── entities
```

The system should preserve the distinction between:

-   **reported claim**;
-   **derived fact**;
-   **inference**;
-   **hypothesis**.

------------------------------------------------------------------------

# 6. Event

## Definition

An **Event** represents a discrete real-world occurrence inferred from
one or more Claims.

Examples:

-   US government buys a stake in MP Materials.
-   CHIPS Act funding is awarded.
-   Microsoft raises CapEx guidance.
-   A new emission standard is enacted.
-   A major mine announces a production outage.
-   A central bank changes its policy rate.

An Event may be supported by many Documents.

This is important because dozens of articles may describe the same
underlying occurrence.

## Event deduplication

Documents should not independently propagate through the graph.

Instead:

``` text
100 Documents
      ↓
25 Claims about the same event
      ↓
1 canonical Event
```

Events therefore act as an early compression and deduplication layer.

## Event properties

``` text
Event
├── event_id
├── event_type
├── timestamp
├── entities
├── description
├── novelty
├── materiality
├── confidence
├── supporting_claims
└── affected_processes / assets
```

------------------------------------------------------------------------

# 7. Economic Process

## Definition

An **Economic Process** is an evolving real-world causal or structural
development that can influence economic outcomes.

Examples:

-   AI infrastructure expansion;
-   domestic semiconductor fabrication;
-   strategic mineral localization;
-   commodity supply tightening;
-   protectionist trade policy;
-   JPY carry-trade unwinding;
-   work-from-home adoption.

A Process is not simply a collection of headlines.

It is a persistent latent object that accumulates evidence over time.

## Process lifecycle

A Process may progress through States such as:

``` text
Initial Discovery
    ↓
Early Adoption
    ↓
Infrastructure Expansion
    ↓
Acceleration
    ↓
Euphoria
    ↓
Saturation
    ↓
Maturity
```

The exact State sequence depends on the Process Archetype.

Not all Processes use an S-curve.

------------------------------------------------------------------------

# 8. Process Archetypes

Processes should be classified into Archetypes because different
economic dynamics require different State models, evidence requirements,
historical analogs, and asset responses.

Initial Archetypes:

## 8.1 Infrastructure / S-Curve Adoption

Examples:

-   cloud computing;
-   AI infrastructure;
-   EV infrastructure;
-   telecommunications;
-   broadband;
-   semiconductor fabrication.

Typical State sequence:

``` text
Discovery
→ Early Adoption
→ Infrastructure Expansion
→ Acceleration
→ Saturation
→ Maturity
```

Common asset expressions:

-   infrastructure providers;
-   picks-and-shovels;
-   enabling technologies;
-   application layers;
-   downstream beneficiaries.

------------------------------------------------------------------------

## 8.2 Commodity Supply Cycle

A Process driven by the interaction of demand, supply, inventories,
capacity, prices, and investment.

Typical State sequence:

``` text
Weak Demand
→ Demand Recovery
→ Inventory Draw
→ Supply Tightness
→ Price Acceleration
→ Supply Response
→ Oversupply
→ Downcycle
```

Relevant variables:

-   inventory;
-   utilization;
-   spot/futures structure;
-   production;
-   capacity additions;
-   CapEx;
-   lead times;
-   pricing;
-   producer margins.

------------------------------------------------------------------------

## 8.3 Industrial Bottleneck

A Process where demand growth encounters a physical or infrastructural
constraint whose resolution requires significant time, capital, or
permitting.

Examples:

-   electrical grid capacity;
-   semiconductor fabs;
-   transmission infrastructure;
-   specialized manufacturing;
-   rare-earth processing;
-   data-center power.

Industrial Bottlenecks may overlap heavily with Commodity Supply Cycles.

The distinction is:

> **Commodity Supply Cycle** focuses primarily on supply/demand and
> price dynamics of a tradable input.

> **Industrial Bottleneck** focuses on a capacity constraint whose
> resolution requires a buildout or expansion process.

------------------------------------------------------------------------

## 8.4 Regulatory Implementation

A Process beginning with an enacted law, regulation, mandate, or
government program.

Examples:

-   emissions standards;
-   domestic sourcing requirements;
-   tax credits;
-   semiconductor subsidies;
-   permitting rules.

Typical stages:

``` text
Enactment
→ Rulemaking
→ Implementation
→ Compliance Buildout
→ Enforcement
→ Normalization
```

The system should distinguish:

-   announced policy;
-   enacted policy;
-   final rules;
-   implementation deadlines;
-   actual compliance;
-   enforcement.

------------------------------------------------------------------------

## 8.5 Business Model Disruption

A Process in which a change in technology, behavior, regulation,
economics, or social organization alters the economics of an existing
business model.

Example:

``` text
Pandemic
    ↓
Work From Home
    ↓
Teleconferencing / Telemedicine
    ↓
Migration from major cities
    ↓
Housing demand
    ↓
Construction activity
    ↓
Lumber / Copper demand
```

Business Model Disruption may therefore spawn downstream Processes.

------------------------------------------------------------------------

# 9. Drivers and Mechanisms

The system should distinguish **Drivers** from **Mechanisms**.

## Driver

A Driver is an external force that initiates or materially changes an
Economic Process.

Examples:

-   CHIPS Act;
-   AI model capability improvements;
-   government strategic-mineral policy;
-   change in consumer behavior;
-   monetary policy shock.

## Mechanism

A Mechanism is an internal economic process through which a Driver
produces downstream consequences.

Example:

``` text
CHIPS Act
    ↓
Domestic fab incentives
    ↓
Domestic fab construction
    ↓
Equipment demand
    ↓
Equipment utilization
```

A Mechanism may itself act as a Driver for a downstream Process.

This does not require creating a separate semantic class hierarchy.

Instead, Driver/Mechanism should be treated as **roles in a causal
relationship**.

A Process can be:

-   downstream of one Process;
-   upstream of another Process;
-   a Driver in one relationship;
-   a Mechanism in another.

This avoids duplicating nodes.

------------------------------------------------------------------------

# 10. Process State

Every Process has a State.

The State describes where the Process currently sits in its lifecycle
and how its observable characteristics compare with historical examples.

A State is not merely a label.

It should be represented by:

``` text
State
├── categorical_state
├── state_confidence
├── state_features
├── transition_probabilities
├── evidence
└── timestamp
```

Example:

``` text
AI Infrastructure
State: Infrastructure Expansion

Demand acceleration: 8.3
CapEx acceleration: 8.7
Supply tightness: 7.6
Capacity expansion: 7.2
Speculation: 4.1
State confidence: 0.82
```

The numerical features are quantitative observations; the LLM may help
identify which features matter and interpret them.

------------------------------------------------------------------------

# 11. Bottleneck Identification

Bottleneck Identification belongs between the Process and Capability
layers.

The Process asks:

> **What constrains further progression of this Process?**

Example:

``` text
AI Infrastructure Expansion
        ↓
Compute demand
        ↓
Power becomes limiting
        ↓
Power infrastructure Bottleneck
```

Another example:

``` text
Domestic strategic-mineral security
        ↓
Need domestic permanent-magnet supply
        ↓
Heavy rare-earth availability is constrained
        ↓
Neodymium / Dysprosium / Terbium Bottleneck
```

The Bottleneck should be explicit rather than hidden inside the Asset
selection.

------------------------------------------------------------------------

# 12. Capability Requirement

A **Capability** is a concrete economic capability required to satisfy a
Bottleneck or participate in the Process.

Examples:

-   domestic neodymium production;
-   heavy rare-earth separation;
-   advanced semiconductor fabrication;
-   HBM production;
-   electrical transmission;
-   data-center construction;
-   grid-scale generation.

A Process may require multiple Capabilities.

Importantly, these requirements can form logical structures:

``` text
Capability A AND Capability B
```

rather than merely:

``` text
Capability A OR Capability B
```

Example:

``` text
Domestic strategic-mineral security

Requires:
    Domestic production
    AND
    Relevant mineral processing
```

The system should therefore support:

-   AND requirements;
-   OR alternatives;
-   weighted requirements;
-   optional capabilities.

------------------------------------------------------------------------

# 13. Capability Confluence

Multiple upstream Processes may feed a single Capability.

Example:

``` text
AI Infrastructure ───────┐
                         │
CHIPS Act ───────────────┼──> Domestic Semiconductor Fabs
                         │
National Security ───────┘
```

This creates **confluence**.

A Capability with multiple independent upstream supporting Processes may
be more compelling than one supported by a single Process, all else
equal.

The system should therefore preserve the graph structure rather than
collapsing all supporting evidence into one thesis.

------------------------------------------------------------------------

# 14. Asset

An Asset is an investable security or underlying economic instrument
that can express a Capability or Process.

V1 should restrict trade expression to the underlying asset itself.

Examples:

-   common stock;
-   ETF;
-   commodity;
-   currency;
-   bond;
-   index.

The system does not need to solve options or complex derivatives in V1.

------------------------------------------------------------------------

# 15. Direct Event → Asset Relationships

Not every Asset must be reached through the full Process chain.

Some Events directly affect an Asset.

Example:

``` text
Event:
US Government acquires stake in MP Materials

        ↓

Asset:
MP Materials
```

This relationship should coexist with Process-based relationships:

``` text
Strategic Mineral Security
        ↓
Domestic Rare-Earth Processing
        ↓
MP Materials
```

The Asset may therefore have both:

-   direct Event exposure;
-   indirect Process exposure.

This is important for representing idiosyncratic catalysts.

------------------------------------------------------------------------

# 16. Asset State

An Asset has its own state independent of the Process.

Relevant dimensions include:

## Fundamental

-   revenue growth;
-   earnings growth;
-   free cash flow;
-   margins;
-   ROIC;
-   balance sheet;
-   CapEx;
-   operating leverage.

## Valuation

-   P/E;
-   EV/Sales;
-   EV/EBITDA;
-   FCF yield;
-   relative valuation;
-   valuation versus historical range.

## Process Exposure

-   revenue exposure;
-   incremental earnings exposure;
-   geographic exposure;
-   capacity;
-   market share;
-   production capability;
-   strategic positioning.

## Market Structure

-   institutional ownership;
-   insider ownership;
-   short interest;
-   crowding;
-   analyst positioning;
-   liquidity.

## Technical State

-   relative strength;
-   momentum;
-   volatility;
-   volatility contraction;
-   accumulation;
-   volume;
-   breakout distance;
-   moving-average structure.

These dimensions are used for **Asset Quality and Asset Ranking**, not
for determining whether the underlying Process is true.

------------------------------------------------------------------------

# 17. Thesis Quality vs Asset Quality vs Trade Quality

These should remain separate.

## Thesis Quality

Answers:

> **Is the underlying Process real, coherent, and likely to continue?**

Possible axes:

-   logical coherence;
-   accumulated evidence;
-   Process State confidence;
-   historical precedent;
-   counterfactual robustness;
-   independent evidence;
-   causal coherence;
-   contradiction;
-   uncertainty.

## Asset Quality

Answers:

> **Is this Asset a strong expression of the Process?**

Possible axes:

-   Capability fit;
-   Process exposure;
-   operating leverage;
-   first-mover advantage;
-   vertical integration;
-   market share;
-   balance sheet;
-   valuation;
-   institutional positioning;
-   technical confirmation.

## Trade Quality

Reserved for V2.

It will eventually address:

-   entry timing;
-   position sizing;
-   options;
-   convexity;
-   implied volatility;
-   strike/expiry selection;
-   risk/reward.

V1 should simply express the thesis through the underlying asset.

------------------------------------------------------------------------

# 18. Quantitative Data Architecture

Numerical documents such as earnings releases should enter through a
deterministic ETL layer.

The canonical financial data model should preserve:

``` text
metric
value
period
period_type
currency
unit
source
source_location
reported_vs_derived
restated
```

Example:

``` yaml
metric: capital_expenditure
value: 42.1
period: FY2027_Q2
unit: USD billions
source: company_filing
source_location: page 17
reported_vs_derived: reported
```

------------------------------------------------------------------------

# 19. Derived Quantitative Features

The ETL layer should deterministically compute recurring features:

### Growth

-   YoY;
-   QoQ;
-   CAGR.

### Margins

-   gross margin;
-   operating margin;
-   FCF margin.

### Ratios

-   CapEx / Revenue;
-   R&D / Revenue;
-   Net Debt / EBITDA;
-   Inventory / Revenue.

### Changes and Acceleration

-   change in growth;
-   change in margins;
-   acceleration/deceleration;
-   rolling growth.

These are derived facts, not LLM opinions.

------------------------------------------------------------------------

# 20. Quantitative Analysis Service

The Quantitative Analysis Service should have at least two modes in V1.

## 20.1 Process Quant

Question:

> **Is the Process actually developing as hypothesized?**

Examples:

-   Is hyperscaler CapEx accelerating?
-   Is commodity inventory tightening?
-   Is capacity utilization rising?
-   Are lead times increasing?
-   Is supply growth lagging demand?
-   Has a regulatory implementation process materially progressed?

Process Quant primarily performs:

-   time-series analysis;
-   industry aggregation;
-   cross-sectional analysis;
-   event studies;
-   historical state analysis.

------------------------------------------------------------------------

## 20.2 Asset Quant

Question:

> **Which assets offer the strongest expression of the Process?**

Asset Quant performs cross-sectional comparison among candidate Assets.

Example:

``` text
Asset        Exposure  Growth  Valuation  RS  Crowding
A              9.4      8.2      5.1      8.9    6.2
B              7.8      7.5      6.8      7.2    5.8
C              6.2      6.9      8.1      5.4    7.3
```

The output is a ranking supported by reproducible calculations.

------------------------------------------------------------------------

# 21. Quantitative Analysis Agent

An LLM-based Quantitative Analyst can formulate novel analyses.

Its workflow:

``` text
1. Receive analytical question
2. Translate question into formal specification
3. Identify required datasets
4. Query canonical data layer
5. Select reusable analysis template if available
6. Construct analysis
7. Execute code in sandbox when necessary
8. Validate results
9. Return structured findings
10. Store analysis, dataset version, and provenance
```

The agent may use Python/Pandas for exploratory or novel analysis, but
generated code should be treated as a computational artifact rather than
as an authoritative answer.

------------------------------------------------------------------------

# 22. Analysis Library

Repeated quantitative analyses should become reusable templates.

Examples:

-   Hyperscaler CapEx Acceleration;
-   Commodity Inventory Tightness;
-   Capacity Utilization;
-   Earnings Revision Breadth;
-   Relative Strength;
-   Price/Fundamental Divergence;
-   Institutional Accumulation;
-   Valuation Compression/Expansion;
-   Supply Growth vs Demand Growth.

The system should prefer reusable deterministic analyses over repeatedly
generating new code.

------------------------------------------------------------------------

# 23. Historical Learning Architecture

Historical learning is not:

> "Find stories that sound similar."

It is:

> **Find historical Processes that reached the same Archetype and
> Process State, then examine the Assets that were comparable at that
> point in time and measure what happened afterward.**

This requires time-indexed historical data.

------------------------------------------------------------------------

# 24. Historical Process Timeline

A historical Process should be represented as a time series of States.

Example:

``` text
Cloud Computing

2006  Discovery
2008  Early Adoption
2010  Infrastructure Expansion
2012  Acceleration
2014  Maturity
2016  Saturation
```

The current system might classify:

``` text
AI Infrastructure
2026
Infrastructure Expansion
```

The analog engine searches for historical Process episodes whose States
align with the current State.

------------------------------------------------------------------------

# 25. Historical State Snapshot

A **Historical State Snapshot** is a point-in-time representation of a
historical Process.

``` text
HistoricalStateSnapshot
├── process_id
├── archetype
├── state
├── state_confidence
├── observation_date
├── process_features
├── bottleneck
├── capabilities
├── market_regime
└── supporting_evidence
```

This is the unit used for historical analog retrieval.

------------------------------------------------------------------------

# 26. Historical Capability Snapshot

Within a Historical State Snapshot, the system identifies the
Capabilities relevant to that Process.

Example:

``` text
Cloud Infrastructure Expansion

Capabilities:
- servers
- networking
- storage
- data centers
- cloud software
```

The current Process might have:

``` text
AI Infrastructure Expansion

Capabilities:
- compute
- networking
- memory
- data centers
- power
```

The system then establishes structural correspondences between
Capabilities.

------------------------------------------------------------------------

# 27. Historical Asset Snapshot

For every relevant historical Asset, the system stores its
characteristics **as they were observable at that time**.

``` text
HistoricalAssetSnapshot
├── asset_id
├── observation_date
├── capability
├── exposure
├── market_cap
├── revenue_growth
├── earnings_growth
├── valuation
├── margins
├── balance_sheet
├── ownership
├── technicals
├── liquidity
└── other point-in-time features
```

The system must never use later information when constructing the
historical snapshot.

------------------------------------------------------------------------

# 28. Historical Outcome

The eventual outcome is stored separately.

``` text
HistoricalOutcome
├── asset_id
├── observation_date
├── return_1m
├── return_3m
├── return_6m
├── return_12m
├── return_24m
├── maximum_upside
├── maximum_drawdown
└── other outcomes
```

This separation creates a clean boundary:

``` text
Information available at t
        ↓
Historical Asset Snapshot
        ↓
Subsequent Outcome
```

------------------------------------------------------------------------

# 29. State-Conditioned Asset Episode

This is the core historical learning object.

``` text
State-Conditioned Asset Episode
│
├── Process Archetype
├── Process State
├── Process Features
├── Bottleneck
├── Capability
├── Asset
├── Asset Features @ t
├── Market Regime @ t
├── Observation Date
│
└── Subsequent Outcomes
    ├── 1M
    ├── 3M
    ├── 6M
    ├── 12M
    ├── 24M
    └── Max Drawdown / Max Upside
```

The forecasting engine retrieves episodes similar to the current
situation.

------------------------------------------------------------------------

# 30. Historical Analog Retrieval

Analog retrieval should operate hierarchically.

## Level 1 --- Same Archetype, Same State

Highest relevance.

``` text
Infrastructure / S-Curve
→ Infrastructure Expansion
```

## Level 2 --- Same Archetype, Adjacent State

Useful when exact examples are sparse.

``` text
Infrastructure / S-Curve
→ Early Adoption
→ Infrastructure Expansion
→ Acceleration
```

## Level 3 --- Different Archetype, Similar Structural Dynamics

Example:

``` text
Rapid demand growth
+
Supply constraint
+
Long capacity buildout
```

This may retrieve analogous commodity or industrial episodes.

## Level 4 --- Broad Base Rate

Use only when more specific analogs are unavailable.

------------------------------------------------------------------------

# 31. Analog Similarity

Historical analogs should be ranked by structured similarity rather than
narrative resemblance alone.

Example:

``` text
Archetype match             1.00
State match                 0.93
Demand acceleration         0.89
CapEx acceleration          0.91
Supply tightness            0.82
Bottleneck similarity       0.78
Market penetration          0.71
Valuation regime            0.63
```

An overall analog quality score should be accompanied by its component
dimensions.

The system should not hide low-quality analogs behind a single
high-level score.

------------------------------------------------------------------------

# 32. Historical Asset Matching

After identifying a comparable historical Process State, the system
searches for Assets that resemble the current candidate.

The comparison should consider:

-   Capability;
-   exposure;
-   market share;
-   operating leverage;
-   capital intensity;
-   valuation;
-   growth;
-   balance sheet;
-   competitive position;
-   technical state;
-   market structure.

The key question is:

> **What assets looked like this current asset at the equivalent
> historical Process State?**

Not:

> "Which companies eventually became winners?"

------------------------------------------------------------------------

# 33. Anti-Hindsight / Point-in-Time Rule

This is a non-negotiable design constraint.

When reconstructing a historical episode, every feature used for:

-   Process classification;
-   State classification;
-   Capability identification;
-   Asset selection;
-   Asset ranking;

must be information that would have been available at the historical
observation date.

Forbidden:

> "Amazon was the best cloud company because AWS eventually became
> enormous."

Permitted:

> "As of 2010, Amazon had these observable growth, valuation, CapEx,
> technical, and competitive characteristics."

Only after the historical snapshot is frozen may the system measure
subsequent performance.

This prevents look-ahead bias and hindsight selection.

------------------------------------------------------------------------

# 34. Current-State Forecasting

The current system first constructs a current State representation.

Example:

``` text
AI Infrastructure

State:
Infrastructure Expansion

Demand acceleration:      8.3
CapEx acceleration:       8.7
Supply tightness:         7.6
Capacity expansion:       7.2
Speculation:              4.1
```

The historical retrieval system then finds State-Conditioned Asset
Episodes with similar characteristics.

------------------------------------------------------------------------

# 35. Empirical Conditional Distribution

Suppose comparable historical episodes produced:

``` text
-17%
-8%
+4%
+11%
+16%
+21%
+25%
+31%
+34%
+42%
+58%
+71%
+94%
```

The system can report an empirical conditional distribution:

``` text
12M historical conditional distribution

P25: +11%
P50: +25%
P75: +42%
P90: +71%

P(positive): 84%
P(>25%):    50%
P(>50%):    17%
```

The wording should initially be:

> "Among historically comparable situations, the subsequent 12-month
> return distribution was..."

rather than:

> "There is an 84% probability the asset will rise."

The latter should only be used after sufficient calibration and
statistical validation.

------------------------------------------------------------------------

# 36. Forecast Horizons

V1 should use standardized horizons:

``` text
1 month
3 months
6 months
12 months
24 months
```

Each horizon may contain:

-   empirical median return;
-   quantiles;
-   probability of positive return;
-   probability of \>20% return;
-   probability of \>50% return;
-   probability of \>100% return;
-   probability of severe loss;
-   maximum historical drawdown;
-   maximum historical upside.

The purpose is to preserve the shape of the distribution rather than
collapse it into a single expected-return number.

------------------------------------------------------------------------

# 37. Tail-Aware Forecasting

The system is specifically intended to identify asymmetric
opportunities.

Therefore it should track the right tail.

Example:

``` text
Asset A
P(positive): 82%
Median: +18%
P(>50%): 15%
P(10x): 0.1%

Asset B
P(positive): 57%
Median: +12%
P(>50%): 31%
P(10x): 4.2%
```

Asset A is the more consistent outcome.

Asset B may be the more interesting speculative opportunity.

A single scalar expected return would obscure this distinction.

------------------------------------------------------------------------

# 38. Process Trajectories

Eventually, Process State itself should be modeled as a transition
system.

Example:

``` text
Infrastructure Expansion
        │
        ├──> Continued Expansion
        ├──> Acceleration
        ├──> Saturation
        └──> Failure / Reversal
```

Each possible trajectory can imply different Asset outcomes.

The eventual architecture may therefore become:

``` text
Current Process State
        ↓
Historical State Transitions
        ↓
Conditional Asset Outcomes
        ↓
Mixture Distribution
```

This is a V2/V3 direction rather than a V1 requirement.

------------------------------------------------------------------------

# 39. V1 vs V2 Scope

## V1

Implement:

``` text
Document
→ Claim
→ Event
→ Process
→ Process State
→ Bottleneck
→ Capability
→ Asset
→ Asset Quant
→ Historical State Snapshot
→ Historical Asset Snapshot
→ Historical Outcome
→ State-Conditioned Asset Episodes
→ Empirical return distributions
```

Trade expression:

> **Underlying asset only.**

## V2

Potentially add:

-   options;
-   LEAPS;
-   spreads;
-   implied volatility;
-   convexity;
-   optimal expiry;
-   position sizing;
-   trade-specific probability distributions;
-   conditional Process transition models;
-   scenario mixtures;
-   dynamic trajectory distributions.

Trade Quant should remain outside V1 because it introduces a
significantly more difficult conditional probability and
instrument-optimization problem.

------------------------------------------------------------------------

# 40. Forecast Evolution Through Time

Every forecast should be timestamped.

Example:

``` text
July 2026

12M MSFT:
P50 +18%
P90 +51%
```

Later:

``` text
October 2026

12M MSFT:
P50 +31%
P90 +74%
```

Later:

``` text
January 2027

12M MSFT:
P50 +47%
P90 +110%
```

The SaaS can visualize the movement of the empirical forecast
distribution over time.

This allows users to see:

> **When did the system's assessment of the opportunity materially
> change?**

rather than evaluating the system only after the outcome is known.

------------------------------------------------------------------------

# 41. Calibration

The system should eventually test whether its empirical forecasts are
calibrated.

If the system repeatedly identifies outcomes with:

``` text
P(positive) = 70%
```

then approximately 70% of comparable outcomes should be positive,
subject to sample size and appropriate conditioning.

Likewise:

``` text
P(>50%) = 10%
```

should eventually correspond to approximately 10% of comparable outcomes
exceeding +50%.

Tail calibration is especially important for the system's goal of
discovering extreme winners.

------------------------------------------------------------------------

# 42. Thesis Quality Scoring

Thesis Quality should remain multidimensional rather than being reduced
immediately to one probability.

Candidate dimensions:

``` text
Logical Coherence
Accumulated Evidence
Process State Confidence
Historical Precedent
Counterfactual Robustness
Independent Evidence
Causal Coherence
Contradictory Evidence
Uncertainty
```

Each may be scored on a 0--10 scale.

The system should preserve the underlying dimensions even if a composite
score is eventually calculated.

------------------------------------------------------------------------

# 43. Asset Ranking

Asset ranking is distinct from Thesis Quality.

For a given Process/Capability, Asset Quant may evaluate:

``` text
Capability Fit
Process Exposure
Operating Leverage
First-Mover Advantage
Vertical Integration
Market Share
Financial Quality
Valuation
Balance Sheet
Institutional Positioning
Crowding
Relative Strength
Technical Confirmation
```

The ranking should be comparative across the relevant Asset universe.

The system should be able to explain why Asset A outranks Asset B.

------------------------------------------------------------------------

# 44. Direct and Indirect Evidence

An Asset can receive evidence from multiple paths.

Example:

``` text
Event:
Government buys MP Materials
        │
        └──────────────> MP Materials

Process:
Strategic Mineral Security
        ↓
Domestic Rare-Earth Processing
        ↓
MP Materials
```

Both relationships should be retained.

This permits the system to identify **confluence**:

> Multiple independent upstream Processes converge on the same Asset or
> Capability.

------------------------------------------------------------------------

# 45. Evidence Attribution

Every material statement in a Process, Asset analysis, or thesis should
be traceable.

For textual claims:

``` text
Thesis Statement
    ↓
Claim
    ↓
Event
    ↓
Document
    ↓
Source Location
```

For quantitative claims:

``` text
Thesis Statement
    ↓
Quantitative Analysis
    ↓
Derived Metric
    ↓
Source Data
    ↓
Original Document / Dataset
```

The user should be able to drill from a thesis statement to its
supporting evidence.

------------------------------------------------------------------------

# 46. Update Architecture

The system should not immediately propagate every document through the
entire graph.

Instead:

``` text
Documents
    ↓
Claims
    ↓
Event clustering / deduplication
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

Events should accumulate documents for a period or until a materiality
threshold is reached.

Processes should then be updated in batches or when a meaningful delta
occurs.

Assets should likewise be updated periodically or when relevant
Process/Asset state changes materially.

This reduces unnecessary LLM calls while preserving provenance.

------------------------------------------------------------------------

# 47. Evidence Deduplication

Multiple documents may represent the same Event.

The system should cluster evidence before propagation.

Possible similarity dimensions:

-   entities;
-   timestamp;
-   event type;
-   semantic similarity;
-   factual overlap;
-   source independence.

The system should distinguish:

``` text
20 articles repeating the same Reuters report
```

from:

``` text
20 independent sources reporting independently observed developments
```

The first should not count as 20 independent pieces of evidence.

------------------------------------------------------------------------

# 48. Summary Objects

Each Process and Asset should maintain a current structured summary.

A Process Summary should contain:

``` text
Current State
State confidence
Key supporting evidence
Contradictory evidence
Bottleneck
Capabilities
Historical analogs
Quantitative confirmation
Recent state change
```

An Asset Summary should contain:

``` text
Relevant Processes
Capability exposure
Fundamental state
Valuation
Technical state
Market structure
Quantitative ranking
Historical asset analogs
Expected empirical return distributions
```

These summaries become the input to downstream agents and the primary
human-readable representation of the system's current state.

------------------------------------------------------------------------

# 49. End-to-End Architecture

The resulting architecture is:

``` text
                           DOCUMENTS
                               │
                    ┌──────────┴──────────┐
                    │                     │
                TEXTUAL               NUMERICAL
                    │                     │
                    ▼                     ▼
               Extraction              ETL
                    │                     │
                    ▼                     ▼
                 Claims            Canonical Data
                    │                     │
                    ▼                     │
                 Events                  │
                    │                     │
             Event Deduplication         │
                    │                     │
                    └──────────┬──────────┘
                               ▼
                        ECONOMIC PROCESSES
                               │
                         Process State
                               │
                               ▼
                      BOTTLENECK IDENTIFIER
                               │
                               ▼
                     CAPABILITY REQUIREMENTS
                               │
                  ┌────────────┴────────────┐
                  │                         │
          Current Asset Universe      Historical Episodes
                  │                         │
                  ▼                         ▼
              ASSET QUANT          Historical State Alignment
                  │                         │
                  │                         ▼
                  │                 Historical Asset Matching
                  │                         │
                  │                         ▼
                  │                 Subsequent Outcomes
                  │                         │
                  └────────────┬────────────┘
                               ▼
                  EMPIRICAL CONDITIONAL
                    ASSET DISTRIBUTION
                               │
                               ▼
                         ASSET RANKING
                               │
                               ▼
                    UNDERLYING EXPRESSION
```

------------------------------------------------------------------------

# 50. The Fundamental Forecasting Loop

The entire system can ultimately be summarized as:

``` text
                 CURRENT WORLD
                      │
                      ▼
               Process Detection
                      │
                      ▼
             Archetype Classification
                      │
                      ▼
                State Estimation
                      │
                      ▼
             State Characterization
                      │
                      ▼
             Historical Retrieval
                      │
                      ▼
         Comparable Historical States
                      │
                      ▼
           Historical Asset Matching
                      │
                      ▼
             Subsequent Outcomes
                      │
                      ▼
       Empirical Conditional Distribution
                      │
                      ▼
              Current Asset Ranking
                      │
                      ▼
              Underlying Expression
```

The key conceptual division is:

**LLM layer:**\
What is happening? What Process is this? What State are we in? What
Bottleneck and Capabilities follow?

**Quantitative layer:**\
Do the observable numbers support that characterization?

**Historical layer:**\
What happened when comparable Processes reached comparable States?

**Asset layer:**\
Which Assets were the best expressions in those historical situations,
and which current Assets resemble those historical winners?

**Calibration layer:**\
When the system made similar assessments in the past, how well did its
empirical distributions correspond to realized outcomes?

------------------------------------------------------------------------

# 51. Core Ontological Insight

The system should not treat a stock as the fundamental object of
investment analysis.

The hierarchy is:

``` text
WORLD
  ↓
ECONOMIC PROCESSES
  ↓
PROCESS STATES
  ↓
BOTTLENECKS
  ↓
CAPABILITIES
  ↓
ASSETS
  ↓
RETURNS
```

A stock is therefore an **investable projection of an underlying latent
economic state**.

The purpose of the system is to identify the latent state early,
determine where value or constraint is accumulating, identify the
relevant Capabilities, and then find Assets whose characteristics
provide unusually strong exposure to the developing Process.

Historical learning adds a final constraint:

> **The system should not invent the expected trajectory from language.
> It should search history for situations in which the world previously
> looked like this, align those situations to the same Process State,
> examine the Assets that were available at that moment, and use their
> subsequent outcomes as the empirical basis for the current forecast.**

That is the central architecture of the research system.
