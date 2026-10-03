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
cannot absorb the source file. Agent modes are retained from the planned source and are
applied to the staging file before its fsync. Overwritten agent/state bytes retain the
existing backup layout. Failed staging or replacement does not publish a partial file;
its temporary sibling is removed where the filesystem permits.

Permissions differ by platform, because a renamed file keeps its own access control:

- **POSIX:** agents take the source mode through the open descriptor; the ownership record
  keeps `mkstemp`'s owner-only `0600`.
- **Windows (NTFS):** a mode contributes only the read-only attribute, so access comes from
  the DACL. The staging file is created with the existing destination's DACL, including
  its inheritance protection and explicit deny entries, or with a protected owner-only
  DACL (and the token user as owner) when the destination is new. Before any byte is
  written, the created DACL is read back and compared with the requested one; a host that
  merged parent entries or dropped protection is refused, not published. The file is
  opened without sharing until replacement, so no reader can be admitted under broader
  access. The read-only attribute is set at creation. Only the DACL is carried over: the
  replacement is owned by the writing token's default owner (an elevated token may make
  that the Administrators group), and mandatory integrity labels and other SACL entries
  of the old file are not copied. Measured on NTFS: a
  destination that another process holds open without delete sharing, or that is
  read-only, refuses replacement; the live bytes, attribute and DACL stay unchanged and
  the staging sibling is removed. A read-only source mode therefore publishes a read-only
  destination that later runs refuse to replace until the attribute is cleared.

This is **single-file publication**, not a multi-file transaction or a concurrent-writer
lock. Earlier files in a failed run may already have changed. Backups remain the recovery
record; do not blindly overwrite newer live edits with them. Checks bound observed
changes but cannot exclude another writer between a check and a filesystem operation.
File fsync is not a guarantee of directory-entry durability across every crash/filesystem.
Unknown files, runtime trust and installed-global activation remain outside this lane.
