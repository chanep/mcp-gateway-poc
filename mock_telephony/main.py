from fastapi import FastAPI, HTTPException
from typing import Dict, Any

app = FastAPI(
    title="Mock Telephony & UV API",
    description="Microservice simulating Dialpad's internal telephony API with call and customer records containing PII."
)

CALLS_DB: Dict[str, Dict[str, Any]] = {
    "c-901": {
        "call_id": "c-901",
        "direction": "inbound",
        "duration_seconds": 342,
        "status": "FAILED",
        "error_code": "SIP_500_INTERNAL_SERVER_ERROR",
        "phone_number": "+14155552671",
        "customer_id": "cust-501",
        "customer_email": "alice.cooper@enterprise-client.com",
        "customer_name": "Alice Cooper",
        "csat_score": 1,
        "recording_url": "https://storage.internal.dialpad/recordings/c-901.mp3",
        "transcript_snippet": "Customer stated: 'I tried sending the code to my phone +14155552671 and your app crashed with error 500.'"
    },
    "c-902": {
        "call_id": "c-902",
        "direction": "outbound",
        "duration_seconds": 890,
        "status": "COMPLETED",
        "error_code": None,
        "phone_number": "+16505559812",
        "customer_id": "cust-502",
        "customer_email": "bob.smith@techcorp.io",
        "customer_name": "Bob Smith",
        "csat_score": 5,
        "recording_url": "https://storage.internal.dialpad/recordings/c-902.mp3",
        "transcript_snippet": "Sales discovery call completed successfully."
    },
    "c-903": {
        "call_id": "c-903",
        "direction": "inbound",
        "duration_seconds": 120,
        "status": "DEGRADED",
        "error_code": "RTP_PACKET_LOSS_HIGH",
        "phone_number": "+13125557733",
        "customer_id": "cust-503",
        "customer_email": "carol.danvers@avengers.org",
        "customer_name": "Carol Danvers",
        "csat_score": 3,
        "recording_url": "https://storage.internal.dialpad/recordings/c-903.mp3",
        "transcript_snippet": "Audio stuttering on WebRTC client."
    }
}

CUSTOMERS_DB: Dict[str, Dict[str, Any]] = {
    "cust-501": {
        "customer_id": "cust-501",
        "name": "Alice Cooper",
        "company": "Enterprise Client Inc",
        "email": "alice.cooper@enterprise-client.com",
        "phone": "+14155552671",
        "ssn": "987-65-4321",
        "plan": "Enterprise VIP"
    }
}

@app.get("/health")
def health():
    return {"status": "ok", "service": "telephony-mock"}

@app.get("/api/calls/{call_id}")
def get_call(call_id: str):
    call = CALLS_DB.get(call_id)
    if not call:
        raise HTTPException(status_code=404, detail=f"Call with ID '{call_id}' not found.")
    return call

@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: str):
    customer = CUSTOMERS_DB.get(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer with ID '{customer_id}' not found.")
    return customer
