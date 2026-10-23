# Serialization digest

The new scheme is sha256-lf-v1: replace CRLF byte pairs with LF, then compute uppercase SHA-256. JSON spacing, key ordering, BOMs, lone carriage returns, and every other byte still matter. This is line-ending normalization, not JSON canonicalization.

Project metadata declares roomcontract_digest_scheme; the V2 trace declares digest_scheme. They must agree. A missing declaration retains sha256-raw-v1 for old projects. Unknown schemes fail closed. The materializer emits the new scheme; the example is repinned without changing its model bytes.

Regression evidence: results/raw/packet_regression.json records the original LF setup refusal. tests/test_digest.py checks portability, altered content/spacing, legacy compatibility, and unknown schemes.
