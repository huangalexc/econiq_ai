"""Ingestion failures, typed so the pipeline can react rather than just log."""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for ingestion failures."""


class UnsupportedContentTypeError(IngestionError):
    """No parser is registered for the document's content type."""


class ParserNotAvailableError(IngestionError):
    """The parser exists but its optional dependency is not installed."""


class StorageError(IngestionError):
    """The object store rejected a read or write."""
