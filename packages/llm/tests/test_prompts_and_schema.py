"""Prompt versioning and schema sanitisation."""

import pytest
from econiq_llm import (
    PromptNotFoundError,
    PromptRegistry,
    PromptTemplate,
    sanitize_json_schema,
    schema_is_recursive,
)


def _prompt(version="1.0.0", body="Classify this document."):
    return PromptTemplate(name="document_classifier", version=version, template=body)


def test_version_and_hash_both_travel_with_the_prompt():
    prompt = _prompt()
    assert prompt.qualified_version.startswith("document_classifier@1.0.0+")
    assert prompt.content_hash == _prompt().content_hash


def test_editing_a_prompt_changes_its_hash():
    """The failure versioning alone misses: an edit with no version bump."""
    assert _prompt().content_hash != _prompt(body="Classify this doc.").content_hash


def test_registry_refuses_a_silent_edit_of_a_registered_version():
    registry = PromptRegistry()
    registry.register(_prompt())
    registry.register(_prompt())  # identical content is fine
    with pytest.raises(ValueError, match="bump the version"):
        registry.register(_prompt(body="Classify this doc."))


def test_old_versions_stay_retrievable():
    registry = PromptRegistry()
    registry.register(_prompt("1.0.0"))
    registry.register(_prompt("1.1.0", body="Classify this document carefully."))
    assert registry.get("document_classifier").version == "1.1.0"
    assert registry.get("document_classifier", "1.0.0").version == "1.0.0"
    assert registry.versions("document_classifier") == ("1.0.0", "1.1.0")


def test_unknown_prompts_and_versions_fail_loudly():
    registry = PromptRegistry()
    with pytest.raises(PromptNotFoundError):
        registry.get("nope")
    registry.register(_prompt())
    with pytest.raises(PromptNotFoundError, match="no version"):
        registry.get("document_classifier", "9.9.9")


def test_versions_must_be_semver_like():
    with pytest.raises(ValueError, match="semver"):
        PromptTemplate(name="x", version="v2", template="…")


def test_template_variables_are_required():
    prompt = PromptTemplate(
        name="x", version="1.0.0", template="State: $state", required_variables=frozenset({"state"})
    )
    assert prompt.render({"state": "acceleration"}) == "State: acceleration"
    with pytest.raises(ValueError, match="missing variables"):
        prompt.render({})


def test_unsupported_constraints_are_stripped_but_objects_are_closed():
    from econiq_schemas import ProcessStateOutput

    sanitized = sanitize_json_schema(ProcessStateOutput.model_json_schema())
    flat = repr(sanitized)
    for keyword in ("minimum", "maxLength", "pattern", "minItems"):
        assert f"'{keyword}'" not in flat
    assert sanitized["additionalProperties"] is False


def test_recursive_schemas_are_detected():
    """The Capability requirement tree cannot use provider-side enforcement."""
    from econiq_schemas import CapabilityMappingOutput, ProcessStateOutput

    assert schema_is_recursive(CapabilityMappingOutput.model_json_schema())
    assert not schema_is_recursive(ProcessStateOutput.model_json_schema())
