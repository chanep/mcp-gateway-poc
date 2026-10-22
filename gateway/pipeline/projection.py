from typing import Any, List, Optional

def apply_response_projection(data: Any, fields: Optional[List[str]]) -> Any:
    """
    Filters response payload to only return fields requested by the agent (P7 - Response Projection).
    Returns complete data if fields is None or empty.
    """
    if not fields or data is None:
        return data

    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in fields}

    if isinstance(data, list):
        return [
            apply_response_projection(item, fields)
            for item in data
        ]

    return data
