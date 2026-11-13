# STELLA Audit #1 — Profiles

**Audited:** 2026-11-12 ~19:00 EST, against the v0.1 tree as shipped
(commit e28db915, Release v0.1). Scope: everything a *profile* is and
does — the data model, the profile pane, the detail panel, the New
Profile dialog, the CLI profile commands, and the Ollama tag lookup.
Projects, export/import, the window as a whole, the CLI as a whole,
the installer, and MetaMorphAi get their own audits (#2–#7).

**Method:** read `stella/model.py`, `stella/gui.py`, `stella/cli.py`,
`stella/ollama.py` in full; probed live behavior with a scratch home
and a counting fake Ollama server; checked test coverage. Every
weakness below was verified by probe or direct code citation — nothing
here is assumed. Probe script: `/tmp/profile-probes.py`,
`/tmp/profile-probe2.py` (scratch, not shipped).

**Design intent (from the brief):** a profile is one base model with
its own clean environment — weights, config, processor/tokenizer,
dependencies — and the base stays untouched. Profiles carry friendly
role/seat names so the roster reads by job, not by cryptic tag.

---

## 1. Features and functions

### Data model (`model.py`, `Store`)

- A profile is a folder `~/.stella/profiles/<slug>/` holding
  `profile.json` plus a `projects/` subfolder. Everything is plain
  JSON + Markdown, hand-readable and hand-fixable.
- Manifest fields: `name` (slug), `display_name`, `role`,
  `ollama_tag`, `base_ref`, `processor`, `config` (object),
  `dependencies` (list), `stella_version`, `kind`, `created`,
  `updated`.
- Full CRUD: `create_profile`, `get_profile`, `list_profiles`,
  `update_profile` (7 allowed fields), `rename_profile`,
  `delete_profile`.
- Slug rules: lowercase letters/digits/dash/underscore, must start
  alphanumeric, max 64 chars; input is stripped and lowercased.
- Rename updates the `name` in the manifest, the `display_name` when
  it still equals the old slug, the `updated` stamp, and the stored
  `profile` pointer inside every project in that profile.
- Delete removes the whole folder (profile + all its projects).
- Writes are atomic: write to `.json.tmp`, then replace.
- Paths are containment-checked (`_check_inside`): a slug can never
  climb out of the Stella home.
- `list_profiles` returns manifests sorted by directory name; a
  manifest that fails to parse is skipped.
- The base model is never touched: Stella stores only a reference
  (an Ollama tag or a path string).

### GUI — profile pane + detail panel (`gui.py`)

- Left pane lists profiles as `Display name  [role]  — tag`
  (role and tag omitted when empty). New / Rename / Delete buttons
  under the list.
- Selecting a profile loads its projects into the middle pane and
  its fields into the right detail panel: Display name, Role,
  Ollama tag (editable combo), Base ref, Processor, Save profile.
- New Profile dialog: Name, Display name, Role (editable combo with
  8 suggestions: driver, reviewer, vision, fast, all-rounder,
  generalist, utility, tester), Ollama tag (editable combo fed from
  the local Ollama install), Base ref, Create / Cancel.
- Delete asks once ("Delete profile X and all its projects? This
  cannot be undone.") and only proceeds on Yes.
- The detail panel's tag combo is refilled from Ollama on every
  profile selection; the stored tag is re-added if it is not in the
  installed list.
- Status bar reports the current profile + project.

### CLI (`cli.py`)

- `stella profiles` — lists `name, role, base tag` (falls back to
  `base_ref` when no tag), with a hint on how to create one when the
  list is empty.
- `stella create-profile <name> --tag --role --display`.
- No CLI for rename, delete, update, or show-one-profile.

### Ollama lookup (`ollama.py`)

- `list_models()` hits `GET /api/tags` on localhost:11434 (or
  `STELLA_OLLAMA_URL`), 2-second timeout, sorted tag list.
- Offline-safe: any failure (down, refused, bad payload, timeout)
  returns `[]`; no exception escapes. The GUI falls back to manual
  tag entry with a note ("Ollama is not answering — type the tag by
  hand.").

### Tests covering profiles

- `test_model.py` (19 tests): CRUD, rename incl. projects' stored
  profile pointer, delete, slug validation (rejects `..`, `a/b`,
  spaces, dots, over-long names; lowercases input), path-escape
  blocking.
- `test_ollama.py` (3 tests): list from a fake server, empty list
  when down, empty list on a bad payload.
- `test_gui.py` (8 tests): list display with role + tag, detail
  fills from selection, save profile writes through, empty-store
  window, no `&` in visible labels, frame grab, status-bar-only
  regression test.
- No test covers a corrupt/broken manifest (see W1).

---

## 2. Strengths

1. **The base is genuinely untouchable.** Profiles hold references
   only; no code path writes to a model. The core design promise
   holds in the implementation, not just the docs.
2. **Slug + containment discipline is airtight.** Names are
   validated at every entry point (GUI, CLI, Store), paths are
   resolved and checked against the home dir, and the escape cases
   are tested. A hostile or mistyped name cannot write outside
   `~/.stella/`.
3. **Crash-safe writes.** Every manifest write goes through
   tmp-file + atomic replace, so a crash or power cut leaves either
   the old file or the new one — never a half-written file. (Which
   makes W1 worse, not better: the main way a manifest goes corrupt
   now is a hand edit, and that is exactly the case with no warning.)
4. **Rename is thorough.** It updates the manifest, the
   display-name-when-default, the timestamp, and every project's
   stored profile pointer — tested. Renames do not orphan projects.
5. **Offline-first Ollama handling.** The lookup never crashes, never
   hangs past 2 seconds, and the GUI degrades to manual entry with a
   clear note. On a WiFi-only machine with Ollama sometimes down,
   this is the right shape.
6. **Delete asks first.** The GUI confirm dialog names the profile
   and says all its projects go too. (One dialog is the whole guard
   — see W5.)
7. **The role label works.** `Display name [role] — tag` in the list
   is exactly the rename-plan idea in miniature: the roster reads by
   job. Role suggestions in the dialog (driver, reviewer, vision…)
   match the Forge seats.
8. **Plain-text home.** JSON + Markdown means Joshua can read or fix
   a profile in the GUI text editor without Stella running — a real
   fit for his workflow.
9. **Timestamps are kept.** `created` and `updated` are recorded on
   every profile (though nothing displays them yet — see W12).

---

## 3. Weaknesses (all verified)

### W1 — A corrupt manifest makes a profile VANISH silently (P0)

`list_profiles` catches the parse error and `continue`s — no warning,
no row, no log. Probed: corrupting `bogus/profile.json` to
`{invalid json` removed the profile from the list entirely, while
`get_profile("bogus")` still raises a clear "not valid JSON" error.
So the profile and all its projects become invisible in the GUI and
CLI, with no indication anything is wrong. The likely cause is a
hand edit (the home is meant to be hand-editable), so the user most
likely to hit this is the user doing exactly what the docs invite.
No test covers it.

### W2 — Any string is accepted as an Ollama tag (P0)

Probed: `create_profile("bogus", ollama_tag="not-a-real-model:99")`
succeeds and stores the tag. The GUI picker offers real tags, but the
combo is editable and nothing checks the typed value — not at create,
not at save. A typo (`lfm3:1.7bb`, `qwen3-v1` instead of `qwen3-vl`)
only fails later, at train or export time, far from the mistake and
with an error that will not point back at the profile.

### W3 — `ollama_tag` and `base_ref` drift apart (P1)

Create with a tag and `base_ref` is set to the same value. Change the
tag later and `base_ref` stays stale — probed: tag updated to
`lfm3:2b`, `base_ref` still `lfm3:1.7b`. Two fields, one meaning, no
sync rule, and no documented answer to which one Item 3 (training)
should trust. The New Profile placeholder ("Same as the tag, unless
the base lives elsewhere") never explains when they *should* differ,
so the user cannot tell a deliberate split from an accidental one.

### W4 — Every profile click re-fetches Ollama, on the UI thread (P1)

`_show_profile_detail` calls `list_models()` on every selection
change, synchronously, with no cache. Probed against a counting fake
server: window open = 1 fetch, switch to row 1 = 2, switch back = 3.
Each fetch can block the UI thread up to the 2-second timeout if
Ollama hangs (slow startup, a loaded model, a swapping 8 GB box).
Clicks can feel dead for up to 2 seconds, and the installed-model
list is re-downloaded for every single click even though it almost
never changes. The New Profile dialog fetches again on open.

### W5 — Delete is unrecoverable (P1)

`delete_profile` is `shutil.rmtree` on the profile folder: profile,
projects, notes, and (from v0.2) checkpoints — all gone. The only
guard is one Yes/No dialog. No trash, no backup, no "export all
projects first" offer, no undo. One misclick past Yes deletes work
that may include hours of training.

### W6 — Role is two different controls with no canonical list (P2)

The New Profile dialog offers an editable combo with 8 suggestions;
the detail panel is a bare text field with no suggestions. A typo in
either place ("drvier") silently becomes a new pseudo-role. There is
no canonical seat list, so the rename plan (role names from System
Test measurements) has nothing to land on, and nothing connects a
profile's role to a Forge seat or to the abliteration guard (a
governing seat needs an abliterated base — Stella never checks).

### W7 — `config` and `dependencies` are dead fields (P2)

They exist in the manifest and `update_profile` allows changing them,
but no UI and no CLI reaches them — the only way to set them is
hand-editing JSON. The "own clean environment" half of the profile
promise is currently unbuildable through Stella itself.

### W8 — `processor` has no defined meaning in the UI (P2)

A bare text field with no label help, no picker, no validation. Is it
a tokenizer name, a processor class, a local path? The user cannot
tell from the window, and nothing downstream reads it yet — it is a
field waiting for a definition.

### W9 — No CLI for rename, delete, or update (P2)

The CLI can list and create profiles but cannot rename, delete, or
change one. Scripted profile management (bulk rename after the System
Test run, for example) has to go through the GUI or hand-edited JSON.

### W10 — No duplicate / clone profile (P2)

Same base, second role means re-entering everything by hand. The
common case — one base, two jobs (e.g. qwen3.5:2b as all-rounder AND
as vision backup) — has no shortcut.

### W11 — No health indicator (P2)

Nothing shows whether a profile's tag is actually installed. A tag
removed from Ollama (`ollama rm`) leaves a profile pointing at a
missing model with no sign — it looks exactly as healthy as every
other row until training fails.

### W12 — Small missing pieces (P3)

No project count in the list row; `created`/`updated` are recorded
but never displayed; no profile-level notes (projects have notes,
profiles do not); no search, filter, or sort in the list (fine at
11 profiles, thin at 30+); no check that two profiles point at the
same tag (allowed by design, but nothing notes it).

---

## 4. UI flaws (verified)

- **U1 — Long tags truncate with no way to read them.** In the v0.1
  screenshot, `maternion/minicpm5-heretic:2b` shows as `matern...`
  and `qwen3-vl:2b-instruct` as `qwen3-vl:2b-instru`. The pane has a
  horizontal scrollbar, but there is no tooltip: the only
  `setToolTip` in the entire GUI is on the metamorph combo. Hovering
  tells you nothing.
- **U2 — Enter does nothing in the New Profile dialog.** Probed:
  `create_btn.isDefault()` is False and no default button is set.
  Typing a name and pressing Enter just sits there; the user must
  click Create.
- **U3 — The New Profile dialog is a plain QWidget, not a QDialog.**
  It opens as a separate 420x320 window, not centered on the parent,
  with no dialog framing. It reads as unanchored next to the main
  window.
  CORRECTION (audit #4, 2026-11-12): the "separate window" description
  was wrong — it is not a separate window at all. The widget has a
  parent and no Qt.Window flag, so it renders as a frameless,
  background-less form smeared over the top-left of the main window
  at (0,0), its labels overlapping the header and both lists
  (screenshot verified in audit #4). The fix direction stands — make
  it a real QDialog — and audit #4 raises it to P0 (W1).
- **U4 — The tag combo re-fetches on every selection (see W4).**
  While Ollama is down the combo is briefly empty before the stored
  tag is re-added — a small flicker on every click.
- **U5 — Role is a combo in the dialog, a text field in the detail
  panel.** Same field, two controls; the suggestions vanish the
  moment the profile exists.
- **U6 — All rows look equally healthy.** A profile pointing at a
  missing model, a profile with no tag at all, and a good profile
  are visually identical (see W11).

---

## 5. Gaps (against the design intent)

- **G1 — No environment management.** Profiles were specced as a
  clean environment per base (weights, config, processor/tokenizer,
  dependencies). Config/deps are dead fields (W7), there is no
  per-profile venv or dependency install, and no record of which
  Python packages a profile's training needs.
- **G2 — No seat mapping.** The rename plan needs canonical role
  names tied to Forge seats; Stella has free-text roles and no seat
  concept. The abliteration guard (governing seats need abliterated
  bases) lives only in Forge — Stella cannot warn when a profile is
  bound for a seat its base must not hold.
- **G3 — No model metadata.** A profile knows only a tag string. No
  size, quant, context length, or capabilities (vision? tools?) are
  recorded or shown, though Ollama's `/api/show` provides them.
- **G4 — A profile cannot be exported on its own.** Export is
  per-project; a profile with zero projects cannot be moved,
  backed up, or shared. Combined with W5, the only copy of a
  profile is the live one.
- **G5 — No profile history.** No last-used date, no record of which
  project last trained, no activity of any kind.
- **G6 — No bulk operations.** No multi-select, no search, no sort —
  acceptable now, a wall later.

---

## 6. Innovation and design suggestions

- **D1 — Health badge per row.** One cached `/api/tags` fetch at
  startup: installed ✓, missing ✗, Ollama down ?. A profile pointing
  at a removed model should look broken at a glance.
- **D2 — Soft tag validation, not a block.** At create/save, if the
  tag is not in the cached installed list, warn ("not installed
  locally — is this right?") and let him proceed. Catches typos
  without blocking deliberate entries (a tag he is about to pull).
- **D3 — Kill the ambiguity: one source of truth for the base.**
  Either drop `base_ref` (the tag IS the base ref) or define it
  properly as "HF repo / local path for training" with a one-line
  explanation. Until then, the sync rule should be: changing the tag
  updates `base_ref` unless the user deliberately split them.
- **D4 — Never silently vanish.** A broken manifest should show as a
  greyed "damaged" row with the parse error and a Repair action
  (open the JSON in the editor). The data is still on disk; the UI
  should say so.
- **D5 — Cache the model list; fetch off the UI thread.** Fetch once
  at startup, refresh on demand (button + when the New Profile
  dialog opens), and never block a click on the network.
- **D6 — Trash, not delete.** Move deleted profiles to
  `~/.stella/trash/<slug>-<date>/` and purge later (or on demand).
  Offer "export all projects first" in the delete dialog.
- **D7 — Clone profile.** One action: same tag/base/role, new name,
  no projects copied (or optionally copied).
- **D8 — Canonical roles wired to the rename plan.** A seat list
  (driver, reviewer, vision, fast, tester, all-rounder, utility)
  shared with Forge, plus the governing-seat warning: a profile
  marked for a governing seat whose base is not abliterated gets
  flagged before any training starts.
- **D9 — Show what the profile points at.** Size, quant, context,
  capabilities from a cached `/api/show`, plus project count,
  created date, and last-used, in the detail panel.
- **D10 — Small UI fixes:** tooltips on truncated rows; Enter creates
  in the dialog (default button); make it a real QDialog centered on
  the parent; role combo with suggestions in the detail panel too.
- **D11 — CLI parity:** `rename-profile`, `delete-profile`,
  `update-profile` (role/tag/display), `show-profile`.
- **D12 — Make config/deps reachable:** even a plain JSON text area
  in the detail panel, validated on save, beats dead fields — and
  Item 3 will need somewhere to put per-profile training config.

---

## 7. Recommended improvements (his to direct)

- **P0:** D4 damaged-row + a test for corrupt manifests (W1);
  D2 soft tag validation (W2).
- **P1:** D5 cached/off-thread Ollama fetch (W4); D3 base-ref rule
  (W3); D6 trash-on-delete (W5).
- **P2:** D7 clone (W10); D11 CLI parity (W9); D8 canonical roles
  (W6/G2); D10 tooltips/Enter/dialog (U1–U3, U5); D12 config/deps
  editor (W7).
- **P3:** D1 health badges (W11) — needs D5 first; D9 metadata
  display (G3); profile notes; search/filter (W12/G6).

## 8. Out of scope for this audit

Projects (#2), export/import (#3), the window as a whole (#4), the
CLI as a whole (#5), installer + icon (#6), MetaMorphAi hooks (#7),
and the training engine (Item 3, in flight — audited after v0.2
ships). The `list_projects` silent-skip shares W1's pattern and will
be covered under #2.
