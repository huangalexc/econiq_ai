"""Twenty articles repeating one Reuters report are not twenty sources."""

import pytest
from econiq_agents import (
    SourceDocument,
    assess_independence,
    duplicate_suppression_rate,
    jaccard,
    shingles,
)

WIRE = (
    "The Pentagon acquired a 15 percent stake in MP Materials on Monday, the "
    "companies said in a joint statement, in the largest federal investment in "
    "a rare-earth producer to date."
)
SYNDICATED = (
    "REUTERS - The Pentagon acquired a 15 percent stake in MP Materials on "
    "Monday, the companies said in a joint statement, in the largest federal "
    "investment in a rare-earth producer to date."
)
INDEPENDENT = (
    "Defense officials confirmed a new equity position in the Mountain Pass "
    "operator, describing the arrangement as a strategic reserve measure that "
    "follows two years of quiet negotiation over domestic magnet supply."
)


def _doc(document_id: str, publisher: str | None, text: str) -> SourceDocument:
    return SourceDocument(document_id=document_id, publisher=publisher, text=text)


def test_one_wire_story_across_many_outlets_is_one_source():
    documents = [_doc("d0", "Reuters", WIRE)] + [
        _doc(f"d{i}", f"Outlet {i}", SYNDICATED) for i in range(1, 20)
    ]

    assessment = assess_independence(documents)

    assert assessment.independent_source_count == 1
    assert assessment.suppressed == 19
    assert len(assessment.syndicated_document_ids) == 19
    assert duplicate_suppression_rate(20, 1) == pytest.approx(0.95)


def test_genuinely_independent_reporting_is_counted_separately():
    assessment = assess_independence(
        [_doc("d1", "Reuters", WIRE), _doc("d2", "Bloomberg", INDEPENDENT)]
    )
    assert assessment.independent_source_count == 2
    assert assessment.syndicated_document_ids == ()


def test_several_pieces_from_one_publisher_are_one_source():
    assessment = assess_independence(
        [
            _doc("d1", "Reuters", WIRE),
            _doc("d2", "Reuters", INDEPENDENT),
            _doc("d3", "Bloomberg", INDEPENDENT),
        ]
    )
    assert assessment.independent_source_count == 2
    assert assessment.publishers == ("Bloomberg", "Reuters")


def test_an_unknown_publisher_is_its_own_source():
    """Over-counting one uncertain source beats collapsing real reporting."""
    assessment = assess_independence([_doc("d1", None, WIRE), _doc("d2", None, INDEPENDENT)])
    assert assessment.independent_source_count == 2


def test_no_documents_means_no_sources():
    assert assess_independence([]).independent_source_count == 0


def test_shingles_ignore_case_and_punctuation():
    assert shingles("The Pentagon acquired a stake") == shingles("the pentagon, ACQUIRED a stake!")


def test_jaccard_is_zero_for_disjoint_text():
    assert jaccard(shingles(WIRE), shingles("Unrelated text about lumber prices today")) == 0.0
    assert jaccard(frozenset(), shingles(WIRE)) == 0.0
