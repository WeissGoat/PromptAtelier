# Duplicate tags.txt Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only tool that recursively groups semantically equivalent `tags.txt` files and emits warnings for duplicate contents.

**Architecture:** Implement the scanner as a standalone module at `tools/check_duplicate_tag_files.py`. It will parse each file into normalized prompt tags and normalized control lines, create a deterministic signature, group files by signature, and expose a small `main(argv)` CLI. Tests will call both the pure scanner functions and CLI entry point without changing the existing migration command.

**Tech Stack:** Python 3.11, `pathlib`, `argparse`, `re`, `pytest`.

## Global Constraints

- The tool is read-only and must not create, modify, move, or delete scanned files.
- Only files named exactly `tags.txt` are scanned recursively.
- Prompt tag order, spaces, and spaces-versus-underscores do not affect equality.
- Bracket and weight syntax remains part of the tag value; weighted and unweighted tags are different.
- `=...`, `type,...`, `extension,...`, and known legacy control lines participate in the signature as normalized control lines.
- Duplicate groups are warnings and return exit code `0`; read errors return `1`; invalid CLI roots return `2`.
- All output paths and groups must be deterministic by relative path ordering.

---

### Task 1: Scanner module

**Files:**
- Create: `tools/check_duplicate_tag_files.py`

**Interfaces:**
- `scan_tag_files(root: Path) -> ScanResult`
- `main(argv: Sequence[str] | None = None) -> int`

**Step 1: Define result types and normalization helpers**

Create dataclasses for one file error and the complete scan result. Use a signature type containing sorted unique normalized tags and sorted unique normalized control lines. Implement:

```python
def _normalize_tag(value: str) -> str:
    value = re.sub(r"\\s+", "_", value.strip().lower())
    return re.sub(r"_+", "_", value)
```

Control-line normalization must lower-case, collapse whitespace, and remove whitespace around commas and the first equals sign without changing payload punctuation.

**Step 2: Implement top-level comma parsing**

Implement a small parser that splits commas only when the bracket stack is empty. It must preserve commas inside `()`, `[]`, and `{}` so weighted prompts remain one tag.

**Step 3: Implement tags/control classification and file signatures**

Read using `utf-8-sig`. Ignore blank lines. Treat a line as control when it starts with `=`, or its first comma-separated key is one of `type`, `extension`, `after_uc`, `origin_uc`, `origin_clear`, `gen_json`, `gen_param`, `uc`, or `negative_prompt`. Parse all other lines with the top-level comma parser and normalize the resulting tags.

Return a signature made from the sorted unique prompt tags and sorted unique control lines.

**Step 4: Implement recursive scanning and grouping**

Resolve and validate the root, discover `root.rglob("tags.txt")`, sort by relative POSIX path, and read each file. Group successful files by signature. Keep only groups with at least two files. Record read failures and continue scanning.

**Step 5: Implement CLI output and exit codes**

Accept one positional directory. Print each duplicate group to `stderr` as:

```text
WARNING duplicate tags content (N files):
  relative/path/tags.txt
```

Print one summary line to `stdout` with `scanned`, `duplicate_groups`, `duplicate_files`, and `errors`. Return `0` for completed scans, `1` when read errors occurred, and `2` for invalid roots or argument errors.

### Task 2: Tests

**Files:**
- Create: `tests/test_check_duplicate_tag_files.py`

**Interfaces:**
- Tests consume `scan_tag_files` and `main` from `tools.check_duplicate_tag_files`.

**Step 1: Add the semantic duplicate case**

Create two files with the same tags in different order and with spaces versus underscores. Assert one duplicate group, two duplicate files, stable relative path order, and no file content changes.

**Step 2: Add non-duplicate weight and control cases**

Assert `{{black_hair}}` differs from `black_hair`, and files with different `type` or `extension` control lines are not grouped.

**Step 3: Add unique and repeated-run cases**

Assert a unique file produces no warnings and that running the scanner twice returns identical result data and output ordering.

**Step 4: Add error and CLI exit-code cases**

Use an invalid UTF-8 file to assert a read error and exit code `1`. Call `main` with a missing/non-directory path and assert exit code `2`. Capture stdout/stderr to verify warning and summary placement.

**Step 5: Run focused verification**

Run:

```powershell
uv run pytest tests/test_check_duplicate_tag_files.py -q
python tools/check_duplicate_tag_files.py <temporary-test-directory>
```

Expected: all tests pass; the CLI prints warnings only for duplicate signature groups and never writes files.

### Task 3: Documentation and final verification

**Files:**
- Modify: `README.md`

**Step 1: Add the command example**

Document the read-only command, warning semantics, normalization behavior, and exit codes in the tools section.

**Step 2: Run full focused tool verification**

Run:

```powershell
uv run pytest tests/test_check_duplicate_tag_files.py tests/test_sync_action_meta.py -q
git diff --check
```

Expected: all tests pass and `git diff --check` has no errors.

**Step 3: Commit only this feature**

```powershell
git add tools/check_duplicate_tag_files.py tests/test_check_duplicate_tag_files.py README.md
git commit -m "feat: add duplicate tags scanner"
```
