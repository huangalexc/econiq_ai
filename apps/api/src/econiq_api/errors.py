"""API errors.

Deliberately small. The domain layer raises meaningful exceptions already, and
the API's job is to translate them rather than invent a second vocabulary.
"""

from __future__ import annotations

from fastapi import HTTPException, status


def not_found(what: str, identifier: object) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no {what} {identifier}")


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
