# Non-executing source-composition fixture

Temporary transport fixture for agent-harness PR #351. Never merge this fixture PR into main or a product branch. The only purpose is to materialize a whole-file Git blob from an existing full source blob and a small contextual edit, using Git's ordinary three-way merge.

The generated blob is usable only if it exactly equals locally verified 0e9a0f33d1665ea7b5e14f369257df09bec0ae46. It must then be placed in a normal commit on PR #351, which keeps all existing CI jobs and review requirements. No history or file from these scratch branches is part of the final PR. compose.py may be a non-executable source fragment. This fixture provides no test, review or merge eligibility evidence.
