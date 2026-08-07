"""Claim extraction preserves epistemic distinctions."""

from econiq_ontology import ClaimType
from econiq_schemas import ASSERTION_TO_CLAIM_TYPE, AssertionSource, ProposedClaim


def test_every_assertion_source_maps_to_a_claim_type():
    assert set(ASSERTION_TO_CLAIM_TYPE) == set(AssertionSource)


def test_forecasts_are_hypotheses_not_facts():
    """A company's capex forecast must not accumulate as a reported fact."""
    claim = ProposedClaim(
        text="Microsoft expects capital expenditure to increase.",
        assertion_source=AssertionSource.COMPANY_FORECAST,
        source_location={"paragraph": 4, "quote": "expects capital expenditure to increase"},
        extraction_confidence=0.9,
    )
    assert claim.claim_type is ClaimType.HYPOTHESIS


def test_observed_facts_are_derived_facts():
    claim = ProposedClaim(
        text="Revenue was $65.6bn.",
        assertion_source=AssertionSource.OBSERVED_FACT,
        source_location={"page": 3},
        extraction_confidence=0.99,
    )
    assert claim.claim_type is ClaimType.DERIVED_FACT
