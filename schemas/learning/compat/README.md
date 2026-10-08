# Learning-contract compatibility fixtures

All records are synthetic; accept files cover every record schema.
Reject records carry `_expect`, stripped before validation, to pin the refusal.
A fixture that stops validating as expected is a breaking contract change:
bump the bundle version and announce it on the learning-plane bus.
Never edit a fixture to make a red test green without that bump and announcement.
