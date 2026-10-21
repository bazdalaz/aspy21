"""Exceptions and error detection for Aspen REST API responses."""

from __future__ import annotations


class AspenSqlError(ValueError):
    """Raised when the IP.21 SQL endpoint reports an error.

    IP.21 returns SQL errors with HTTP 200, so they are detected from the response body.
    """


def raise_for_sql_error(payload: object) -> None:
    """Raise AspenSqlError if a SQL endpoint response contains an error.

    Recognized formats:
        - [{"AtPD_ErrorCode": ..., "AtPD_ErrorString": "..."}]  (response="Record")
        - {"data": [{"r": "E", "ec": <code>, "es": "..."}]}  (response="Original")
        - {"data": [{"result": {"er": <non-zero>, "es": "..."}}]}
        - Either error object at the top level or inside the "data" array

    Args:
        payload: Parsed JSON response

    Raises:
        AspenSqlError: If the response contains an error
    """
    candidates: list[object] = []
    if isinstance(payload, list):
        # Errors come back as a single record; avoid scanning large result sets
        candidates = payload[:1]
    elif isinstance(payload, dict):
        candidates = [payload]
        data = payload.get("data")
        if isinstance(data, list):
            candidates.extend(data)

    for item in candidates:
        if not isinstance(item, dict):
            continue
        if "AtPD_ErrorCode" in item:
            message = item.get("AtPD_ErrorString") or f"error code {item['AtPD_ErrorCode']}"
            raise AspenSqlError(f"SQL API error: {message}")
        if item.get("r") == "E" or item.get("ec", 0) != 0:
            message = item.get("es") or item.get("aes") or f"error code {item.get('ec')}"
            raise AspenSqlError(f"SQL API error: {message}")
        result = item.get("result")
        if isinstance(result, dict) and result.get("er", 0) != 0:
            raise AspenSqlError(f"SQL API error: {result.get('es') or 'Unknown error'}")
