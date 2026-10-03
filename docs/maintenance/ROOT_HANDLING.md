# Sync input and Doctor session roots

Source behavior for issues #273, #258 and the unavailable-root portion of #375.
This is not an installed-runtime or native trust receipt.

## Raw sync inputs

`sync-global` refuses parent components (`..`) in selected input roots before
absolute-path normalization or alias inspection. This prevents an input such as
`alias/../target` from hiding an alias or selecting a different physical target.
The same rule applies to bundle roots and a supplied rollback-receipt path.
Use the intended concrete path without parent components. Ordinary relative paths
and `./` remain usable. Unselected Codex and skill roots do not affect a
Claude-skill-only sync.

Refusal occurs before live copies, backup allocation or target creation. Existing
alias, overlap, source-drift and recovery checks still apply. This is not a
concurrent-writer exclusion mechanism.

## Unavailable destinations

Both source-name preflight ancestor walks stop with a named error when they reach
an unavailable root. A destination becoming unavailable after the disposable probe
was created is a separate control; the probe cleanup still runs. An ordinary
missing parent with an available ancestor remains supported.

The regression fixtures use disposable directories and bounded fault injection.
They do not certify every unavailable drive, mount or filesystem lookup mode.
Selected-root name collisions and the remaining filesystem qualification in #375
are separate work.

## Doctor's modeled session cwd

When root-selection rule 2 finds the unique declared product below `--repo`,
Doctor models a session started in that product. It now names this cwd and uses it
consistently for both configuration-layer inspection and relative-wrapper checks.
Direct product inspection and downward product selection therefore agree.

This does not certify starting a real session in the undeclared parent directory.
A checkout-relative wrapper inherited by the product, or a relative wrapper sourced
from a primary checkout while inspecting a linked worktree, is still rejected when
its source root differs from the modeled session cwd. Runtime trust, enabled state
and live canaries remain separate operator evidence.
