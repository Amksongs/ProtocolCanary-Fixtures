# Live RPC response vectors

These five JSON files are read-only JSON-RPC captures from the public Stellar
Testnet endpoint `https://soroban-testnet.stellar.org`; each envelope records
its own capture instant (`getNetwork`, `getLatestLedger` and `getVersionInfo`
were captured on 2026-10-18 UTC, and the two remaining methods on 2026-10-30
UTC).
The request and response bodies are preserved exactly as returned; no values
were invented or redacted. The paired `getNetwork` capture records the
Testnet passphrase and protocol version 29 at the capture time.

The endpoint is the official Testnet Soroban RPC service documented by
[Stellar RPC](https://developers.stellar.org/docs/data/apis/rpc/api-reference).
The method-specific fields are checked by
[`tests/test_rpc_response_vectors.py`](../../test_rpc_response_vectors.py),
which also mutates valid responses to prove that missing fields, wrong types,
method mismatches, and malformed JSON-RPC envelopes fail validation.

`getLatestLedger` is intentionally large because its `headerXdr` and
`metadataXdr` fields are the complete public response payload, not a sample or
placeholder. The vectors are offline test inputs after capture; the test suite
does not contact the endpoint.
