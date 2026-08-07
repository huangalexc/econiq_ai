"""Prompts are code (agent doc §21).

A prompt change can flip a Process classification, move a State estimate or
reorder an Asset ranking. So prompts are versioned artefacts with content
hashes, registered explicitly, and the version that produced an output is
recorded against that output — never looked up later from whatever happens to
be current.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from string import Template

from econiq_llm.errors import PromptNotFoundError

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """A versioned system prompt.

    ``$``-substitution rather than f-strings or ``str.format``: prompts contain
    JSON braces, and a template language that ignores them removes a whole class
    of escaping bugs.
    """

    name: str
    version: str
    template: str
    description: str = ""
    required_variables: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not _VERSION_RE.match(self.version):
            raise ValueError(f"prompt version must be semver-like, got {self.version!r}")

    @property
    def content_hash(self) -> str:
        """SHA-256 of the template body, truncated.

        Guards against the failure mode versioning alone cannot catch: an edited
        prompt whose version number was not bumped. The evaluation harness
        (issue #16) compares this against the hash recorded on past runs.
        """
        return hashlib.sha256(self.template.encode()).hexdigest()[:16]

    @property
    def qualified_version(self) -> str:
        """What gets recorded on every output: ``name@version+hash``."""
        return f"{self.name}@{self.version}+{self.content_hash}"

    def render(self, variables: Mapping[str, str] | None = None) -> str:
        values = dict(variables or {})
        missing = self.required_variables - values.keys()
        if missing:
            raise ValueError(f"prompt {self.name!r} missing variables: {sorted(missing)}")
        return Template(self.template).substitute(values) if values else self.template


class PromptRegistry:
    """All known prompt versions, keyed by name.

    Old versions are kept, not replaced: reconstructing why the system believed
    something on a past date requires the prompt it believed it with
    (ui_concept §32).
    """

    def __init__(self) -> None:
        self._by_name: dict[str, dict[str, PromptTemplate]] = {}
        self._current: dict[str, str] = {}

    def register(self, prompt: PromptTemplate, *, current: bool = True) -> PromptTemplate:
        versions = self._by_name.setdefault(prompt.name, {})
        existing = versions.get(prompt.version)
        if existing is not None and existing.content_hash != prompt.content_hash:
            raise ValueError(
                f"prompt {prompt.name!r} version {prompt.version} already registered with "
                f"different content — bump the version rather than editing in place"
            )
        versions[prompt.version] = prompt
        if current or prompt.name not in self._current:
            self._current[prompt.name] = prompt.version
        return prompt

    def get(self, name: str, version: str | None = None) -> PromptTemplate:
        versions = self._by_name.get(name)
        if not versions:
            raise PromptNotFoundError(f"no prompt registered under {name!r}")
        resolved = version or self._current[name]
        try:
            return versions[resolved]
        except KeyError:
            raise PromptNotFoundError(
                f"prompt {name!r} has no version {resolved!r}; known: {sorted(versions)}"
            ) from None

    def versions(self, name: str) -> tuple[str, ...]:
        return tuple(sorted(self._by_name.get(name, {})))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_name))


#: Process-wide registry. Agent modules register their prompts at import time.
PROMPTS = PromptRegistry()


#: Appended to every agent system prompt. These constraints are not per-agent
#: preferences — they are the epistemic rules of the whole system (agent doc
#: §2.3–§2.5), so they live in one place and cannot be forgotten.
SHARED_AGENT_PREAMBLE = """\
You are one narrow component of an evidence-based investment research system.

Rules that apply to every response you produce:
- Answer only the question posed at your layer of the ontology. Do not reason \
about layers below you, and never name an investable security unless your task \
explicitly asks for one.
- Every material statement must cite the supplied Claim ids that support it. If \
no supplied evidence supports a statement, do not make it.
- Distinguish what is observed, inferred, hypothesized, contradicted and \
unknown. Do not present an inference as an observation.
- Confidence values are your belief, not calibrated probabilities. Do not \
describe them as probabilities or likelihoods.
- Do not compute figures. Interpret the numbers you are given; deterministic \
code does the arithmetic.
- If the evidence does not support an answer, abstain and say why. An honest \
abstention is a correct result.\
"""
