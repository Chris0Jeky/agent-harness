# Replay input decoding failures

Follow-up to #145. Source-output failures remain distinct from invalid inputs:
#334 preserves reports when a running policy emits invalid decision JSON; this
change rejects invalid corpus or recorded-sidecar JSON before policy execution.

## Boundary

Translate JSON decoder `ValueError` at the existing corpus-manifest, corpus-JSONL
and recorded-sidecar boundaries. Python integer-conversion limits are not raised
or disabled. Existing duplicate-key and schema errors keep their more specific
diagnostics instead of being replaced by a generic decoding message.

The CLI returns input-invalid exit 2, writes a bounded diagnostic, and neither
launches a policy nor creates a report directory for these input failures. Both
`replay` and `validate` use the corpus boundary. Direct `RecordedDecisionSource`
use returns `recording-manifest-invalid` with all decisions indeterminate when
its sidecar cannot be decoded. The direct source API has no CLI exit status.

## Controls

`python -m unittest tests.test_replay_input_decoding -v` exercises actual CLI
subprocesses for an oversized integer in the corpus manifest, recorded sidecar,
events and cases. JSONL digests are refreshed so tests reach decoding rather
than fail for unrelated stale bytes. A valid fixture proves that the candidate
can launch and publish all three reports. Additional controls preserve JSON
syntax, UTF-8, duplicate-key and recorded-schema diagnostics, and exercise the
direct recorded-source API. Only test-child integer limits are tightened.

No schema, production interpreter limit, process-launch protocol, timeout,
policy effect, floor, permission or merge gate changes. This is not a universal
exception handler or a memory/resource sandbox. Other #145 cases retain their
own acceptance evidence; this document does not close them by implication.
