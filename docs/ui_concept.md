# Investment Intelligence Platform — UI/UX Technical Design

**Audience:** Senior engineers, technical leads, product architects, and frontend/backend engineers  
**Status:** Design specification / implementation planning  
**Scope:** SaaS user interface and interaction model for the Economic Process → Bottleneck → Capability → Asset → Trade research system

---

## 1. Executive Summary

The product should not be designed as a generic AI chatbot that happens to discuss investments.

Its primary abstraction is the **Economic Process**: a persistent, evolving representation of an underlying economic, technological, regulatory, industrial, commodity, or market process. Assets are downstream expressions of those processes rather than the fundamental unit of analysis.

The UI therefore needs to let a user move naturally through:

> **World → Process → State → Bottleneck → Capability → Asset → Trade**

The five principal user journeys are:

1. **Discover** — find emerging or accelerating Processes.
2. **Track** — observe how a Process evolves through States over time.
3. **Research** — investigate the implications of a Process and its downstream graph.
4. **Underwrite** — construct an investment case for a particular Asset.
5. **Monitor** — determine whether an existing thesis/trade is developing as expected.

The application should combine:

- a research terminal,
- an interactive knowledge graph,
- an evidence database,
- a historical analogue engine,
- quantitative asset analysis,
- a thesis journal,
- and a natural-language research interface.

The LLM should primarily function as a **reasoning and navigation layer over structured data**, not as an ungrounded investment-answer generator.

---

# 2. Core Product Principles

## 2.1 Process-first, Asset-second

The default research flow should begin with:

> What is changing?

rather than:

> What stock should I buy?

An Asset becomes relevant because it is an investable expression of one or more Processes and Capabilities.

---

## 2.2 Every important conclusion must be inspectable

A user should be able to move from:

**score → component → evidence → source document → extracted statement**

without losing context.

No important score should appear as an unexplained black box.

---

## 2.3 Temporal state is first-class

The system is not merely storing facts. It is modeling how Processes evolve.

Therefore the UI must expose:

- current State,
- State history,
- evidence accumulation,
- State transitions,
- rate of change,
- historical analogues,
- and the dates at which the system knew each fact.

---

## 2.4 Thesis quality and trade quality remain separate

The UI must never collapse these into one opaque "investment score."

### Thesis quality

Measures the strength of the underlying Process:

- logical coherence,
- accumulated evidence,
- historical precedent,
- State confidence,
- counterfactual robustness,
- evidence independence,
- etc.

### Asset/trade quality

Measures the quality of expressing that Process through an Asset:

- Process exposure,
- Capability exposure,
- fundamentals,
- first-mover advantage,
- vertical integration,
- market share,
- valuation,
- institutional ownership,
- crowding,
- technical behavior,
- liquidity,
- etc.

A very strong Process can have mediocre Asset expressions.

A high-quality Asset can also be exposed to a weak or deteriorating Process.

---

## 2.5 Chat is an interface, not the product

Natural-language interaction should be deeply integrated, but the product should not reduce to a chat window.

The graph, timelines, scores, evidence, and comparisons are the durable product state.

Chat should help users:

- query the graph,
- explain scores,
- navigate relationships,
- generate research questions,
- summarize evidence,
- investigate counterarguments,
- and construct reports.

---

# 3. Primary Navigation

Recommended application shell:

