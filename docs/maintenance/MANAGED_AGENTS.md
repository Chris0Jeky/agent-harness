# Managed Codex agent publication

The `sync-global --only codex-agents` lane reconciles ordinary `.toml` definitions
and its explicit ownership record. It does not install models or activate a deny floor.

Before any write, ownership JSON must have unique keys at every object level and
unique case-folded agent names. Only entries matching a selected agent's managed
identity take part in destination lookup. Notes, hidden files and unrelated directories
are left alone; ambiguous case-equivalent agent definitions are still refused.

Planning captures each source file's exact bytes and mode. Apply publishes those bytes,
not a later version reread from the source pathname. A source edited after planning is
picked up by the next sync. The recorded digest is computed from the captured bytes,
and every active destination is checked again before ownership publication, including
planned no-ops. A detected late edit is refused, not certified by a stale digest.

Each changed agent and nonempty ownership record is written to an exclusively created
temporary sibling, flushed and fsynced, then atomically replaced. This breaks destination
hardlinks instead of mutating their other names, and a directory at the final pathname
cannot absorb the source file. Agent modes are retained from the planned source. The
ownership record uses the temporary file's private default permissions. Overwritten
agent/state bytes retain the existing backup layout. Failed staging or replacement does
not publish a partial file; its temporary sibling is removed where the filesystem permits.

This is **single-file publication**, not a multi-file transaction or a concurrent-writer
lock. Earlier files in a failed run may already have changed. Backups remain the recovery
record; do not blindly overwrite newer live edits with them. Checks bound observed
changes but cannot exclude another writer between a check and a filesystem operation.
File fsync is not a guarantee of directory-entry durability across every crash/filesystem.
Unknown files, runtime trust and installed-global activation remain outside this lane.
