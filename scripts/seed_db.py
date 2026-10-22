import sqlite3
from pathlib import Path

def init_db():
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "tickets.db"

    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE tickets (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL,
        priority TEXT NOT NULL,
        assigned_to TEXT NOT NULL,
        call_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    sample_tickets = [
        (
            "TICKET-101",
            "500 Internal Error during SMS delivery and abrupt call drop",
            "Customer reported that during call c-901 there was an unexpected termination and the app threw a 500 error when sending a verification SMS.",
            "OPEN",
            "CRITICAL",
            "john@dialpad.com",
            "c-901"
        ),
        (
            "TICKET-102",
            "Delay in UV call transcription processing",
            "Transcriptions for calls exceeding 10 minutes take more than 20 minutes to process.",
            "IN_PROGRESS",
            "HIGH",
            "mary@dialpad.com",
            "c-902"
        ),
        (
            "TICKET-103",
            "Degraded audio quality over WebRTC",
            "Observed packet loss for clients on unstable UDP connections during call c-903.",
            "RESOLVED",
            "MEDIUM",
            "peter@dialpad.com",
            "c-903"
        ),
        (
            "TICKET-104",
            "Renew sandbox SSL certificate",
            "Certificate expires in 5 days. Must renew before Friday deployment.",
            "OPEN",
            "LOW",
            "devops@dialpad.com",
            None
        )
    ]

    cursor.executemany("""
    INSERT INTO tickets (id, title, description, status, priority, assigned_to, call_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, sample_tickets)

    conn.commit()
    conn.close()
    print(f"Database successfully created at: {db_path.resolve()} with {len(sample_tickets)} sample tickets.")

if __name__ == "__main__":
    init_db()