```text
┌─────────────────────────────────────────────┐
│ LOGO       Global Search / Ask Research     │
├──────────────┬──────────────────────────────┤
│              │                              │
│ DISCOVER     │                              │
│ Processes    │                              │
│ Capabilities │       Application View       │
│ Assets       │                              │
│              │                              │
│ MY RESEARCH  │                              │
│ Watchlist    │                              │
│ Processes    │                              │
│ Assets       │                              │
│ Trades       │                              │
│              │                              │
│ RESEARCH     │                              │
│ Historical   │                              │
│ System Stats │                              │
│              │                              │
└──────────────┴──────────────────────────────┘
Primary navigation
Discover
Processes
Capabilities
Assets
Watchlist
My Processes
My Assets
My Trades
Historical Analogs
System Performance

A persistent global search should be available from every screen.

---

# 4. Global Search / Research Command Bar

The command bar should understand ontology-aware natural language.

Examples:

"Show me emerging infrastructure Processes."
"What Capabilities are downstream of AI infrastructure?"
"Which Assets have exposure to both AI and grid modernization?"
"Which Processes are transitioning from adoption to infrastructure expansion?"
"Find regulatory Processes with strong historical precedent."
"Which Assets have high Process exposure but low market attention?"
"Show historical analogues where regulatory implementation created a commodity bottleneck."
"Why did the confidence of this Process increase yesterday?"

The system should translate natural-language queries into structured graph/filter operations where possible.

The LLM should not invent the underlying data.

---

# 5. Home / Discover Screen

The home screen should answer:

What is changing in the economic state space?

It should not primarily be a portfolio dashboard.

5.1 Emerging Process panel

Display Processes ranked by a combination of:

State confidence,
evidence acceleration,
recent State change,
affected Capability count,
Asset breadth,
historical analogue strength,
market attention,
and novelty.

Example:

Process	State	Evidence Δ	Confidence	Attention
AI Infrastructure	Expansion	+12	8.2	High
Domestic Rare Earth Security	Expansion	+9	7.9	Medium
Grid Modernization	Acceleration	+8	7.6	Medium
Protectionism	Implementation	+14	8.1	High
---

## 5.2 Emergence Radar

A scatter plot can show:

X = Process maturity
Y = evidence acceleration
bubble size = economic scope
bubble opacity = market attention

The purpose is to identify Processes where evidence is accelerating before attention has fully caught up.

This should be treated as a discovery visualization, not a predictive claim.

---

## 5.3 Hot Process Cards

Each card should include:

Process name
Archetype
Current State
State confidence
Evidence momentum
Historical precedent
Contradictory evidence
Major Bottlenecks
Number of downstream Capabilities
Number of candidate Assets

Example:

DOMESTIC RARE EARTH SECURITY

State: Infrastructure Expansion
Confidence: 8.1 / 10
Evidence momentum: ↑↑
Historical precedent: 7.4 / 10

Bottlenecks
• Heavy rare earth separation
• Processing
• Permanent magnets

Capabilities
Nd production · Dy/Tb supply · separation · magnets

Assets
12 candidate Assets

---

# [Open Process]
6. Process Screen

The Process screen is one of the central product views.

It should provide four synchronized perspectives:

Overview
State evolution
Evidence timeline
Dependency graph
---

## 6.1 Process Header

Example:

AI INFRASTRUCTURE

Archetype: Infrastructure / S-Curve Adoption
Current State: Infrastructure Expansion

State Confidence        8.3 / 10
Evidence Momentum       ↑↑
Historical Precedent    8.1 / 10
Counterfactual Robust.  7.2 / 10

[Track Process] [Research] [View Graph]
---

## 6.2 State History

Show the evolution of the Process through its defined State machine.

Example:

Discovery
   │
   ▼
Early Adoption
   │
   ▼
Acceleration
   │
   ▼
Infrastructure Expansion  ← CURRENT
   │
   ▼
Saturation
   │
   ▼
Maturity

The interface should record the date and confidence associated with each transition.

---

## 6.3 State Distribution

Where probabilistic/state-distribution modeling is available, display a distribution.

Example:

Discovery              4%
Early Adoption        11%
Acceleration          15%
Infrastructure        68%  ← current
Saturation              2%

Until the model is properly calibrated, this should be labeled something such as:

State distribution
State confidence
Model belief

rather than implying statistically calibrated probabilities.

---

# 7. Evidence Timeline

Every Process should have an evidence timeline.

Example:

2024 ───────── 2025 ───────── 2026

  Regulation
       │
       ├── CapEx acceleration
       │
       ├──── Government investment
       │
       ├──────── Capacity announcement
       │
       └──────────── Bottleneck worsening

Each evidence item should be clickable.

The user should be able to inspect:

source,
publication date,
event date,
extracted statement,
source type,
evidence polarity,
confidence,
novelty/deduplication status,
and which Process update it influenced.
---

# 8. Explainable Score Decomposition

Any aggregate score should have an Explain affordance.

Example:

THESIS QUALITY: 8.4 / 10

Logical Coherence           8.7
Accumulated Evidence        9.1
Historical Precedent        7.6
Counterfactual Robustness   6.9
Evidence Independence       8.4
State Confidence            8.3

Clicking a dimension should expose its underlying reasoning and evidence.

For example:

ACCUMULATED EVIDENCE: 9.1

Supporting evidence
+ Government investment
+ New capacity commitments
+ Regulatory implementation
+ Utility CapEx

Contradictory evidence
− Cost inflation
− Project delays

Evidence sources: 27
Independent event clusters: 11

[View Evidence]

This is critical to user trust.

---

# 9. Process Graph

The graph view should expose relationships without overwhelming the user.

Recommended hierarchy:

             UPSTREAM PROCESSES
                     │
                     ▼
                 PROCESS
                     │
                     ▼
                BOTTLENECK
                     │
                     ▼
                CAPABILITY
                     │
                     ▼
                   ASSET
                     │
                     ▼
                  TRADE

The user should be able to expand one or two hops at a time.

Do not render the entire graph by default.

---

## 9.1 Relationship semantics

Edges should be typed.

Examples:

Process → influences → Process
Process → creates → Bottleneck
Bottleneck → requires → Capability
Capability → expressed by → Asset
Asset → used for → Trade

The visual language should make these distinctions clear.

---

# 10. Bottleneck View

Because Bottleneck Identification is a distinct layer, it should have its own UI.

Example:

AI INFRASTRUCTURE

Bottleneck: GRID CAPACITY

Demand pressure          9.1
Supply elasticity         4.2
Time to expand            8.8
Current constraint        8.6

Required Capabilities

• Transmission
• Transformers
• Generation
• Interconnection

A Bottleneck page should answer:

What prevents the Process from scaling?

This is often more actionable than the Process itself.

---

# 11. Capability Explorer

Capabilities are the bridge between economic Processes and investable Assets.

Example:

CAPABILITY: HEAVY RARE EARTH SEPARATION

Upstream Processes
• Domestic Rare Earth Security
• Defense Supply Chain Resilience
• China Supply Risk

Bottlenecks
• Processing capacity
• Specialized equipment
• Refining expertise

Assets
• Asset A
• Asset B
• Asset C

The user should be able to select multiple upstream Processes and find their confluence.

Example:

Process A ─────┐
               ├──► Capability X
Process B ─────┘

This supports AND relationships rather than forcing everything into OR-style exposure.

---

# 12. Asset Discovery

When a user reaches an Asset from a Process, the system should explicitly explain why it appears.

Example:

ASSET: COMPANY X

Process Exposure
AI Infrastructure             8.9
Grid Modernization             7.7
Electrification                6.8

Capability Exposure
Transformer Manufacturing      9.2
Grid Equipment                 8.6

Expression Quality             8.1

The UI should show the chain:

AI Infrastructure
       +
Grid Modernization
       ↓
Grid Capacity Bottleneck
       ↓
Transformer Capability
       ↓
Company X
---

# 13. Asset Comparison Screen

This is where Asset-level quantitative analysis belongs.

The interface should support side-by-side comparisons.

Dimension	Asset A	Asset B	Asset C
Process Exposure	9.2	8.4	9.6
Capability Exposure	9.5	7.8	9.7
Asset Quality	8.7	9.1	6.8
Valuation	6.1	8.2	4.2
Technicals	8.4	7.6	9.0
Crowding	5.7	8.0	4.9
Overall Expression	8.4	8.2	7.9

The interface should allow users to change ranking weights without changing the underlying scores.

---

# 14. Asset Underwriting Screen

Entering an Asset should open a structured investment case.

---

## 14.1 Why this Asset?

Show:

upstream Processes,
Bottlenecks,
Capabilities,
Asset-specific advantages,
financial exposure,
and historical analogues.
14.2 Why now?

Show evidence of Process-State transition.

Example:

WHY NOW?

Process State
Adoption → Acceleration → Infrastructure Expansion

Recent evidence
+ CapEx acceleration
+ Regulatory implementation
+ Capacity constraints
+ Demand expansion

Historical analogues
3 comparable Process episodes
---

## 14.3 Why not?

The interface must explicitly surface disconfirming evidence.

COUNTERARGUMENTS

1. Valuation already reflects expected growth.
2. New capacity could resolve the bottleneck.
3. Historical analogue has a materially different regulatory regime.
4. Demand may normalize earlier than expected.
---

# 15. Historical Analogue Interface

Historical analogues should not simply be a list of similar companies.

The system should compare:

Process archetype + Process State + economic conditions + Asset characteristics

Example:

CURRENT PROCESS
AI Infrastructure
State: Infrastructure Expansion

Historical analogue
Mobile Infrastructure
State: Infrastructure Expansion
2004–2007

Then compare:

Process State,
evidence trajectory,
bottlenecks,
affected capabilities,
asset characteristics,
valuation,
market attention,
subsequent returns.

The user should be able to scrub through the historical episode.

---

# 16. "Thesis Replay"

A major product feature should be a temporal replay.

Example:

2022
Discovery
      ↓
2023
Early Adoption
      ↓
2024
Acceleration
      ↓
2025
Infrastructure Expansion
      ↓
2026
Current State

As the user scrubs the timeline, update:

Process score,
State,
evidence,
Bottlenecks,
Capabilities,
candidate Assets,
Asset prices,
and eventual outcomes where historically available.

This serves both research and system validation.

---

# 17. "Find the Next NVIDIA" / Extreme Opportunity Discovery

This should not be implemented as a simple stock similarity search.

The correct abstraction is:

Historical Extreme Winner
        ↓
Process Archetype
        ↓
Process State
        ↓
Characteristic configuration
        ↓
Current Process search
        ↓
Candidate Assets

The user could ask:

Find current Processes that resemble the early-stage configuration preceding historical extreme winners.

The system should return:

Process	Archetype	State	Evidence	Analog Strength
Process A	Infrastructure	Expansion	8.2	8.7
Process B	Commodity	Tightening	7.8	8.1
Process C	Regulatory	Implementation	7.4	7.9

This should be presented as pattern discovery, not a promise of future 10x returns.

---

# 18. Trade Monitoring

Trade monitoring should monitor the reason for owning the Asset, not merely price.

Example:

TRADE: COMPANY X

Position
Entry: $80
Current: $97
Return: +21%

THESIS STATUS

Process                🟢 Strengthening
Bottleneck             🟢 Persistent
Capability             🟢 Expanding
Asset Exposure         🟢 Intact
Asset Quality          🟢 Intact
Valuation              🟡 Elevated
Technicals             🟢 Positive

This lets users distinguish:

"The stock is falling"

from:

"The thesis is deteriorating."

---

# 19. Thesis Invalidation Alerts

Alerts should be thesis-aware.

Bad alert:

XYZ down 5%.

Better alert:

Bottleneck potentially resolving. New transformer capacity announcements suggest the identified constraint may be easing faster than expected.

Better still:

Thesis contradiction detected. Three independent event clusters now contradict the assumption that domestic transformer supply remains structurally constrained.

Potential alert classes:

Process State transition
Evidence acceleration
Evidence deterioration
Bottleneck resolution
New Bottleneck
Capability expansion
Capability contraction
Asset exposure change
Fundamental deterioration
Valuation regime change
Technical confirmation
Technical invalidation
Historical analogue divergence
---

# 20. Thesis Journal

Every Process, Asset, and monitored Trade should maintain a persistent journal.

Example:

AI POWER INFRASTRUCTURE

2026-06-12
State confidence: 7.2 → 7.8

Reason
+ New utility CapEx plans
+ Interconnection queue acceleration
+ Nuclear PPAs

2026-06-27
State confidence: 7.8 → 7.5

Reason
− Natural gas capacity additions
− Data-center construction slowdown

2026-07-14
State confidence: 7.5 → 8.1

Reason
+ Transformer shortage worsening
+ Utility rate-base expansion

Every entry should link to the underlying evidence and model version that produced it.

This creates a complete audit trail.

---

# 21. Research Workspace

Users should be able to create a persistent research workspace around a Process or Asset.

A workspace might contain:

selected Processes,
selected Assets,
evidence,
notes,
charts,
historical analogues,
counterarguments,
generated reports,
and user annotations.

The workspace should preserve ontology links rather than flattening everything into a document.

---

# 22. Natural-Language Research Assistant

The assistant should be context-aware.

Inside a Process page:

"Why did confidence increase this week?"

Inside an Asset page:

"Which assumptions about the upstream Process are most important to this company?"

Inside a Trade page:

"What changed since I entered?"

Inside Historical Analogs:

"What distinguishes this historical episode from the current one?"

The assistant should answer from retrieved structured context and evidence.

---

# 23. "Explain" as a Universal UI Primitive

Every important object should have:

[Explain]

This should work on:

scores,
State assignments,
Asset rankings,
Process relationships,
historical analogue matches,
alerts,
and recommendations.

The explanation should include:

conclusion,
supporting factors,
contradictory factors,
source evidence,
model version,
timestamp,
confidence/uncertainty.
---

# 24. System Performance Dashboard

The system should expose its own performance.

Example:

SYSTEM PERFORMANCE

Process Identification
Precision                    74%
Recall                       68%

State Prediction
12M State Accuracy           71%

Asset Ranking
Information Coefficient      0.08
Top Decile Excess Return     +11.4%

Extreme Opportunity Discovery
>100% Winners Identified     14 / 31
False Positive Rate          27%

Then break performance down by Archetype:

Archetype	State Accuracy	Asset IC	Extreme Winner Recall
Infrastructure	78%	.11	42%
Commodity	69%	.07	31%
Regulatory	74%	.09	36%
Business Disruption	61%	.04	18%

This prevents the system from presenting itself as uniformly predictive.

---

# 25. Process Screener

The Process screener should be analogous to a stock screener.

Example filters:

Archetype               Infrastructure
State                   Expansion
State Confidence        > 7
Evidence Acceleration   > 75th percentile
Historical Precedent    > 7
Counterfactual Risk     < 5
Market Attention        < 50th percentile
Affected Assets         > 5

Output:

Process,
State,
confidence,
acceleration,
Bottlenecks,
Capability count,
market attention,
candidate Assets.

This is likely to become one of the highest-value discovery tools.

---

# 26. Notifications / Alert Center

Alerts should be grouped by semantic importance rather than chronologically only.

Process Alerts
State transition
Evidence acceleration
Evidence deterioration
Bottleneck Alerts
Bottleneck emerging
Bottleneck intensifying
Bottleneck resolving
Capability Alerts
Capacity expansion
Supply disruption
Pricing change
Asset Alerts
Fundamental change
Exposure change
Technical confirmation
Valuation regime change
Thesis Alerts
Thesis strengthening
Thesis weakening
Thesis contradiction
Thesis invalidation
---

# 27. Mobile vs Desktop

The core application should be desktop-first.

The graph, timelines, comparisons, and research workspace require significant screen real estate.

Mobile should prioritize:

alerts,
Process snapshots,
Asset monitoring,
saved research,
quick evidence review,
and conversational queries.

Mobile should not attempt to reproduce the full graph workspace.

---

# 28. Visualization System

The product should use a small number of reusable visual primitives.

Required primitives
Process Timeline

Shows State and evidence through time.

State Distribution

Shows current model belief across Process States.

Evidence Timeline

Shows event/evidence accumulation.

Dependency Graph

Shows typed ontology relationships.

Emergence Radar

Shows Process maturity vs evidence acceleration.

Asset Comparison Matrix

Shows Asset expression quality.

Historical Replay

Synchronizes Process State and Asset performance through time.

Thesis Scorecard

Shows multidimensional quality.

Thesis Journal

Shows score changes and reasons over time.

Avoid introducing custom visualization types for every feature.

---

# 29. UX for Evidence Provenance

Evidence provenance is a core trust mechanism.

Every generated statement should be capable of displaying:

CLAIM

"Domestic heavy rare-earth supply remains constrained."

Evidence
├── Source A
├── Source B
├── Source C

Event clusters
├── Event 102
└── Event 118

Extraction timestamp
2026-08-05 14:31 UTC

Model
ResearchAgent v1.7

Confidence
0.84

The user should be able to inspect the original document.

Evidence should never be represented merely as an undifferentiated "AI summary."

---

# 30. Technical Architecture Implications

The UI should consume a structured API rather than calling LLMs directly.

Recommended conceptual layers:

Frontend
   │
   ▼
API / BFF
   │
   ├── Process Service
   ├── Evidence Service
   ├── Graph Service
   ├── Asset Service
   ├── Quant Service
   ├── Historical Analogue Service
   ├── Alert Service
   └── Research/LLM Service

The frontend should not know how an LLM generated a Process score.

It should request:

GET /processes/{id}
GET /processes/{id}/timeline
GET /processes/{id}/evidence
GET /processes/{id}/graph
GET /processes/{id}/capabilities
GET /processes/{id}/assets
GET /processes/{id}/historical-analogs
31. Event-Driven UI Updates

The backend architecture is asynchronous, so the UI should support asynchronous updates.

Examples:

Document ingested
       ↓
Event updated
       ↓
Process updated
       ↓
Capability exposure changed
       ↓
Asset ranking changed
       ↓
Alert generated

The frontend should receive update notifications rather than requiring a full page refresh.

Potential implementation:

WebSockets
Server-Sent Events
or a polling fallback.
---

# 32. Versioning and Reproducibility

Every material UI-visible conclusion should be associated with:

timestamp,
data version,
model version,
prompt/agent version where relevant,
and calculation version.

A user should be able to answer:

"Why did the system believe this on July 14?"

using only information that was available at that time.

This is essential for avoiding hindsight contamination.

---

# 33. User-Supplied Research

Users should be able to add:

documents,
URLs,
notes,
hypotheses,
counterarguments,
and manual evidence.

User evidence should remain distinguishable from system-generated evidence.

Suggested labels:

System
User
External Research
Quantitative
Historical
---

# 34. Permissions and Collaboration

For a SaaS aimed at professional users, support:

Personal

Private workspaces and watchlists.

Team

Shared research workspaces.

Organization

Shared Processes, annotations, and internal documents.

Every object should have an ownership/access model independent of the public ontology.

The canonical Process graph can be system-wide while users maintain private annotations and research.

---

# 35. MVP Scope

Do not attempt to build the complete interface initially.

Phase 1
Discover
Process list
Process screener
Process cards
Process
Process overview
State timeline
Evidence timeline
Scorecard
Graph
Process → Bottleneck → Capability → Asset
Asset
Asset page
Asset comparison
Basic quantitative metrics
Research
Evidence inspection
Explain
Natural-language query
Monitoring
Watchlist
Thesis journal
Basic alerts
---

# 36. Phase 2

Add:

historical analogue engine,
historical replay,
advanced Process radar,
Capability confluence search,
sophisticated Asset ranking,
thesis invalidation alerts,
collaborative research,
user workspaces,
richer quantitative visualizations.
---

# 37. Phase 3

Potentially add:

probabilistic outcome distributions,
trade construction,
options analysis,
portfolio optimization,
conditional probability models,
automated position sizing,
and live execution integrations.

Trade Quant should remain outside the initial architecture unless the rest of the research system is sufficiently mature.

---

# 38. Signature User Journey

The complete intended workflow should feel like:

DISCOVER
"What is changing?"

      ↓

PROCESS
"What economic Process explains it?"

      ↓

STATE
"Where are we in its evolution?"

      ↓

BOTTLENECK
"What is preventing the Process from scaling?"

      ↓

CAPABILITY
"What must exist to resolve the Bottleneck?"

      ↓

ASSET DISCOVERY
"Which Assets provide those Capabilities?"

      ↓

ASSET UNDERWRITING
"Which Asset is the best expression?"

      ↓

HISTORICAL ANALOG
"Has this configuration happened before?"

      ↓

TRADE
"How do I express the thesis?"

      ↓

MONITOR
"Is the thesis still developing?"

      ↓

LEARN
"Was the system right?"

This is the central product loop.

---

# 39. Core Design Philosophy

The product should feel less like:

"Ask an AI what stock to buy."

and more like:

"Explore a continuously updated model of the economic world and determine where the model currently offers an attractive investable expression."

The user should always be able to move between:

macro process → specific mechanism → capability → asset → evidence → historical precedent → outcome

without losing provenance.

The UI therefore becomes an interface to the ontology itself.

The deepest product differentiation is not the chatbot, the stock screener, or even the graph individually.

It is the ability to maintain a persistent, temporal, evidence-backed representation of economic Processes and their downstream investment expressions, and to let a human interrogate that representation at whatever level of abstraction is useful.

---

# 40. Recommended North-Star Metric

The primary product metric should not simply be:

daily active users

or:

number of AI queries.

A more meaningful product-level metric is:

How often does the system help a user move from a newly identified Process to a defensible Asset thesis with a complete evidence trail?

This can be decomposed into:

Process discovered
Process investigated
Bottleneck identified
Capability identified
Asset selected
Investment case constructed
Thesis monitored
Outcome recorded

That is the fundamental workflow the entire product is designed to facilitate.
