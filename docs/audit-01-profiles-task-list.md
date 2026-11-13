# STELLA Audit #1 — Profiles: Task List

**Source:** [audit-01-profiles-2026-11-12.md](audit-01-profiles-2026-11-12.md)
(Profiles audit, 2026-11-12, against v0.1 / commit e28db915).

**This file is a list only.** Nothing here has been fixed or built.
Each task turns one or more audit findings into work with a verifiable
"done". Priorities follow the audit's section 7; within a priority,
a fix comes before the polish that depends on it.

**Priority key:** P0 = data loss / silent failure, fix first.
P1 = real functional defect or daily friction. P2 = missing capability
or inconsistency. P3 = polish, display, and scale.

**Effort key:** S = a focused change in one or two files, a day or
less. M = a change across model + GUI + tests, or a small design
decision plus implementation. L = a multi-part build or a design that
needs Joshua's direction on scope first.

**Counts:** 18 tasks — 2 P0, 3 P1, 7 P2, 6 P3.

---

## P0 — fix first

### T1 — Show corrupt manifests as damaged rows, never silently vanish

- **Covers:** W1, D4
- **Effort:** M
- **Problem:** `list_profiles` catches a parse error and `continue`s
  with no warning, no row, no log. Probed: corrupting
  `bogus/profile.json` to `{invalid json` removed the profile (and
  all its projects) from the GUI and CLI entirely, while a direct
  `get_profile("bogus")` still raises a clear "not valid JSON" error.
  The home is meant to be hand-editable, so a hand-edit typo is the
  most likely cause — the user doing exactly what the docs invite is
  the user most likely to hit this. No test covers it.
- **Fix:** `list_profiles` (and the GUI list build) must surface a
  broken manifest instead of skipping it: a greyed "damaged" row
  showing the profile slug and the parse error, plus a Repair action
  that opens the JSON in the text editor. Keep the profile's folder
  untouched; the data is still on disk and the UI must say so.
- **Done:** Corrupt a `profile.json` by hand, open Stella: the
  profile appears as a greyed row with the error text; Repair opens
  the file; fixing the JSON by hand and refreshing restores the
  normal row. New tests: a corrupt manifest is reported (not
  skipped) by the list path, and the GUI shows the damaged row.

### T2 — Soft tag validation at create and save (warn, don't block)

- **Covers:** W2, D2; W12 (duplicate-tag note)
- **Effort:** S
- **Problem:** Any string is accepted as an Ollama tag. Probed:
  `create_profile("bogus", ollama_tag="not-a-real-model:99")`
  succeeds and stores the tag. The GUI picker offers real tags, but
  the combo is editable and nothing checks the typed value — not at
  create, not at save. A typo (`lfm3:1.7bb`, `qwen3-v1` for
  `qwen3-vl`) only fails later, at train or export time, with an
  error that will not point back at the profile. Separately, nothing
  notes when two profiles point at the same tag (W12).
