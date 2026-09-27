def canonicalize_skill_tree_case(source: Path, target: Path) -> None:
    """Give case-insensitive destination entries the source tree's spelling."""
    try:
        source_children = sorted(source.iterdir(), key=lambda path: path.name)
        target_children = sorted(target.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise HarnessError(
            f"cannot inspect skill tree while aligning case: {source}; {target}: {exc}"
        ) from exc

    # Resolve source spellings through the destination itself. Unicode
    # casefold is not a filesystem lookup rule (for example, NTFS can keep
    # Straße and STRASSE as distinct entries).
    for target_child in target_children:
        if path_is_alias(target_child):
            raise HarnessError(f"unsafe skill tree alias: {target_child}")
    target_by_name = {entry.name: entry for entry in target_children}
    source_by_target: dict[str, Path] = {}
    for source_child in source_children:
        if path_is_alias(source_child):
            raise HarnessError(f"unsafe skill tree alias: {source_child}")
        desired = target / source_child.name
        if path_is_alias(desired):
            raise HarnessError(f"unsafe skill tree alias: {desired}")
        try:
            if not desired.exists():
                continue
            exact = target_by_name.get(source_child.name)
            # Exact directory entries stay distinct even when they are hard links.
            matches = (
                [exact]
                if exact is not None
                else [entry for entry in target_children if desired.samefile(entry)]
            )
        except OSError as exc:
            raise HarnessError(
                f"cannot resolve skill destination spelling: {desired}: {exc}"
            ) from exc
        if len(matches) != 1:
            raise HarnessError(f"ambiguous skill destination spelling: {desired}")
        key = matches[0].name
        previous = source_by_target.get(key)
        if previous is not None and previous.name != source_child.name:
            raise HarnessError(
                f"source skill entries collide on this destination: "
                f"{previous}; {source_child}"
            )
        source_by_target[key] = source_child

    for target_child in target_children:
        if path_is_alias(target_child):
            raise HarnessError(f"unsafe skill tree alias: {target_child}")
        source_child = source_by_target.get(target_child.name)
        if source_child is None:
            continue

        try:
            source_mode = source_child.lstat().st_mode
            target_mode = target_child.lstat().st_mode
        except OSError as exc:
            raise HarnessError(
                f"skill tree changed while aligning case: {source_child}; "
                f"{target_child}: {exc}"
            ) from exc
        source_is_dir = stat.S_ISDIR(source_mode)
        target_is_dir = stat.S_ISDIR(target_mode)
        if source_is_dir != target_is_dir:
            remove_skill_tree_entry(target_child)
            continue
        if not (source_is_dir or stat.S_ISREG(source_mode)) or not (
            target_is_dir or stat.S_ISREG(target_mode)
        ):
            raise HarnessError(
                f"unsupported skill tree entry while aligning case: {target_child}"
            )

        if source_child.name != target_child.name:
            desired = target / source_child.name
            if desired.exists() or path_is_alias(desired):
                try:
                    same_entry = target_child.samefile(desired)
                except OSError as exc:
                    raise HarnessError(
                        f"cannot compare case-renamed skill entry: "
                        f"{target_child}; {desired}: {exc}"
                    ) from exc
                if not same_entry:
                    raise HarnessError(
                        f"ambiguous case-insensitive skill destination: "
                        f"{target_child}; {desired}"
                    )
            rename_skill_tree_entry_to_canonical_name(target_child, desired)
            target_child = desired

        if source_is_dir:
            canonicalize_skill_tree_case(source_child, target_child)


def make_skill_tree_directories_writable(root: Path) -> None:
    """Temporarily make an existing target tree removable on POSIX."""
    if os.name == "nt":
        return

    pending = [root]
    while pending:
        directory = pending.pop()
        if path_is_alias(directory):
            raise HarnessError(f"unsafe skill tree alias: {directory}")
        try:
            mode = directory.lstat().st_mode
            if not stat.S_ISDIR(mode):
                raise HarnessError(f"skill tree changed during pruning: {directory}")
            current_mode = stat.S_IMODE(mode)
            writable_mode = current_mode | 0o700
            if writable_mode != current_mode:
                os.chmod(directory, writable_mode)
            children = list(directory.iterdir())
        except HarnessError:
            raise
        except OSError as exc:
            raise HarnessError(
                f"cannot prepare skill tree for pruning {directory}: {exc}"
            ) from exc

        for child in children:
            if path_is_alias(child):
                raise HarnessError(f"unsafe skill tree alias: {child}")
            try:
                child_mode = child.lstat().st_mode
            except OSError as exc:
                raise HarnessError(
                    f"cannot inspect skill tree entry {child}: {exc}"
                ) from exc
            if stat.S_ISDIR(child_mode):
                pending.append(child)
            elif not stat.S_ISREG(child_mode):
                raise HarnessError(f"unsupported skill tree entry: {child}")


def copy_skill_tree_over(source: Path, target: Path) -> None:
    """Copy a skill over its live root, then prune stale entries in place."""
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        source_digest = tree_digest(source)
        target_digest = tree_digest(target)
        if source_digest is None or target_digest != source_digest:
            raise HarnessError(
                f"copied skill tree does not match source: {source}; {target}"
            )
        return

    source_kinds = skill_tree_entry_kinds(source)
    target_kinds = skill_tree_entry_kinds(target)
    if source_kinds is None or target_kinds is None:
        raise HarnessError(f"skill tree changed during sync: {source}; {target}")

    source_dir_modes: dict[str, int] = {}
    if os.name != "nt":
        try:
            source_dir_modes[""] = stat.S_IMODE(source.lstat().st_mode)
            for relative, kind in source_kinds.items():
                if kind == "directory":
                    path = source / Path(*PurePosixPath(relative).parts)
                    source_dir_modes[relative] = stat.S_IMODE(path.lstat().st_mode)
        except OSError as exc:
            raise HarnessError(f"cannot inspect skill tree {source}: {exc}") from exc

    # The caller has already retained a backup of an existing target. Make it
    # removable before pruning so a previous sync's read-only directory modes
    # cannot prevent this sync from deleting stale entries.
    make_skill_tree_directories_writable(target)

    # copytree(..., dirs_exist_ok=True) cannot replace a file with a directory
    # (or vice versa), so remove conflicting nested entries first. Keep the live
    # skill root in place for Windows readers holding it.
    for relative in sorted(set(source_kinds) & set(target_kinds)):
        if source_kinds[relative] != target_kinds[relative]:
            remove_skill_tree_entry(target / Path(*PurePosixPath(relative).parts))

    if skill_tree_destination_is_case_insensitive(target):
        canonicalize_skill_tree_case(source, target)

    target_kinds = skill_tree_entry_kinds(target)
    if target_kinds is None:
        raise HarnessError(f"skill tree changed during sync: {target}")
    stale = sorted(
        set(target_kinds) - set(source_kinds),
        key=lambda relative: (-len(PurePosixPath(relative).parts), relative),
    )
    for relative in stale:
        path = target / Path(*PurePosixPath(relative).parts)
        if path.exists() or path_is_alias(path):
            remove_skill_tree_entry(path)

    shutil.copytree(source, target, dirs_exist_ok=True)

    current_kinds = skill_tree_entry_kinds(target)
    if current_kinds is None:
        raise HarnessError(f"skill tree changed during sync: {target}")
    stale = sorted(
        set(current_kinds) - set(source_kinds),
        key=lambda relative: (-len(PurePosixPath(relative).parts), relative),
    )
    if stale:
        make_skill_tree_directories_writable(target)
        try:
            for relative in stale:
                path = target / Path(*PurePosixPath(relative).parts)
                if path.exists() or path_is_alias(path):
                    remove_skill_tree_entry(path)
        finally:
            if os.name != "nt":
                for relative, mode in source_dir_modes.items():
                    path = (
                        target
                        if not relative
                        else target / Path(*PurePosixPath(relative).parts)
                    )
                    try:
                        if stat.S_ISDIR(path.lstat().st_mode):
                            os.chmod(path, mode)
                    except FileNotFoundError:
                        continue
                    except OSError as exc:
                        raise HarnessError(
                            f"cannot restore skill tree mode {path}: {exc}"
                        ) from exc

    source_digest = tree_digest(source)
    target_digest = tree_digest(target)
    if source_digest is None or target_digest != source_digest:
        raise HarnessError(
            f"copied skill tree does not match source: {source}; {target}"
        )


