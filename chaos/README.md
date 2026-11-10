# Fault Injection Chaos Harness (`chaos/`)

The chaos harness injects synthetic faults into the ingestion and storage pipeline mid-stream:
- Randomly disconnects the WebSocket.
- Drops $N\%$ of messages.
- Injects duplicate messages.
- Reorders messages within a sliding window.
- Kills writer process.

Then it performs an automated reconciliation against ground-truth data:
**No gaps and no double counts.**

## Running:
```bash
python run.py chaos
```

