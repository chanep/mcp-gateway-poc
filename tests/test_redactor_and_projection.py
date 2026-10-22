import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gateway.pipeline.redactor import redact_sensitive_data
from gateway.pipeline.projection import apply_response_projection

def test_redaction():
    sample_data = {
        "call_id": "c-901",
        "duration": 300,
        "phone_number": "+14155552671",
        "customer": {
            "email": "alice.cooper@enterprise-client.com",
            "name": "Alice"
        }
    }

    redacted = redact_sensitive_data(sample_data, ["phone_number", "email"])

    assert redacted["call_id"] == "c-901"
    assert redacted["duration"] == 300
    assert redacted["phone_number"] == "+1415****671"
    assert redacted["customer"]["email"] == "a****r@enterprise-client.com"
    print("[OK] Redaction test passed: PII masked successfully.")

def test_projection():
    sample_data = {
        "call_id": "c-901",
        "status": "FAILED",
        "error_code": "SIP_500",
        "transcript_large": "Very long transcript..." * 100,
        "debug_trace": "Huge trace..." * 50
    }

    # Project only 2 fields
    projected = apply_response_projection(sample_data, ["call_id", "status"])
    assert list(projected.keys()) == ["call_id", "status"]
    assert projected["call_id"] == "c-901"
    assert "transcript_large" not in projected
    print("[OK] Response Projection test passed: Unrequested fields pruned.")

if __name__ == "__main__":
    test_redaction()
    test_projection()
