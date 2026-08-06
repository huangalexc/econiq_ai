"""Bottleneck and Capability agent guardrails."""

from datetime import UTC, datetime

from econiq_agents import (
    BindingClarityEvaluator,
    ConfluenceScopeEvaluator,
    RequirementStructureEvaluator,
    independent_support,
    slugify,
)
from econiq_ontology import BottleneckKind, ProcessArchetype
from econiq_schemas import (
    BottleneckIdentificationInput,
    BottleneckIdentificationOutput,
    CapabilityConfluenceInput,
    CapabilityConfluenceOutput,
    CapabilityMappingOutput,
    ProcessContext,
)

NOW = datetime(2026, 7, 14, tzinfo=UTC)


def _process(process_id: str = "p1") -> ProcessContext:
    return ProcessContext(
        process_id=process_id,
        name="AI infrastructure expansion",
        description="…",
        archetype=ProcessArchetype.INFRASTRUCTURE_S_CURVE,
    )


def _bottleneck_input() -> BottleneckIdentificationInput:
    return BottleneckIdentificationInput(as_of=NOW, process=_process())


def _candidate(*, binding: bool = True, relief=("Interconnection queue times fall",)) -> dict:
    return {
        "name": "Grid interconnection capacity",
        "description": "New load cannot connect faster than queues clear.",
        "kind": BottleneckKind.INFRASTRUCTURE.value,
        "why_limiting": "Datacentres cannot energise without an interconnection slot.",
        "currently_binding": binding,
        "relief_indicators": list(relief),
        "confidence": 0.8,
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _bottleneck_output(*candidates: dict, index: int | None = 0) -> BottleneckIdentificationOutput:
    return BottleneckIdentificationOutput.model_validate(
        {
            "candidates": list(candidates),
            "binding_candidate_index": index,
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def test_a_binding_constraint_needs_something_to_watch():
    checks = BindingClarityEvaluator().evaluate(
        _bottleneck_input(), _bottleneck_output(_candidate(relief=()))
    )
    assert checks[0].passed is False
    assert "nothing to watch" in (checks[0].detail or "")


def test_a_future_constraint_need_not_name_relief_indicators():
    checks = BindingClarityEvaluator().evaluate(
        _bottleneck_input(),
        _bottleneck_output(_candidate(binding=False, relief=()), index=None),
    )
    assert checks[0].passed


def _capability(ref: str) -> dict:
    return {
        "ref": ref,
        "name": ref.replace("-", " "),
        "description": "…",
        "role": "necessary",
        "confidence": 0.8,
        "supporting_claim_ids": [],
        "contradicting_claim_ids": [],
        "evidence": [],
        "schema_version": "1.0.0",
    }


def _leaf(ref: str, necessity: str = "required") -> dict:
    return {
        "node": "capability",
        "ref": ref,
        "necessity": necessity,
        "weight": 1.0,
        "schema_version": "1.0.0",
    }


def _group(operator: str, *children: dict) -> dict:
    return {
        "node": "group",
        "operator": operator,
        "children": list(children),
        "necessity": "required",
        "weight": 1.0,
        "label": None,
        "schema_version": "1.0.0",
    }


def _mapping(capabilities: list[dict], tree: dict) -> CapabilityMappingOutput:
    return CapabilityMappingOutput.model_validate(
        {
            "capabilities": capabilities,
            "requirement_tree": tree,
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def _structure_checks(output) -> dict[str, bool]:
    checks = RequirementStructureEvaluator().evaluate(_bottleneck_input(), output)
    return {check.name: check.passed for check in checks}


def test_a_structured_and_tree_passes():
    output = _mapping(
        [_capability("transmission"), _capability("transformers")],
        _group("and", _leaf("transmission"), _leaf("transformers")),
    )
    assert all(_structure_checks(output).values())


def test_a_flat_or_over_everything_is_flagged():
    """'Any of these will do' is almost never true of a real Bottleneck."""
    output = _mapping(
        [_capability("transmission"), _capability("transformers")],
        _group("or", _leaf("transmission"), _leaf("transformers")),
    )
    assert _structure_checks(output)["requirement_tree_is_not_a_flat_or"] is False


def test_an_or_inside_a_larger_structure_is_fine():
    output = _mapping(
        [_capability("transmission"), _capability("transformers"), _capability("generation")],
        _group(
            "and",
            _leaf("transmission"),
            _group("or", _leaf("transformers"), _leaf("generation")),
        ),
    )
    assert all(_structure_checks(output).values())


def test_a_necessary_capability_cannot_be_optional_in_the_tree():
    output = _mapping(
        [_capability("transmission"), _capability("transformers")],
        _group("and", _leaf("transmission"), _leaf("transformers", necessity="optional")),
    )
    checks = _structure_checks(output)
    assert checks["necessary_capabilities_are_not_optional"] is False


def _confluence_input(*process_ids: str) -> CapabilityConfluenceInput:
    return CapabilityConfluenceInput(
        as_of=NOW,
        capability_id="c1",
        capability_name="Heavy rare-earth separation",
        capability_description="…",
        candidate_processes=[_process(pid) for pid in process_ids],
    )


def _confluence_output(*support: tuple[str, str]) -> CapabilityConfluenceOutput:
    return CapabilityConfluenceOutput.model_validate(
        {
            "upstream": [
                {
                    "process_id": pid,
                    "independence": independence,
                    "support_strength": 7.0,
                    "rationale": "…",
                    "supporting_claim_ids": [],
                    "contradicting_claim_ids": [],
                    "evidence": [],
                    "schema_version": "1.0.0",
                }
                for pid, independence in support
            ],
            "interactions": [],
            "abstained": False,
            "abstention_reason": None,
            "uncertainty_notes": [],
            "schema_version": "1.0.0",
        }
    )


def test_only_independent_support_is_counted():
    """The same rule the Event layer applies to syndicated reporting."""
    output = _confluence_output(
        ("p1", "independent"), ("p2", "independent"), ("p3", "redundant"), ("p4", "correlated")
    )
    count, ids = independent_support(output)
    assert count == 2
    assert ids == ("p1", "p2")


def test_the_agent_may_only_classify_processes_it_was_shown():
    checks = {
        check.name: check.passed
        for check in ConfluenceScopeEvaluator().evaluate(
            _confluence_input("p1"),
            _confluence_output(("p1", "independent"), ("p9", "independent")),
        )
    }
    assert checks["upstream_processes_were_offered"] is False


def test_slugify_produces_valid_ontology_slugs():
    import re

    pattern = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    for name in ("Heavy Rare-Earth Separation", "  Grid interconnection  ", "HBM (packaging)"):
        assert pattern.match(slugify(name)), name
