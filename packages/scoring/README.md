# packages/scoring

Reusable scoring primitives, kept out of the agents so that score computation is
deterministic and testable in isolation.

Empty until issue #65 (Thesis Scoring agent) — the first thing that needs it.
The ontology contract it will implement already exists in
`econiq_ontology.quality`: `ScoreFamily`, `DimensionScore` and `Scorecard`,
including the rule that Thesis, Asset and Trade quality never mix.