- **Fix:** At create and at save, check the tag against the installed
  model list (a direct `list_models()` call is fine here — it is a
  user-initiated action, not a click; T3's cache replaces it later).
  If the tag is not installed, warn ("not installed locally — is
  this right?") and let him proceed — a deliberate entry (a tag he
  is about to pull) must never be blocked. Also warn when another
  profile already uses the same tag ("profile X already uses this
  tag"), without blocking.
- **Done:** Create a profile with `not-a-real-model:99`: a warning
  appears and the user can still proceed. Create with a typo'd tag
  while the correct tag is installed: warning appears. Create a
  second profile with an already-used tag: the duplicate note
  appears. Tests cover: warning on uninstalled tag, no warning on
  installed tag, duplicate-tag note, proceed-anyway path.

---

## P1 — functional defects and daily friction

### T3 — Cache the Ollama model list; fetch off the UI thread

- **Covers:** W4, U4, D5
- **Effort:** M
- **Problem:** `_show_profile_detail` calls `list_models()` on every
  selection change, synchronously, with no cache. Probed against a
  counting fake server: window open = 1 fetch, switch to row 1 = 2,
  switch back = 3. Each fetch can block the UI thread up to the
  2-second timeout if Ollama hangs (slow startup, a loaded model, a
  swapping 8 GB box), so clicks can feel dead for up to 2 seconds.
  The New Profile dialog fetches again on open. While Ollama is down
  the tag combo is briefly empty before the stored tag is re-added
  (U4 flicker on every click).
- **Fix:** Fetch the installed-model list once at startup into a
  cache; serve every selection change and every combo fill from the
  cache. Refresh on demand only: a Refresh button, and when the New
  Profile dialog opens. Move the fetch to a background thread so a
  hung Ollama never blocks a click; the UI keeps showing the last
  good list (and the stored tag) while a refresh is in flight.
- **Done:** Against a counting fake Ollama server: 1 fetch at
  startup, 0 fetches across any number of profile selection changes,
  1 fetch on explicit Refresh. With Ollama hung (no response within
  the timeout), profile clicks still respond immediately and the
  stored tag stays visible. Tests: fetch-count test, hung-Ollama
  responsiveness test, refresh-button test.

### T4 — One source of truth for the base: resolve `base_ref`

- **Covers:** W3, D3
- **Effort:** M
- **Problem:** `ollama_tag` and `base_ref` are two fields with one
  meaning and no sync rule. Create with a tag and `base_ref` is set
  to the same value; change the tag later and `base_ref` stays stale
  — probed: tag updated to `lfm3:2b`, `base_ref` still `lfm3:1.7b`.
  Nothing documents which field Item 3 (training) should trust, and
  the New Profile placeholder ("Same as the tag, unless the base
  lives elsewhere") never explains when they *should* differ, so the
  user cannot tell a deliberate split from an accidental one.
- **Fix:** Decide, then implement (the decision is Joshua's call —
  one line): either drop `base_ref` (the tag IS the base ref, with a
  migration that removes it from existing manifests) or define it
  properly as "HF repo / local path for training" with a one-line
  explanation in the UI. Until the decision lands, apply the sync
  rule: changing the tag updates `base_ref` unless the user
  deliberately split them. Document which field training trusts.
- **Done:** The old probe passes: update a tag and `base_ref`
  follows it (or the field is gone and nothing references it). The
  UI explains what the base field is in one line. Existing profiles
  migrate cleanly. The training docs name the field they trust.
  Tests: tag-update sync test, migration test.

### T5 — Trash instead of delete

- **Covers:** W5, D6
- **Effort:** M
- **Problem:** `delete_profile` is `shutil.rmtree` on the profile
  folder: profile, projects, notes, and (from v0.2) checkpoints —
  all gone. The only guard is one Yes/No dialog. No trash, no
  backup, no "export all projects first" offer, no undo. One
  misclick past Yes deletes work that may include hours of training.
- **Fix:** Move deleted profiles to `~/.stella/trash/<slug>-<date>/`
  instead of destroying them, with a purge action (manual, and/or
  automatic after a stated age). Add an "export all projects first"
  offer in the delete dialog. Keep the confirm dialog.
- **Done:** Delete a profile with projects: it leaves the list, and
  its full folder (projects, notes, checkpoints) appears under
  `~/.stella/trash/` with a dated name; restoring it by moving it
  back works. The delete dialog offers to export all projects first.
  Purge removes a trashed profile permanently, with its own confirm.
  Tests: delete-to-trash, trash contents intact, purge.

---

## P2 — missing capabilities and inconsistencies

### T6 — Clone profile

- **Covers:** W10, D7
- **Effort:** S
- **Problem:** Same base, second role means re-entering everything
  by hand. The common case — one base, two jobs (e.g. qwen3.5:2b as
  all-rounder AND as vision backup) — has no shortcut.
- **Fix:** One Clone action (GUI button + `Store.clone_profile`):
  same tag/base/role/processor/config/deps, new name, no projects
  copied (offer to copy projects as an option if it stays simple).
- **Done:** Clone a profile: the new profile appears with the same
  tag, base, role, and settings under its own name, with zero
  projects; the original is untouched. Tests: clone copies fields,
  clone does not copy projects by default, clone-name collision
  rejected.

### T7 — CLI parity: rename, delete, update, show profile

- **Covers:** W9, D11
- **Effort:** S
- **Problem:** The CLI can list and create profiles but cannot
  rename, delete, or change one. Scripted profile management (bulk
  rename after the System Test run, for example) has to go through
  the GUI or hand-edited JSON.
- **Fix:** Add `stella rename-profile <old> <new>`,
  `stella delete-profile <name>` (with the same trash behavior as
  T5, plus a `--purge` flag for permanent removal),
  `stella update-profile <name> [--role ...] [--tag ...]
  [--display ...] [--base ...] [--processor ...]`, and
  `stella show-profile <name>` (full manifest, readable). Reuse the
  Store methods and error messages the GUI already uses.
- **Done:** Each command works end to end from a terminal against a
  scratch home; `delete-profile` moves the profile to trash (T5);
  errors print the same messages as the GUI. Tests for all four
  commands including bad-name and missing-profile exits.

### T8 — Canonical roles wired to the rename plan, with a governing-seat warning

- **Covers:** W6, G2, D8
- **Effort:** M
- **Problem:** There is no canonical seat list, so the rename plan
  (role names from System Test measurements) has nothing to land on,
  and nothing connects a profile's role to a Forge seat or to the
  abliteration guard: a governing seat needs an abliterated base,
  and Stella never checks. A typo'd role ("drvier") silently becomes
  a new pseudo-role.
- **Fix:** Define one canonical role/seat list shared with Forge
  (driver, reviewer, vision, fast, tester, all-rounder, utility —
  confirm the final list with Joshua; it should match the System
  Test rename output). Roles outside the list are still allowed but
  flagged as custom. Add a governing-seat marker on a profile (a
  seat it is bound for, when set): if a governing seat is marked and
  the base is not abliterated, warn before any training starts. (The
  single-control part of W6 — role combo in the detail panel — is
  T9.)
- **Done:** The role field offers the canonical list everywhere it
  appears; a custom role is visibly marked custom; marking a profile
  for a governing seat with a stock base produces a warning naming
  the seat and the base. Tests: canonical list present, custom-role
  flag, governing-seat warning fires and does not fire for an
  abliterated base.

### T9 — Small UI fixes: tooltips, Enter-to-create, real dialog, role combo in detail

- **Covers:** U1, U2, U3, U5, D10; W6 (control-consistency part)
- **Effort:** M
- **Problem:** Four verified UI flaws. (U1) Long tags truncate in
  the profile list (`maternion/minicpm5-heretic:2b` shows as
  `matern...`, `qwen3-vl:2b-instruct` as `qwen3-vl:2b-instru`) and
  there is no tooltip — the only `setToolTip` in the whole GUI is on
  the metamorph combo — so hovering tells you nothing. (U2) Enter
  does nothing in the New Profile dialog: probed,
  `create_btn.isDefault()` is False and no default button is set.
  (U3) The New Profile dialog is a plain QWidget, not a QDialog: a
  separate 420x320 window, not centered on the parent, with no
  dialog framing. (U5) Role is a combo in the dialog but a bare text
  field in the detail panel — same field, two controls, and the
  suggestions vanish the moment the profile exists.
- **Fix:** Set a tooltip on every profile list row showing the full
  display name, role, and tag. Make Create the dialog's default
  button so Enter submits. Convert the New Profile dialog to a real
  QDialog centered on the parent window. Replace the detail panel's
  role text field with the same editable combo (canonical list from
  T8, plus custom entry).
- **Done:** Hovering a truncated row shows the full tag; pressing
  Enter in the New Profile dialog creates the profile; the dialog
  opens centered on the main window with dialog framing; the detail
  panel's role field offers the same suggestions as the dialog.
  Tests: tooltip text present on rows, default-button set, dialog is
  a QDialog, detail role combo offers the canonical list.

### T10 — Make config and dependencies reachable (JSON editor)

- **Covers:** W7, D12; G1 (first step)
- **Effort:** M
- **Problem:** `config` and `dependencies` exist in the manifest and
  `update_profile` allows changing them, but no UI and no CLI
  reaches them — the only way to set them is hand-editing JSON. The
  "own clean environment" half of the profile promise is currently
  unbuildable through Stella itself. Item 3 will need somewhere to
  put per-profile training config.
- **Fix:** Add a config/deps editor to the detail panel: a plain JSON
  text area for `config` and an editable list for `dependencies`,
  validated on save (bad JSON is rejected with the parse error, and
  nothing is written). Expose both through `update-profile` (T7) as
  well. This is the first step toward G1; full environment
  management is T18.
- **Done:** Edit config JSON in the detail panel, save, reopen: the
  values persist and `show-profile` prints them. Invalid JSON is
  refused with a readable error and the old values stay. Tests:
  save-through, invalid-JSON rejection, CLI update path.

### T11 — Define the `processor` field

- **Covers:** W8
- **Effort:** S
- **Problem:** `processor` is a bare text field with no label help,
  no picker, no validation. Is it a tokenizer name, a processor
  class, a local path? The user cannot tell from the window, and
  nothing downstream reads it yet — it is a field waiting for a
  definition.
- **Fix:** Decide what `processor` means (one-line decision needed
  from Joshua: tokenizer/processor identifier, class name, or local
  path — or drop the field if Item 3 does not need it). Then: a
  one-line explanation beside the field, validation or a picker
  matching the definition, and a README line documenting it.
- **Done:** The UI explains what `processor` is in one line; an
  invalid value is rejected or warned about (per the definition);
  the README documents the field. If the decision is to drop it, the
  field is removed from the manifest, the GUI, and the docs, with a
  migration for existing profiles.

### T12 — Export a profile on its own

- **Covers:** G4
- **Effort:** M
- **Problem:** Export is per-project; a profile with zero projects
  cannot be moved, backed up, or shared. Combined with W5, the only
  copy of a profile is the live one.
- **Fix:** Add profile export: a package holding the profile manifest
  (and, as an option, all its projects), importable back with the
  same verification the project import already does. Note the seam:
  the package format belongs to export/import, so this task should
  land alongside (or just after) audit #3's export/import work to
  avoid two formats.
- **Done:** Export a project-less profile, delete it, import the
  package: the profile returns with tag, role, base, and settings
  intact. Export with projects includes them. A corrupt profile
  package is refused with a readable error. Tests: round-trip with
  and without projects, corrupt-package rejection.

---

## P3 — polish, display, and scale

### T13 — Health badge per profile row

- **Covers:** W11, U6, D1
- **Effort:** S
- **Depends on:** T3 (cached model list)
- **Problem:** Nothing shows whether a profile's tag is actually
  installed. A tag removed from Ollama (`ollama rm`) leaves a
  profile pointing at a missing model with no sign — it looks
  exactly as healthy as every other row until training fails. All
  rows look equally healthy: a profile pointing at a missing model,
  a profile with no tag at all, and a good profile are visually
  identical (U6).
- **Fix:** Using the cached model list from T3, show a health badge
  on each row: installed ✓, missing ✗, Ollama down ?. A profile
  pointing at a removed model should look broken at a glance. A
  profile with no tag shows a distinct "no tag" state.
- **Done:** With Ollama up: installed tags show ✓, a removed tag
  shows ✗, a tag-less profile shows "no tag". With Ollama down: all
  rows show ?. Badges update on Refresh (T3). Tests: badge states
  against a fake server, Ollama-down state.

### T14 — Show what the profile points at (model metadata in the detail panel)

- **Covers:** G3, D9; G5 (last-used); W12 (project count, created/updated display)
- **Effort:** M
- **Problem:** A profile knows only a tag string. No size, quant,
  context length, or capabilities (vision? tools?) are recorded or
  shown, though Ollama's `/api/show` provides them. The list row
  shows no project count, and `created`/`updated` are recorded but
  never displayed (W12). There is no last-used date or activity of
  any kind (G5).
- **Fix:** Fetch model metadata from a cached `/api/show` (same cache
  discipline as T3 — never on the UI thread, never per click) and
  show size, quant, context length, and capabilities in the detail
  panel. Show the project count in the list row and in the detail
  panel, the created/updated dates, and a last-used date — record
  last-used when a profile is selected for training or a project
  under it is trained (define the trigger in the implementation and
  document it).
- **Done:** The detail panel shows size, quant, context, and
  capabilities for an installed tag (from a fake `/api/show` in
  tests), a project count, created/updated dates, and a last-used
  date that updates after a training run. List rows show the project
  count. With Ollama down, metadata shows as unavailable, not as
  blank or wrong. Tests: metadata display from fake `/api/show`,
  project count, last-used update, Ollama-down display.

### T15 — Profile-level notes

- **Covers:** W12 (profile notes)
- **Effort:** S
- **Problem:** Projects have `notes.md`, profiles do not. There is
  nowhere to write why a profile exists, what it is for, or what was
  learned about its base.
- **Fix:** Add `notes.md` per profile (same pattern as project
  notes: `read_notes`/`write_notes` on the Store) with an editor in
  the detail panel and a Save path through the existing Save profile
  flow. Include profile notes in profile export (T12).
- **Done:** Write notes in the detail panel, save, reopen: the notes
  persist. Notes survive rename. Profile export includes them.
  Tests: notes round-trip, notes survive rename.

### T16 — Search, filter, and sort for the profile list

- **Covers:** W12 (search/filter/sort); G6 (search/sort part)
- **Effort:** M
- **Problem:** No search, filter, or sort in the list. Fine at 11
  profiles, thin at 30+. No multi-select or bulk operations either
  (G6 — bulk work is T17).
- **Fix:** Add a filter box above the profile list (matches display
  name, slug, role, and tag), a role filter, and sort options
  (name, role, recently used, project count). Filtering must keep
  the current selection when the selected profile still matches.
- **Done:** Typing in the filter narrows the list live; the role
  filter shows only that role; each sort order reorders correctly;
  selection survives filtering when the profile still matches.
  Tests: filter by text, filter by role, each sort order, selection
  preserved.

### T17 — Bulk operations (multi-select)

- **Covers:** G6 (bulk part)
- **Effort:** M
- **Problem:** No multi-select, no bulk operations — acceptable now,
  a wall later. Every profile action is one at a time.
- **Fix:** Multi-select in the profile list (Ctrl/Shift-click) with
  bulk actions: delete (to trash, T5 — one confirm naming all
  selected), export (T12, one package per profile or a bundle), and
  role change. Single-selection behavior must not change.
- **Done:** Select three profiles, bulk-delete: all three land in
  trash with one confirm naming them. Bulk-export produces one
  package per profile. Bulk role change updates all selected.
  Single-click selection and all single-profile actions still work
  exactly as before. Tests: multi-select delete/export/role change,
  single-selection unchanged.

### T18 — Per-profile environment management (full G1)

- **Covers:** G1 (full)
- **Effort:** L
- **Depends on:** T10 (config/deps reachable)
- **Problem:** Profiles were specced as a clean environment per base
  (weights, config, processor/tokenizer, dependencies). Config/deps
  are dead fields (W7 — first step is T10), there is no per-profile
  venv or dependency install, and no record of which Python packages
  a profile's training needs.
- **Fix:** Design, then build — scope needs Joshua's direction
  before implementation: per-profile venv vs. a shared training venv
  vs. a dependency record only. At minimum: each profile records the
  Python packages its training needs, and `install-training.sh` can
  install from that record. If per-profile venvs are chosen, add
  create/activate/remove per profile and a disk-usage readout (venv
  sizes add up fast on a 1 TB HDD shared with Ollama models).
- **Done:** Per the agreed scope: a profile's dependency record is
  visible and editable (via T10), and the training installer
  consumes it. If venvs are in scope: creating a profile's
  environment, using it for a training run, and removing it all work
  from the GUI, with disk usage shown. Tests per the agreed scope.

---

## Coverage map

Every finding ID from the audit, and the task(s) covering it. Nothing
dropped.

| Finding | Task(s) | Notes |
|---|---|---|
| W1 — corrupt manifest vanishes silently | T1 | Damaged row + Repair + tests |
| W2 — any string accepted as a tag | T2 | Soft validation, warn don't block |
| W3 — tag/base_ref drift | T4 | One source of truth + sync rule |
| W4 — every click re-fetches Ollama | T3 | Cache + off-thread fetch |
| W5 — delete unrecoverable | T5 | Trash + export-first offer |
| W6 — role is two controls, no canonical list | T8, T9 | T8 canonical list + seat warning; T9 single role combo |
| W7 — config/deps dead fields | T10 | JSON editor; first step of G1 |
| W8 — processor undefined | T11 | Define it, label it, validate it |
| W9 — no CLI for rename/delete/update | T7 | Four new CLI commands |
| W10 — no clone profile | T6 | Clone action |
| W11 — no health indicator | T13 | Health badges (needs T3) |
| W12 — small missing pieces | T2, T14, T15, T16 | T2 duplicate-tag note; T14 project count + created/updated; T15 notes; T16 search/filter/sort |
| U1 — long tags truncate, no tooltip | T9 | Tooltips on rows |
| U2 — Enter does nothing in dialog | T9 | Default button |
| U3 — dialog is a QWidget, not QDialog | T9 | Real QDialog, centered |
| U4 — tag combo re-fetch flicker | T3 | Cache removes the re-fetch |
| U5 — role combo vs text field | T9 | Role combo in detail panel too |
| U6 — all rows look equally healthy | T13 | Health badges |
| G1 — no environment management | T10, T18 | T10 first step (reachable fields); T18 full build |
| G2 — no seat mapping | T8 | Canonical roles + governing-seat warning |
| G3 — no model metadata | T14 | Cached /api/show display |
| G4 — profile cannot be exported alone | T12 | Profile export (seam with audit #3) |
| G5 — no profile history | T14 | Last-used date |
| G6 — no bulk operations | T16, T17 | T16 search/sort; T17 multi-select bulk |
| D1 — health badge per row | T13 | |
| D2 — soft tag validation | T2 | |
| D3 — one source of truth for base | T4 | |
| D4 — never silently vanish | T1 | |
| D5 — cache model list, off UI thread | T3 | |
| D6 — trash, not delete | T5 | |
| D7 — clone profile | T6 | |
| D8 — canonical roles, rename plan | T8 | |
| D9 — show what the profile points at | T14 | |
| D10 — small UI fixes | T9 | |
| D11 — CLI parity | T7 | |
| D12 — config/deps reachable | T10 | |

**Coverage check:** 12 weaknesses + 6 UI flaws + 6 gaps + 12 design
suggestions = 36 findings. All 36 appear in the map above, each with
at least one task. 18 tasks total: 2 P0 (T1–T2), 3 P1 (T3–T5),
7 P2 (T6–T12), 6 P3 (T13–T18).

**Dependency order (within the priority order above):** T3 before
T13 (badges need the cache); T8 before T9 (the detail role combo
shows the canonical list); T5 before T7's `delete-profile` and T17's
bulk delete (both delete to trash); T10 before T18 (reachable fields
before full environment management); T12 before T17's bulk export
(profile export must exist first). T2 works standalone with a direct
fetch; T3's cache improves it later.
