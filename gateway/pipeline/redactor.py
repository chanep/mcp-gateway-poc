from typing import Any, List
import re

def _mask_value(value: Any) -> Any:
    if not isinstance(value, str):
        return "***REDACTED***"

    # Mask email: alice@corp.com -> a***e@corp.com
    if "@" in value:
        parts = value.split("@", 1)
        user, domain = parts[0], parts[1]
        if len(user) <= 2:
            masked_user = user[0] + "*"
        else:
            masked_user = user[0] + "****" + user[-1]
        return f"{masked_user}@{domain}"

    # Mask phone: +14155552671 -> +1415****671
    digits = re.sub(r"[^\d]", "", value)
    if len(digits) >= 7:
        prefix = value[:5]
        suffix = value[-3:]
        return f"{prefix}****{suffix}"

    # General text fallback
    if len(value) > 6:
        return value[:2] + "****" + value[-2:]
    return "***REDACTED***"

def redact_sensitive_data(data: Any, redact_keys: List[str]) -> Any:
    """
    Recursively inspects dicts and lists, masking any key
    matching declared entries in `redact_keys` (P4 - PII Redaction).
    """
    if not redact_keys or data is None:
        return data

    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            if k in redact_keys:
                new_dict[k] = _mask_value(v)
            else:
                new_dict[k] = redact_sensitive_data(v, redact_keys)
        return new_dict

    if isinstance(data, list):
        return [redact_sensitive_data(item, redact_keys) for item in data]

    return data
