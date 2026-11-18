# Changelog

## v0.31.0 — 2026-11-18

Joshua's order from his real-PC session the same day v0.30.0
shipped: he opened the Profile window and saw Display name /
Role / Governing seat / Ollama tag / Base ref / Config (JSON) /
"quant Q4_K_M, 3.4B parameters, can do: completion, tools" — and
said he did not know what any of it was, invoking the 5-year-old
rule ("it should be easy enough for [a] child to use? This
isnt"). Then: "I also dont know what you mean by assigning it
roles neither I shouldn't need to do that... it shoukd be able
to get the accurate weights and know what the model is good at
and what it isnt good at". This version is the answer.

- The profile window is child-simple now. What opens is the
  model's name, what it does in plain words ("It can write and
  answer, and use tools."), what it is good and not good at,
  whether its training files are ready with one button to get
  them, and its projects with a Start a project button.
- Everything technical lives behind one Details flap, closed by
  default and still fully working: the derived role (read-only),
  the governing-seat binding, the Ollama tag, the Hugging Face
  repo, the technical stats line, and the config. Nothing was
  deleted.
- Nobody assigns roles by hand anymore. The role is worked out
  from the model by a curated strengths table (stella/
  strengths.py), grounded only in the roster audit and OST's
  graded results — never fabricated. Unknown models say "Not
  measured yet". The role field stays in the profile record, so
  the tree filter, the probe sets, and the governing-seat
  warning all keep working off derived roles; a governing role
  is derived only for the three tags that actually hold those
  seats in Forge. The bulk Change role menu action is gone.
- The How to Use topics for Profiles and Governing seats now
  describe the simple window and the derived role.

## v0.30.0 — 2026-11-18

A real-PC defect Joshua hit minutes after the v0.29.0 release:
pressing "Get its weights" on a profile picked from Ollama
dead-ended with "No Hugging Face repo set for this profile. Open
the profile and set Base ref..." — jargon he rightly called out
("This shit should pull from huggingface automatically"). The
Ollama bridge already knew the answer and nothing used it. Now
every "no repo" wall offers it: one candidate gets a Yes/No
question naming the repo and where it comes from, and Yes stores
it and starts the download at once; several get a pick-one
dialog; an unknown tag gets plain words. The chat tools offer the
same bridge in text form with a confirm round-trip, and the words
"Base ref" no longer appear in any user-visible string.

- The download, the train pre-check, and the "Set the model
  source..." button all offer the bridge repo on a no-repo
  profile, and a pick starts the download immediately.
- The chat's download_weights and start_training tools suggest
  the bridge repo and ask; a call with "confirm": true and a
  "repo" naming a suggested candidate stores it and proceeds. A
  repo the bridge did not suggest is refused, never stored.
- The profile window's field is now labelled "Hugging Face repo",
  and the How to Use topics say the same. The storage key stays
  base_ref.
- A mismatch guard in the download: when the stored repo is a
  valid id but not the bridge's for the profile's model (Joshua
  typed the old message's LFM3 example into his Granite profile),
  the download warns once, names both repos, and offers "Use the
  usual repo instead" or "Keep the one set". A warning, never a
  block; a tag the bridge does not know never warns.

A second real-PC defect, found the same day running
install-training.sh: the training install downloaded every wheel,
then failed at the install step with "Could not find a version
that satisfies the requirement torch==2.15.0+cpu". The cause was
the wheel file name: pip's report spells torch's version with
%2B, and the fetch saved the wheel under that encoded name,
which pip's --find-links cannot parse as a version.

- The wheel fetch now URL-decodes the file name before saving,
  so torch lands as torch-2.15.0+cpu-...whl. The traversal guard
  still holds (decoding happens after taking the last path
  segment; a decoded slash is rejected).
- A wheel already saved under the old encoded name is renamed
  into place when it matches its hash — never re-downloaded.
- When the local-wheel install fails, install-training.sh now
  falls through to the direct download instead of dying with
  "run it again" (a re-run would repeat the identical failure).
  The download-failed error only shows when both paths fail.

## v0.29.0 — 2026-11-18

The last P3 batch of the 2026-11-15 full-product review
(R103–R129): cloud chat that streams and shows what it cost,
five new CLI commands, a click-only doctor, a pytest config
with timeouts, and the docs refreshed to match the real
layout. That closes the list: 124 of 129 tasks done, the
remaining 5 needing Joshua's PC. Full record:
docs/stella-review-task-list-2026-11-15.md.

- R103 — The chat tool help now documents the `resume` and
  `dest` arguments, so the agent's options can be learned
  from the help instead of guessed.
- R104 — Cloud chat replies stream in as they arrive (Groq,
  Gemini, custom) instead of arriving all at once after a
  long silence.
- R105 — A damaged providers.json now says so in plain words
  and offers to reset it (with a backup first) instead of
  silently pretending no keys are saved.
- R106 — Cloud chat shows what each reply used in tokens
  ("That reply used 16 tokens (12 sent, 4 back)"), in the
  window and on the terminal.
- R107 — Every training-setting flag's help now says what it
  does, its range, and its default; --method names its values.
- R108 — `probe --json` prints a JSON error object on
  failure, like `verify` does, so scripts get JSON on every
  path.
- R109 — The stella-cli header comment no longer lists
  commands (it had gone stale twice); it points at --help
  instead.
- R110 — CLI help says "Mode" like the GUI does; the word
  "MetaMorphAi" no longer appears in CLI help.
- R111 — Four small CLI fixes: delete errors name the
  profile; the HF Hub advisory no longer leaks onto a dry
  run; the doubled "rough" is gone; the pull-weights line
  prints only when a pull starts.
- R112 — Five new CLI commands: mark-ready, notes (read or
  --set), probe-results, howto, and debug-report.
- R113 — The window now says in plain words that training
  settings are changed from the terminal, with the exact
  command, in the project panel, the session summary, and
  the How to Use Training topic.
- R114 — The README records that the installer file itself
  shows a generic icon before install (a limit of the
  desktop file format, no spec-compliant fix) — accepted,
  not a missing file.
- R115 — Uninstall's manual icon removal now runs as a real
  fallback when the venv-branch remover fails, instead of
  silently leaving icons behind.
- R116 — Uninstall offers to clear the pip cache (about 2 GB
  after a training install), naming the size, default No.
- R117 — A failed re-install no longer deletes the previous
  good install receipt; the receipt is only replaced by a
  successful install.
- R118 — The icon render runs with
  QT_QPA_PLATFORM=offscreen, so icons render on a
  display-less run.
- R119 — The desktop icon lands on the real desktop folder
  (via xdg-user-dir DESKTOP, ~/Desktop fallback), and
  uninstall removes it from there too.
- R120 — CI runs desktop-file-validate and shellcheck in a
  lint job and runs on a weekly schedule.
- R121 — The doctor runs by clicking: a new "Repair Stella"
  desktop entry, no terminal needed, and it works even with
  the venv deleted.
- R122 — PROMPTS_VERSION is 3, matching the per-role prompt
  battery from v0.22.
- R123 — The dream-skip string typo is fixed ("(...) .
  Dreaming skipped" lost its stray space).
- R124 — A new sleep manifest carries the real Stella
  version; the manifest-format version lives under its own
  sleep_version key.
- R125 — The probe gate matches whole words now, so
  "breakfast" and "screwdriver" no longer trip it.
- R126 — Dreaming gives up early on a silent Ollama (30 s
  silence budget) instead of stalling the full 120 s; the
  120 s generation budget for a slow-but-answering model is
  unchanged.
- R127 — TEST-REPORT.md carries the real suite counts, and
  the package docstring no longer says v0.8.0 (the
  versioned feature list is dropped; the changelog is the
  version record).
- R128 — A pytest.ini sets a 300 s per-test timeout and a
  gui marker, so one hung test cannot hold CI for six
  hours; pytest-timeout is wired into run_tests.sh and CI.
- R129 — FORMAT.md matches the current store: example
  version 0.29.0, governing_seat and last_used in the
  profile block, dataset/ in the layout.

## v0.28.0 — 2026-11-18

The first P3 batch of the 2026-11-15 full-product review
(R76–R102, minus R92 which shipped in v0.27.0): training honesty
(plain-words out-of-memory, a disk check before a run starts,
orphan checkpoints reaped, settings that re-resolve when the
model changes), a CLI that asks before deleting, a trash that
shows its size and clears out old items on its own, a job that
can be un-picked, Quit in the File menu, a finish moment that
lingers, drag-and-drop for a dataset file, one shortcuts registry
behind the Shortcuts topic, and cloud models as buttons in the
chat window. Full record:
docs/stella-review-task-list-2026-11-15.md.

- R76 — An out-of-memory failure during training says so in
  plain words ("the PC ran out of memory") with what to do
  next, instead of a raw traceback. The shared wording lives in
  tool_errors.py.
- R77 — Checkpoints save through a temp file + rename, so a
  crash mid-save leaves no half checkpoint behind. Orphans are
  reaped when a run starts, and `delete-checkpoint` /
  `prune-checkpoints` manage them from the CLI.
- R78 — Auto-settings now react to the model and the machine:
  a model of 3B or more trains smaller, under 10 GB of disk
  checkpoints less often, and 2 CPUs or fewer trains shorter
  sequences. A run-start refresh announces any change.
- R79 — A run is refused before it starts when the disk cannot
  hold the checkpoints, with 512 MB of headroom. Existing
  checkpoint bytes are not double-counted.
- R80 — Raw error text from Ollama and from Hugging Face loads
  no longer reaches the user; the plain-words message is shown
  and the raw text is kept on the exception chain.
- R81 — `export-gguf` on the CLI prints the size estimate
  first, like the window does.
- R82 — `ollama create` gets a 30-minute timeout from the CLI
  and the window, so a stuck create cannot hang forever.
- R83 — The stale merged-model directory is cleared inside the
  job lock with a lock-time re-check, so two exports cannot
  delete each other's work.
- R84 — A Modelfile FROM line with a quoted path (spaces in
  the folder) is read right: one pair of matching quotes is
  stripped, and unquoted spaced paths still work.
- R85 — A prompts file saved with a byte-order mark (Windows
  editors do this) reads cleanly; the mark is stripped.
- R86 — Each requant run gets its own temp job directory for
  the GGUF and the Modelfile, so two requants can no longer
  overwrite each other's files.
- R87 — A base model reference that cannot be found gets a
  health warning on GUI save, on import, and on the CLI when
  the user explicitly sets it. Tag-valued bases (the store's
  synced default) are not flagged.
- R88 — `settings_source` (auto vs manual) survives an export
  and an import: the package manifest carries it, validates it,
  and restores it. Documented in docs/FORMAT.md.
- R89 — The LFM3 template's dead `notes` key is gone, and a
  guard test fails if any template carries a dropped key again.
- R90 — `delete-profile` and `delete-project` on the CLI ask
  first (the window already did); `--yes` skips the prompt.
- R91 — Trash shows each item's size and a total, and items
  older than 30 days are purged when the Trash window opens.
- R93 — A picked job can be un-picked: clicking it again
  disarms Go. Switching jobs still keeps at most one picked.
- R94 — Quit is in the File menu with Ctrl+Q, wired to the
  same close path as the window chrome, so a running job gets
  the same stop-and-wait.
- R95 — The finish moment lingers 2.5 s (was 250 ms), long
  enough to actually read it. Reduced motion is unchanged.
- R96 — A How to Use search with no matches says so in the
  pane ("Nothing matches '<query>'. Try fewer words.") instead
  of leaving the old body up.
- R97 — A dataset file can be dropped onto the "Pick dataset
  file" button and the project window's Dataset field. A bad
  drop (not .jsonl, missing, unreadable) is refused in plain
  words.
- R98 — All shortcuts live in one registry (stella/shortcuts.py)
  and the How to Use Shortcuts topic is generated from it, so
  the list can never drift from the keys that work. 8 shortcuts
  including the new Ctrl+Q.
- R99 — A reply that hits the 12 tool-call cap, or is
  cancelled, is recorded in the chat history instead of
  vanishing.
- R100 — "just do it" matches anywhere in a message, not only
  at the start. A refusal still wins when a plan is pending.
- R101 — A custom provider base URL ending in
  /chat/completions has it stripped before Stella appends it,
  so the URL is never doubled.
- R102 — The chat window offers cloud models as buttons
  (Groq, Gemini, custom — with saved keys only), labelled with
  their provider, even when Ollama is down.

## v0.27.0 — 2026-11-17

The second P2 batch of the 2026-11-15 full-product review (R52–R75),
plus R92 (How to Use opens on Getting started, decided by Joshua
2026-11-17): the CLI's --json flag is now honoured or plainly
refused on every command, keys are saved without ever showing them,
the installer fetches training wheels with resume, the uninstaller
only touches its own launchers, the refusal probe judges replies
right, sleep cycles can be deleted and pruned, the guide names the
right governing seats, and the desktop training icon actually works.
Full record: docs/stella-review-task-list-2026-11-15.md.

- R52 — Every CLI command either honours --json or refuses it in
  plain words (exit 1): 29 honour, 9 refuse, and the gate is
  closed by default, so a future command cannot silently ignore
  the flag. A sweep test covers all 38 commands.
- R53 — The four export commands check the profile and project
  exist before printing the size estimate, instead of printing a
  number for a project that is not there.
- R54 — Chat pre-flight failures go to stderr, and keys are now
  managed from the CLI: `save-key` reads the key without showing
  it (typed or piped, never echoed), plus `list-keys` and
  `remove-key`. There is no --key flag anywhere.
- R55 — `clone-profile` and `clone-project` on the CLI, wrapping
  the same store calls the window uses.
- R56 — The nameless-profile warning only fires when a profile
  has neither a name nor a display name.
- R57 — `doctor explain <file>` names the exact apt package a
  missing Qt library needs, and install.sh prints that line when
  the GUI cannot start.
- R58 — When the training venv is broken, doctor's later steps
  skip their repairs and say the venv is broken, instead of
  reporting fixes that never happened.
- R59 — uninstall.sh only removes a launcher or desktop file when
  it names this install's own run.sh path (a symlink only when it
  resolves to this install's stella-cli). A newer install's
  launchers are left alone.
- R60 — install.sh echoes a waiting line before every pip step
  and checks the connection first (10 s HEAD to pypi.org), so an
  offline install fails in seconds instead of hanging silently.
- R61 — The training preflight asks for 5 GB free (was 3 GB) and
  pip runs with --no-cache-dir. The peak is still unmeasured; R23
  measures it on the real PC.
- R62 — Training wheels are fetched outside pip, with resume:
  pip resolves the list, then a small fetcher downloads each
  wheel with HTTP Range, streaming hash, and 3 attempts. A
  killed download resumes where it stopped. A fetch that stops
  partway never falls back to a direct pip install.
- R63 — Uninstall is click-only now: `Uninstall Stella.desktop`
  in the Stella folder runs the uninstaller through a small
  launcher, the same shape as the install icons.
- R64 — The refusal probe judge reads the first two sentences,
  strips idioms, and only counts a bare "No." or a strong marker
  in the second sentence. The 11-case battery now passes 11/11.
- R65 — The probe gate recomputes the change from the measured
  rates instead of trusting the caller's number, fails any run
  where the model refuses everything after training, and fails
  when the empty-prompt rate is missing.
- R66 — Sleep cycles show their size, and can be deleted or
  pruned (keep the newest N) from the window and the CLI
  (`sleep-delete`, `sleep-prune`). Deleting keeps the slept-row
  hashes, so old rows are never re-slept.
- R67 — The governing-seat warning fires for a governing-seat
  marker or a governing role, and is still suppressed when the
  base model is already abliterated.
- R68 — `stella probe` auto-detects like the window: a governing
  seat gets the gate, anything else is informational.
  --informational forces informational, --gate forces the gate.
- R69 — The README names the right probe counts (18 plainly
  benign prompts by default, 24 for a governing seat), the right
  seats, the exit-3 failed gate, and the new commands.
- R70 — How to Use names the right governing seats and counts,
  covers the bridge, checkpoints, recipe and adapter packages,
  and governing seats, and the GGUF topic names the quant picker.
  The v0.16.0 T90 bullet below carries a correction note (the
  bullet named the wrong seats; the code always gated the right
  ones).
- R71 — The v0.24 test fixture uses a seeded store and temp
  settings, so no test touches the real ~/.stella store.
- R72 — The HF size resolvers have real-execution tests: HEAD
  against a fake huggingface_hub, ranged GET against a local
  HTTP server.
- R73 — Every entry in the plain-words error map is covered by
  a test.
- R74 — The GUI test fixture waits for all background workers
  before closing a window, so a stray worker cannot outlive its
  test.
- R75 — Resume is only offered when there is a session, no run
  in progress, and at least one checkpoint; the pause message
  ends "Press Resume when you are ready."
- R92 — How to Use opens on Getting started instead of an empty
  pane (Joshua's decision, 2026-11-17).
- R13 fix — The desktop copy of the training installer icon was
  broken since v0.25.0: its Exec used the %k pattern, which
  resolves to the Desktop folder, so double-clicking it failed.
  install.sh now rewrites the Desktop copy's Exec to the absolute
  launcher path, and uninstall.sh removes the Desktop training
  icon when it names this install. The tree copy keeps the
  portable %k form.

## v0.26.0 — 2026-11-17

The first P2 batch of the 2026-11-15 full-product review (R24–R51):
training honesty (the dry-run fit counts dataset RAM, resume refuses
a changed dataset, a crashed run is reconciled on startup instead of
showing "training" forever), disk guards on export and requant,
cleanup that runs on interrupts too, a distill run that survives a
bad prompt, the end of `method: full` on the CLI, a status bar that
stays true, a fit verdict that no longer calls the recommended
starter too big, chat history that stops growing without bound, and
dated cloud model lists with a staleness warning. Full record:
docs/stella-review-task-list-2026-11-15.md.

- R24 — The dry-run fit answer counts dataset RAM as well as
  training RAM (`total_bytes` added), and the format names the
  dataset's share.
- R25 — Offline, a single-file model link is no longer refused when
  the weights are already cached: the remote metadata path reads
  config + weight sizes from the HF cache first (no network, no
  huggingface_hub). A genuine refusal names the next step.
- R26 — Checkpoints carry a dataset fingerprint (SHA-256 + row
  count); resuming after editing the dataset is refused before the
  lock is taken, instead of silently training the wrong rows. Old
  fingerprint-less checkpoints warn and continue.
- R27 — A hard crash no longer leaves a run showing "training"
  forever: `reconcile_stale_training` marks crashed runs `paused`
  (checkpoints exist) or `failed` (none), logs `run_crashed`, and
  no-ops while the job lock is held. It runs at CLI startup and in
  the main window, which also shows a crash notice + resume offer
  in the status bar.
- R28 — `method: full` can no longer be set from the command line:
  create/update-project refuse it in plain words, and show-project
  and train warn on a stored `full`. The `--method` flag stays, so
  `full` gets a plain-words refusal instead of argparse's error.
- R29 — The GGUF parser picks the quant by bytes (elements x
  bits-per-weight), not by tensor count, so a near-tie can no
  longer pick the wrong one.
- R30 — A distill timeout or failure no longer aborts the whole
  run: each prompt retries once, then is skipped, recorded, and
  warned about, and the run continues. The timeout message says
  the teacher is slow, not down. The report gains `failed` /
  `failed_prompts`; the CLI prints warnings even under `--quiet`;
  the GUI logs them.
- R31 — Export has a disk guard: `estimate_export` returns
  `f16_bytes` and a peak `disk_bytes` (2x merged + output), the
  format names the F16 file, and `export_gguf` refuses up front
  on a short disk.
- R32 — The requant disk estimate counts Ollama's blob copy
  (2x estimate + slack, named in the message).
- R33 — Cleanup runs on interrupts too: the cleanup handlers in
  requant, `convert_to_gguf`, and `export_gguf` catch
  `BaseException` and re-raise interrupts bare. `convert_to_gguf`
  also removes a partial GGUF output once quantize has started
  (never a pre-existing file).
- R34 — The requant subprocess has a 30-minute timeout; a hung
  quantizer is killed with a plain-words error. `ollama create`
  keeps no timeout (a model load is not a hung process).
- R35 — Teacher answers are no longer silently cut off at 1024
  tokens: `ollama.generate_full` returns the done reason, and
  distill skips length-truncated answers (counted, never saved).
- R36 — Importing a recipe from a finished project keeps the
  project's status with a truthful "carries no trained weights by
  design" warning — no demotion, no "Train it first".
- R37 — The model layer type-checks what it is given
  (`_require_text` / `_require_config` / `_require_dependencies`
  in create/update profile and project); a bare-string
  dependencies value is refused, never shredded into characters.
- R38 — Export checks what it writes: `_validate_export_manifest`
  runs in all four exporters before anything is written, so Stella
  no longer exports packages its own verify refuses.
- R39 — Import has size and disk guards: a 10 GB package cap
  enforced from the zip headers before extraction, plus a
  free-space check on folder imports.
- R40 — Cloning a profile names its dropped projects:
  `clone_profile` returns `skipped_damaged_projects` (name +
  error), and the GUI clone handler warns naming them, instead of
  reporting success over a silent drop.
- R41 — The status bar no longer says "Pick a profile to begin."
  while a session is live: refresh replaces the stale line with
  "Ready.", but only when the current message IS that stale line,
  so a fresher action message is never clobbered.
- R42 — The Settings Ollama status text no longer overlaps the
  Refresh button when the window opens: the relayout is forced the
  moment the status text lands. Word wrap was already set and was
  not re-added.
- R43 — The fit verdict is reconciled, not just reworded: the
  picker formula is now 1.0 GB/param-B + 2.7 GB fixed (resident
  weights + activations/headroom/LoRA state from the training
  estimator), so LFM3 1.7B reads 4.4 GB against the recalibrated
  4.34 GB (was 6.4 GB). The verdict is judged against total RAM
  (stable) instead of free RAM (transient); the too-big line says
  Stella checks free RAM again at train time. A test pins the
  picker and the training estimator together so they cannot drift
  again.
- R44 — The run-button row moved above the progress bar in the
  glanceable card, so it is no longer clipped at 1366x768
  (measured offscreen: row bottom 605 px vs 664 px viewport).
- R45 — A typed cloud-model pick is kept when Ollama is down: the
  no-models branch sets `_awaiting_model`, and a refresh landing
  on the no-models state no longer repeats its message.
- R46 — Chat history is bounded: at most the last 20 messages are
  sent per turn, cut on a user-message boundary so a tool result
  is never orphaned from its call. The full history stays in the
  window.
- R47 — Every tool block in a reply runs (each counts against the
  12-call cap), and the plain text has every block stripped, so a
  second tool block's raw JSON no longer leaks into the chat. A
  malformed second block gets the same garbled-call recovery as
  the first.
- R48 — Tool JSON in a ```json fence, or in an unclosed fence with
  complete JSON, is parsed and run instead of being shown as raw
  text. A ```json block with no `"tool"` key stays text.
- R49 — The template walk is tracked, not just prompted:
  `template_step_for` derives the step from real store state
  (profile, project, dataset, status, passed probe, export), the
  system prompt carries the current step, step changes are
  narrated, and the Chat window shows a step label.
- R50 — The agent loop fetches the Ollama model list once per turn
  (`_turn_models`, cleared in a `finally`), instead of up to 12
  tag fetches per loop.
- R51 — The curated Groq/Gemini lists carry a `checked` date
  (2026-11-17), with a 90-day staleness threshold; Settings shows
  a plain-words freshness label in the AI providers section,
  hidden while fresh. No online check was added (that needs
  Joshua's say-so first); each release re-checks the lists and
  moves the dates.

## v0.25.0 — 2026-11-17

The P1 batch of the 2026-11-15 full-product review (R1–R18): the
New Profile dialog no longer picks a model by itself, the trash has
a Restore button, sleep adapters can be exported to GGUF, the
refusal-probe gate is enforced at export for governing seats, vision
models can no longer be silently exported or requanted as text-only,
the doctor's two live bugs are fixed, the Groq and Gemini model
lists are current (re-checked against the providers' own pages on
build day), and training installs with one click — no terminal.
R19–R23 stay hard-gated on Joshua's PC. Full record:
docs/stella-review-task-list-2026-11-15.md.

- R1 — New Profile dialog: no row is selected when the dialog opens
  (a deferred clear in showEvent), and only a real user pick (mouse,
  arrow keys, Space) counts — a background refresh can no longer
  re-select row 0. Enter with no pick does nothing.
- R2 — Trash window gains a Restore button (disabled until a row is
  picked). Restore moves the dated trash folder back under its
  manifest name; a name clash or a project whose profile is gone is
  refused in plain words, never renamed or overwritten silently.
  The help text now says "pick it and press Restore".
- R3 — Sleep adapters have a GGUF export path: `export_gguf(...,
  from_sleep=N)`, CLI `--from-sleep N`, and a "From" picker beside
  the Export button listing sleep cycles (via
  `sleep.list_sleep_adapters()`). Two adapter sources at once is a
  plain refusal, not a silent pick.
- R4 — The refusal-probe gate is enforced: `require_passed_probe`
  runs in `export_gguf` (engine level, before any folder is made)
  and in the GUI export (before the folder pick), so the GUI, CLI,
  and chat paths are all gated. Hard block, no bypass flag; a
  governing profile with no passed probe cannot export. An
  old-version probe result with no before/after rates fails the
  gate rather than passing vacuously. Non-governing profiles are
  untouched.
- R5 — Vision models refuse, in plain words, in both export and
  requant: `gguf_has_vision()` scans the GGUF header for a vision
  tower, and `is_vision_architecture()` refuses vision config
  architectures at export. Text-only Gemma 3 1B shares the Gemma 3
  arch, so it is deliberately excluded from the GGUF arch list.
- R6 — Reading a model's type reads only the first 4 bytes
  (`resolve_model_blob`), never the whole file into RAM.
- R7 — Bad UTF-8 in a profile or project manifest is one damaged
  row, not a crash: `UnicodeDecodeError` is caught in `_read_json`
  (wrapped as StellaError), in notes reads, in history read/trim,
  and in export manifest loading.
- R8 — Sleep heal rebuilds hashes from the orphan cycle's own
  `cycle_input.json` + `val_rows.jsonl`; orphans with no input file
  are refused and recorded in `unhealed_cycles` (recomputed from
  disk on every manifest read).
- R9 — The doctor's launcher fix writes the real icon path, and a
  new `_launcher_is_current()` checks Exec AND Icon, so a fixed
  launcher stays fixed.
- R10 — The doctor's libxcb map grows from 14 to 20 entries, and
  the generic fallback is narrowed from `libxcb` to `libxcb.so`,
  so the libxcb misdiagnosis is gone.
- R11 — Groq model list refreshed (openai/gpt-oss-120b,
  openai/gpt-oss-20b), re-checked live on build day. qwen/qwen3.8-27b
  is preview and is not added.
- R12 — Gemini model list refreshed (gemini-3.8-flash,
  gemini-3.5-flash-lite), re-checked live on build day.
  gemini-3.1-pro-preview has zero free-tier quota and is not added.
- R13 — Training installs with one click: an "Install training"
  button in the Train panel (live whenever no job runs, streaming
  output to the Train log), plus a double-clickable `Install
  Training Stella.desktop` on the desktop (same script, result
  stays visible until Enter). install.sh copies the icon and makes
  it trusted. Every GUI and How to Use surface names the click
  path first.
- R14 — CLI chat shows narration and progress lines ahead of the
  final `Stella:` reply.
- R15 — The sleep command's no-dataset error now names the full
  command (`stella sleep <profile> <project> --rows my-data.jsonl`)
  instead of pointing at a "Train panel".
- R16 — Tests that need huggingface_hub are gated with
  `pytest.importorskip("huggingface_hub")`, so the 4 tests that
  failed on a base-only install now skip cleanly. The hub is
  deliberately NOT added to the base requirements.
- R17 — The Ollama-down settings test seeds its own models via the
  `seed_models` fixture, so a live Ollama on the machine can no
  longer flip it mid-run.
- R18 — The press-dip test asserts on the animation's key values
  (start, 118 px at halfway, restored at the end) instead of
  sampling geometry, so load can no longer miss the dip.

## v0.24.0 — 2026-11-15

The Stella half of the Stella + OST improvement list (from hands-on
use of v0.23.0 against a live Ollama server): the requant fix, the
single-file Hugging Face defect, the RAM recalibration, the Ollama
bridge, the distill timeout and keep-alive, live progress, tool
errors in plain words, and a doctor that names the real fix. The
OST items from that list belong to the OST thread and are not built
here. Full record: docs/stella-ost-improvement-list-2026-11-15.md.

- S1 — Ship the requant fix: llama-quantize is called with
  --allow-requantize, so re-quantizing an already-quantized model
  works instead of failing in ~14 seconds. Every Ollama model is
  already quantized, so as released requant failed on all of them.
  Proven live: 1.04 GB -> 718 MB, loads and answers, original
  untouched.
- S24 — Fix the single-file Hugging Face defect (the highest-priority
  unfixed item): the Hub API returns size: None for every sibling of
  a single-file model, so training by repo id refused with "the size
  of its weights could not be read" — including LFM3-1.7B, Stella's
  own first target. The remote metadata path now resolves each weight
  file's size with a HEAD request (ranged-GET fallback) instead of
  trusting the siblings' size field. Verified live against
  Qwen/Qwen2.5-Coder-1.5B (3,087,467,144 bytes, exact match).
- S6 — Check RAM before training, recalibrated: the estimate counted
  base weights in full, but safetensors weights stream from disk —
  a real 0.5B run peaked at 0.85 GB against a 2.30 GB estimate. The
  weights term now counts the probe-grounded resident fraction
  (0.5x, against a measured ~0.36x), and the limit is the RAM
  actually free, not just the 8 GB ceiling — so a run no longer
  starts when Ollama is holding half the machine. A 3B model at
  seq 512, refused before at 8.06 GB, now fits at 5.57 GB. The
  guard still overstates every measured peak.
- S23 — Bridge from Ollama to training: an Ollama tag or GGUF file
  as base_ref used to fail with a misleading "config could not be
  read (no network...)" error. It now says plainly that training
  needs Hugging Face weights, never a GGUF file, and `stella bridge
  <tag>` suggests the HF repo for known models (curated, each repo
  verified on the Hub; the user confirms — Stella never guesses a
  repo silently). Models with no verifiable repo stay unknown rather
  than guessed.
- S3 — Distill timeout knob: `stella-cli distill --timeout <seconds>`
  (default 300), plus the Distill dialog's "How long to wait for
  each answer (seconds)" and an optional timeout on the chat
  distill tool. A slow CPU that answers one token in 115 seconds
  no longer times out through no fault of the model.
- S4 — Keep the teacher warm: distill sets keep_alive ("30m") on
  every teacher call, so the model stays loaded across prompts
  instead of reloading (30-60 seconds each) between them. It
  unloads on its own after the run; never kept forever.
- S15 — Fix the "unknown" quant reading: the GGUF parser read only
  the first 1 MB of the file, but a real Ollama blob's metadata is
  7.85 MB (tokenizer vocab), so every real model read as "unknown"
  and size estimates were guesses. The header is now streamed, and
  the parser reads the real quant (verified live: Q5_K, 5.5 bits
  per weight). Note: the file's manifest name said Q4_K_M, but its
  tensors say Q5_K — the parser reports what the file is.
- S21 — Live progress on long jobs: the requant run streams the
  quantizer's own per-tensor progress ("shrinking... tensor N of
  M", plus a "still working" line when no count is parsed), and the
  train and distill terminal lines carry an ETA ("about 25 minutes
  left") once enough units have finished to measure a rate. The
  GUI distill job card already showed prompt N of M (verified).
- S22 — Tool errors in plain words: the requant and GGUF-export
  runners translated raw tool output verbatim ("requantizing from
  type q4_K is disabled"). Known errors now lead with a plain-words
  explanation and what to do; the raw lines stay as detail, never
  hidden.
- S19 — Doctor names the fix: a missing system library (libEGL,
  libxcb, libGL, ...) used to report the raw error plus "run
  install.sh again", which never fixes a library problem. The
  doctor now names the system package and the exact install
  command (sudo apt install libegl1). Unmapped errors keep the
  old wording.
- S14 — Warn before double-quantizing: shrinking an already-quantized
  model rounds the weights a second time and can lose
  noticeably more quality. The warning now says so in plain words
  before the run.
- S17 — Clean up partial files on failure: a failed requant left a
  197 MB partial file behind. Partials are removed on failure now,
  and empty output is cleared before complaining.
- S16 — Checkpoint and resume for training: already done (engine
  resume with RNG restore, CLI --resume/--from-checkpoint, GUI
  Resume button and checkpoint picker, 16 tests). Verified, no
  build needed.
- S20 — Make the install survive restarts: no product defect. The
  restart problem (Qt libraries wiped) exists only on the dev VM;
  on a real Mint PC the system libraries persist across restarts,
  and install.sh already checks the window starts. Recorded, not
  built.

## v0.23.0 — 2026-11-14

The final UI polish slice (audit #9 R21–R26, tasks T189–T194):
one tagline everywhere, the status bar stops repeating the
session, tooltips where they earn their place, a searchable
How to Use with a link from the empty state, and breathing room
for the Chat window's help line. T189 is mooted by T16 — the
settings form (Method combo with it) was deleted in v0.11.0, so
there is no "full" left to remove from the UI; the model enum
still accepts it, so old projects still load.

- T189 — Remove the dead "full" method: MOOTED by T16. No Method
  combo exists anywhere in the GUI anymore (grep of gui.py finds
  no "method" control at all), so there is nothing to remove;
  pinned by a test asserting no combo offers "full" and no label
  is "full", and by a test opening a project whose stored method
  is "full" (it opens clean — the model enum keeps accepting it,
  so old manifests still load).
- T190 — One tagline everywhere: the header now carries the same
  line as the window title, "fine-tune models on your PC". The
  window title keeps the version number.
- T191 — Status bar shows the session once, in display names:
  refresh_session no longer writes "Profile: <slug>, project:
  <slug>." (or the profile-only variant) into the status bar —
  the session title carries the session, in display names. The
  status bar keeps whatever the last action said.
- T192 — Tooltips where they earn their place: tree rows already
  carried their full text as tooltips (T78), so this slice adds
  the button half — Go, Proof run, Estimate, Prune, the chat
  plan Run, dependency Add/Remove, Mark ready, and the distill
  Start each explain themselves on hover, in plain words.
- T193 — How to Use gets search and a link from the empty state:
  a search box over the topics narrows the list by title or
  body (case-insensitive, never picks a topic for the user), and
  the empty-list hint ("No profiles yet", "No projects yet")
  links to Getting started, which opens the guide on that topic.
- T194 — Chat window breathing room: the default size is 700x560
  (was 700x520, where the help line rendered 30px against a 45px
  need) and the help line is shortened to two sentences — the
  greeting already says the chat sets up and runs training. The
  test measures the rendered label height against its
  heightForWidth, not by eye.

## v0.22.0 — 2026-11-14

The packages/CLI/tree slice (audit tasks T170, T171, T172, T173,
T174, T180, T181, T184, T185, T186, T187; T175/T176 stay
overtaken by the v0.8 metamorph UI removal, T182/T183 stay
hard-gated on Joshua's decisions): recipes and adapters are
packages now, every package kind travels as one `.stella` file,
the command line is scriptable and quietable, the probe runs a
per-role prompt set, and the profile list has a filter, a role
filter, sort, and multi-select bulk actions.

- T170 — Settings-only export / share a recipe: `export_recipe`
  writes a `stella-recipe-export` package — profile block,
  project block (dataset reference, settings, metamorph mode +
  notes), README, notes — no weights, no checkpoints, no probe
  results, no sleep cycles. Importing a recipe creates a new
  project with those values, through the same profile merge and
  collision choices as a project import; a dataset that is not
  on the importing PC warns at import and never blocks it.
  CLI: `stella export-recipe`, `stella import` reads recipes.
  GUI: File menu "Export recipe...".
- T171 — Single-file package option: every package kind exports
  as a `.stella` zip holding exactly the folder package (same
  manifest, same members, at the zip root). `stella export`,
  `export-profile`, `export-recipe`, and `export-adapter` take
  `--zip`; the GUI's File menu has "as single file" entries for
  project and profile; import, verify, check, and preview read
  a `.stella` file exactly like a folder, and a zip whose
  members escape the folder is refused whole.
- T172 — Machine-readable and quiet output: `--json` on
  `profiles`, `projects`, `show-profile`, `show-project`,
  `probe`, `verify`, and `sleep-status` prints valid JSON
  (parseable, with the damaged rows included); `--quiet` silences
  the per-step lines on `train`, `sleep`, and `distill` and the
  progress lines on `pull-weights`; `--verbose` prints the full
  traceback behind the catch-all error. The flags are global:
  they work before or after the subcommand.
- T173 — Adapter library: `export_adapter` writes a
  `stella-adapter-export` package — the trained adapter weights
  under `weights/` plus a manifest adapter block (name, base,
  rank, dataset, status, steps, final loss). Import lands it in
  any project with the same base (into an existing project from
  the import preview, or a new project built around the weights
  with the adapter's rank and dataset reference); the base must
  match, a target that already has an adapter refuses, and a
  new-project import whose name is taken lands under a copy
  name. CLI: `stella export-adapter`, `stella import-adapter`.
  GUI: File menu "Export adapter...", import preview checkbox.
- T174 — Per-role probe sets: `stella/probe_sets/<role>.json`,
  one file per canonical role, editable. Governing seats
  (driver, reviewer, tester, fast) get the full 18-prompt
  refusal battery plus 6 role-specific prompts; vision,
  all-rounder, and utility get 12 role-specific prompts each.
  The probe picks the set for the profile's role, falls back to
  the default set (with a note when a set file is unreadable),
  and records the set name in `probe_results.json`; the results
  dialog shows it, and `stella probe` prints it.
- T180 — Search, filter, and sort for the profile list: a
  filter box above the tree (matches display name, slug, role,
  and tag), a role filter, and sort by name (the default —
  the old filesystem order is gone), role, recently used
  (the T165 `last_used` stamp), and project count. Filtering
  keeps the current selection when the selected profile still
  matches, and a filter that matches nothing says so.
- T181 — Bulk operations / multi-select: Ctrl/Shift-click
  selects several profiles; the right-click menu offers delete
  (one confirm naming them all, each to the trash), export (one
  package per profile, one include-projects question, one
  overwrite question), and role change (one picker for the
  whole selection). Single-click selection and every
  single-profile action work exactly as before.
- T184 — Replace the pull-weights one-liner: `stella
  pull-weights <repo>` downloads a Hugging Face repo's weights
  with plain progress lines (no nested quotes anywhere), and
  install-training.sh ends with the short command.
- T185 — Desktop-file polish: the generated launcher
  (`stella/install.py`) carries `StartupNotify=true`, a
  `Keywords` line, and `Version=1.0`; the checked-in "Install
  Stella.desktop" gained StartupNotify and Keywords too.
  (No `desktop-file-validate` in the sandbox; the fields are
  verified by parsing.)
- T186 — --help for the scripts: install.sh,
  install-training.sh, and run.sh each answer `--help` with
  usage and exit 0, checked before anything else runs, so no
  install or launch happens.
- T187 — Small CLI polish: every create/rename path that
  normalizes a name says so ("Created profile 'upper-case'
  (from 'UPPER-Case')"), and bare `stella` with no subcommand
  prints the command list instead of argparse's "arguments are
  required" error.

## v0.21.0 — 2026-11-14

The profiles/rows/provenance slice (audit tasks T160, T161, T163,
T164, T165, T166, T167, T168, T177, T178, T179; T162 stays done in
v0.9.0, T169 stays superseded by T19): the Train panel has the
CLI-only options in the window (a step cap, per-run dataset and
base overrides, a quant choice and a checkpoint picker on Export
GGUF); rows carry more of the truth (a tag-health marker and the
project count on profiles, the dataset and a slug disambiguator
on projects); the Profile window shows what the profile points
at (size, quant, context, capabilities from Ollama) plus the
dates and a last-used stamp; profiles have notes of their own;
exports report their size and refuse when the disk will not fit;
and packages carry provenance, with an import/export history in
the home.

- T160 — Notes placement: the Project window's Notes section
  moved above Details, so the running log is visible without
  scrolling in the default window (probed: the editor was at
  y=596 against a 425 px viewport, 0 px visible; now it spans
  y=49-241, fully visible). The settings-tooltips half is MOOT:
  T16 removed the settings form entirely, so there are no
  settings fields left to tooltip — no tooltips were added, and
  no settings UI was resurrected. The inline help labels already
  explain every field that remains.
- T161 — GUI parity for the CLI-only options: the Train panel has
  a step cap (0 means the full run; a cap makes Go a short run,
  Resume still runs to the run's own total), per-run dataset and
  base overrides (this run only, never written back, cleared on
  a project switch; the pre-train check runs against the override
  dataset, and a base override skips the weights offer), and
  Export GGUF has a quant picker (every known quant, Q4_K_M by
  default) plus a checkpoint picker riding the T150 list
  (trained adapter, or one entry per checkpoint). The engine
  already took all four options; this is the window wiring.
  Rank/lr/epochs/batch/seq stay under the hood (T16).
- T163 — health badge per profile row: T78's weights dot stays
  exactly as it was (green ready, amber not ready, grey Ollama
  down); the remainder was the TAG side, which now shows as a
  marker on the row from the cached model list (T43): installed
  tick, missing cross, Ollama down question mark, and a distinct
  "no tag" state for a profile that names no tag. The markers
  relabel when the model-list refresh lands, so Refresh updates
  them. The two signals answer different questions (weights ready
  vs tag installed) and both stay.
- T164 — richer project rows, RECONCILED: method and rank are
  NOT shown — they are settings, and T16 forbids settings on any
  screen, so the task's Fix (written before T16) is overruled on
  that half. Status was already in rows (T53). What was built:
  the dataset file in each row, and the slug as a disambiguator
  when two projects in one profile share a display name
  (collision only). Tests pin dataset + slug + status, not
  method/rank.
- T165 — show what the profile points at: model metadata from a
  cached /api/show (same discipline as T43 — a background fetch
  per tag, never on the UI thread, never per click) shows size,
  quant, context length, capabilities, and parameter count in
  the Profile window; with Ollama down it says unavailable, and
  a tag Ollama does not have says so outright. The list row and
  the panel both show the project count; the panel shows the
  created/updated dates and a last-used date. The last-used
  trigger is defined here: a real training run starting on a
  project under the profile stamps it (sleep consolidation does
  not); a run that never starts stamps nothing. Last-used travels
  in exports and is restored on import.
- T166 — profile-level notes: notes.md per profile (same pattern
  as project notes: read_profile_notes/write_profile_notes on
  the Store), edited in the Profile window and saved through the
  existing Save profile flow, with the same rotating .1 backup
  as project notes (T119). Profile export carries them as
  profile-notes.md at the package root; import restores them
  only for a newly created profile — an existing profile keeps
  its own notes. Notes survive rename (the file lives in the
  profile folder).
- T167 — README wording + export/import UI polish: the README
  claim was already true — weights DO ship in packages (T41,
  v0.13.0), so no wording change was needed there (one adjacent
  fix: the package list no longer names "config", which stopped
  shipping in v0.13.0/T60 — the settings live in the manifest).
  Export was already disabled until a project is selected (menu
  action, via _refresh_menu_state, pinned by existing tests).
  What was built: the export dialogs name the package
  (<project>-stella-export / <profile>-stella-profile-export) in
  the folder-picker title, before the folder is picked.
- T168 — double-click does the obvious thing, RULING: double-click
  on a profile/project row KEEPS opening the detail window — it
  is the established multi-window pattern, and swapping it for
  rename would have replaced live behavior. Rename becomes F2
  (Chat moved to F3) plus a right-click context-menu Rename
  action on rows. Checkpoint double-click shows its detail (the
  same detail a single click shows).
- T177 — notes type validated at both write points: create_project
  and update_project reject non-string notes with a StellaError
  (None counts as absent, the import validator's convention).
  Only notes being written are checked — an unrelated update on
  a project with old bad stored notes normalizes them instead of
  failing the update.
- T178 — size/disk awareness on export: the CLI prints the
  estimated size before copying and the real package size after;
  the window's export log line carries the estimate and the
  success message the real size. The engine checks free disk
  space against the estimate before copying and refuses (naming
  both sizes) when the package will not fit.
- T179 — provenance: every package manifest names its source
  machine (hostname) next to T118's exported_at stamp, and the
  home keeps an import/export history log (history.jsonl: what
  was exported where, what was imported from where, when —
  trimmed to the newest 200 entries past 500). The import
  preview shows the provenance line when the package carries it.

## v0.20.0 — 2026-11-14

The training-engine + checkpoints slice (audit tasks T150, T151,
T152, T153, T155, T156, T157, T158, T159; T154 stays superseded
by T16 — settings stay under the hood): checkpoints are managed
(resume from a picked one, delete, prune, disk usage), past runs
have a history with their loss curves, the window says which
model it is loading, the export button shows what the export
will cost, the val split is stable under dataset growth,
multi-turn rows train every assistant turn, tool results fit
the dataset format, big datasets are streamed and sized before
they tokenize, and the final checkpoint is saved once.

- T150 — checkpoint management: the list shows step, loss, size,
  and date per row, with total disk usage underneath; clicking
  one fills a detail view (step, loss, size, date). Resume from
  selected continues from that checkpoint (`train_project`
  takes `from_checkpoint`; the CLI's `train --from-checkpoint`
  matches the GGUF flag). Delete and prune are permanent — the
  point is freeing disk, and the trash does not free disk — and
  both confirm first with the size shown, defaulting to No.
  Prune keeps the newest N (spinbox, default 3) and reports
  the size before and after plus the space freed.
- T151 — run history: the log now opens each run with a
  run_started record (settings snapshot stored, never
  displayed — T16) and closes it with run_finished, so
  `list_runs` rebuilds past runs (date, steps, final loss)
  from the log; older logs split on a step that goes down, as
  before. The Train panel's Past runs list shows one row per
  run, and picking one draws that run's loss curve in the
  chart. The log view renders the run records as friendly
  lines, never raw JSON.
- T152 — loading feedback: the training loading event names
  the model ("Loading <base>..."), and the same shape covers
  the probe's two loads (before, then after with the adapter)
  and the export merge — the window and the terminal both say
  which model is loading, from Start until the first step.
- T153 — the export estimate: `estimate_export` (metadata
  only, no model load) names the merged size, the GGUF output
  size for the quant, and a rough time band. It shows beside
  the Export GGUF button once a project has an adapter, in the
  export preview dialog at the commit point, and in the log
  line that starts the job.
- T155 — stable val sets: `split_dataset` assigns val
  membership by hashing each row's content (SHA-256, seed
  salted, namespaced), so adding rows never moves an old row
  between train and val. The at-least-one-val / at-least-one-
  train guards stay (the one exception to stability: a dataset
  with no row under the threshold validates on its lowest-hash
  row, and a new lower-hash row can take that slot).
- T156 — every assistant turn trains: `tokenize_example`
  segments a multi-turn row per turn (through the chat template
  when it segments cleanly, through the plain renderer
  otherwise) and unmasks each assistant turn, each user /
  system / tool turn masked. Single-turn rows take the original
  path, unchanged. Truncation cuts from the left, keeping the
  most recent turns and the final turn's end tokens.
- T157 — the "tool" role validates in messages rows and renders
  as masked prompt content: the model learns from the assistant
  turns around the tool results, not from the results.
- T158 — dataset-size awareness: validation streams line by
  line (`iter_dataset_rows`, `stream_dataset_info`), so the
  health check never holds the file; a dataset over 10 MB or
  5,000 rows warns before tokenization with its size; and a
  dataset that would not fit alongside the model is refused
  with both numbers named (`check_dataset_fit`, reusing the
  RAM estimator).
- T159 — the final checkpoint is saved once: when the last step
  is a checkpoint step, the in-loop save already wrote it, so
  the final save (and its event) is skipped — 3 steps with
  checkpoint_steps=1 emits exactly 3 checkpoint events.

## v0.19.0 — 2026-11-14

The profiles/roles/chrome slice (audit tasks T114, T115, T116,
T120, T121, T122, T124, T126, T127): profiles clone, roles come
from one canonical list with a governing-seat marker and a
pre-train warning, config and dependencies are editable in the
window and from the terminal, the project window carries the
"Why this mode" notes, delete dialogs name what they destroy,
empty lists say what to do next, and the splitter cannot lose a
pane.

- T114 — the three notes are one surface each, in the right
  place: `settings["notes"]` is dropped (it lived in the
  defaults but nothing ever read or wrote it; old manifests
  drop it when they are read, and old packages import with it
  dropped), the Project window shows the stored mode with a
  "Why this mode" notes field under it (the mode picker stays
  gone — it was deliberately removed in v0.8 — and the word
  stays out of visible text), and `notes.md` stays the running
  log, now headed "Project notes". The CLI flags
  (`--metamorph-notes` on create-project and update-project)
  already landed in v0.18; the README now says which notes
  live where.
- T115 — config and dependencies are reachable: the profile
  window has a JSON text area for config and an editable list
  for dependencies, validated on save (bad JSON is refused
  with the parse error and nothing is written), and
  `update-profile` takes `--config` and `--dependencies` too.
  The profile window's form scrolls now (T80's pattern, as in
  the project window): the added section made the window
  taller than a small screen, which squeezed every help label
  to two lines. This is the first step toward the profile's
  own clean environment only — full environment management is
  T182, hard-gated on Joshua's decision.
- T116 — one canonical role list (driver, reviewer, vision,
  fast, tester, all-rounder, utility), offered by the role
  field everywhere it appears; roles outside it are still
  allowed but flagged as custom. The list is UNCONFIRMED with
  Joshua (no approver was awake — it is the roster's seat
  vocabulary). A profile can be marked as bound for a Forge
  governing seat (driver, reviewer, tester, fast — the T90
  set): a bound profile with a stock base warns before any
  training starts, naming the seat and the base (the window
  asks, the CLI warns and proceeds), and its probe runs as a
  gate the same way a governing role does. "Abliterated" has
  no stored flag, so it is detected heuristically from the
  tag/base name markers (heretic, uncensored, abliterat).
- T120 — delete dialogs name the item (display name + slug),
  count what goes with it (projects, checkpoints, notes), and
  state where it goes (the trash) or that it is permanent
  (purge, including the item count on Empty trash).
- T121 — clone profile: the Profile window's Clone button
  (and `Store.clone_profile`) copies tag, base, role,
  processor, config, and dependencies under a new name, with
  zero projects by default and an offer to copy the projects
  too. The processor is copied verbatim (its meaning is
  undecided, T128); the governing-seat marker is not copied —
  a binding is per profile.
- T122 — every profile list row already carried its full text
  as a tooltip (T78: display name, role, tag), pinned by a
  test; the detail panel's role text field is now the same
  editable combo as the canonical list, with custom entry.
- T124 — the button half was already done (the v0.4
  restructure disables the actions with nothing to act on, in
  the refresh pass); the remainder lands here: an empty store
  shows "No profiles yet - New profile to start" under the
  tree, and a profile with no projects shows "No projects
  yet - New project to start".
- T126 — the splitter keeps honest minimums (tree 200px,
  session 480px) and refuses to collapse a pane, so a drag
  cannot lose a list. The non-collapsible flag is re-asserted
  after the saved splitter state is restored, because the
  restore brings back the old collapsible flag too — without
  that, a returning user's pre-v0.19.0 saved state would have
  re-enabled collapsing (found by the coordinator's drive).
- T127 — the window icon, geometry/splitter/session
  persistence, and the shortcuts (Ctrl+N, Ctrl+S, Ctrl+G, F1,
  F2) were already in place from earlier versions; this
  version pins them with an icon test, including the
  missing-file guard.

## v0.18.0 — 2026-11-14

The export/import/clone slice (audit tasks T86, T87, T88, T89,
T104, T105, T106, T107, T108, T112, T117, T118, T119): profiles
export and import whole, export packages carry checksums and
timestamps and are checked before they are imported, export and
import run on the job card with progress and cancel, collisions
are choices, projects clone and start from templates, and the
CLI can rename, delete, update, and show profiles and projects.

- T86 — profile packages: `stella export-profile` (and File >
  Export profile) writes a `<profile>-stella-profile-export`
  package holding the profile, optionally with every project in
  it (weights, checkpoints, notes); `stella import` brings a
  profile package back whole. Datasets are referenced, never
  bundled; a profile import refuses while any of its projects
  already exist here, naming them.
- T87 — CLI parity: rename, delete (to the trash, `--purge` for
  forever), update, and show for profiles and projects
  (`rename-profile`, `delete-profile`, `update-profile`,
  `show-profile`, `rename-project`, `delete-project`,
  `update-project`, `show-project`). `show-project` lists the
  checkpoints, so the user can see what `train --resume` would
  use; `create-project` and `update-project` take the training
  settings as flags. `--processor` on `update-profile` is NOT
  implemented: the processor field's meaning is undecided
  (T128, gated on Joshua's decision).
- T88 — `stella projects` on a nonexistent profile exits 1
  naming it, instead of printing the empty message for a
  profile that is not there.
- T89 — Create in Ollama: the Train panel's new button runs
  `ollama create` for the last GGUF export (its record lives in
  the project dir), on the job card so a slow create can be
  cancelled; `stella export-gguf --create` does the same from
  the terminal. The manual commands are still printed.
- T104 — checksums: every file in a package (except the
  manifest itself) is listed in the manifest with its size and
  SHA-256, and import refuses a package whose files do not
  match, naming the file. Packages written before this version
  import as before.
- T105 — `stella verify` (and File > Check package) checks a
  package without importing it: manifest present, kind known,
  schema valid, files match their checksums — each check
  reported, the first failure named.
- T106 — export and import run on the job card with a
  determinate progress bar and a Cancel button; a cancel leaves
  no partial package and no partial import, and the lists
  refresh when the job finishes either way.
- T107 — the GGUF job's bar moves per phase (merge 1 of 3,
  convert 2 of 3, quantize 3 of 3); the probe job's bar moves
  per prompt. Both were already cancellable on the job card.
- T108 — a second Ctrl+C during a train or sleep run exits at
  once (130) instead of re-requesting the same graceful stop,
  so a run stuck in a blocking base download can be ended; and
  the base load prints a line first saying the first run
  downloads it and Ctrl+C takes effect when the download
  finishes.
- T112 — clone and templates: the project window's Clone button
  copies the dataset, settings, and metamorph mode under a new
  name (no checkpoints, fresh notes with a "cloned from" line);
  New Project offers a template picker, starting with the LFM3
  tool-format preset (the audit's recommended defaults — no
  approver was awake to confirm the values). The picker shows
  names and plain-words descriptions only, never settings.
- T117 — collisions are choices: a menu export over an existing
  package asks before overwriting (`--force` on the CLI); an
  import whose project already exists offers "import as a copy"
  (new slug) or replace (the old project goes to the trash) —
  `--as-copy` / `--replace` on the CLI.
- T118 — the manifest carries each profile's and project's
  created/updated stamps plus a top-level exported_at, and
  import restores them.
- T119 — project notes keep a rotating single backup: saving
  notes copies the previous notes.md to notes.md.1 first, so a
  mistaken save loses nothing. Restore by moving notes.md.1
  back over notes.md (see the README).

## v0.17.0 — 2026-11-14

The training-engine honesty slice (audit tasks T97, T98, T100, T101,
T103, T109, T110, T111, T141, T143): the engine tells the truth about
what it is doing — resume warns when settings drifted or the
optimizer file is gone, long phases print a line each, a paused run
says Paused, and the mode a run trained with is recorded in its
artifacts.

- T97 — LFM3 to GGUF conversion pre-flight: before the merge, the
  base's architecture (from its config) is checked against the
  installed converter's own supported-arch list, parsed from its
  @Model.register lines. An unsupported arch is refused naming
  the arch and the converter; a converter whose list cannot be
  read is not refused on a guess. Whether the installed llama.cpp
  supports LFM3 still wants a real-PC check.
- T98 — resume contract: every checkpoint state now snapshots the
  run's training settings, and a resume warns (event + log) when
  the project's settings changed since the pause instead of
  silently training on with the checkpoint's adapter. A missing
  optimizer.pt warns the same way instead of silently restarting
  the optimizer. Old checkpoints carry no settings and resume as
  before, unwarned.
- T100 — the completion ends with the template's turn terminator:
  when the tokenizer's chat template defines an assistant-turn end
  token (<|im_end|> for a Qwen-shaped template), it goes on
  instead of EOS, so the tuned model learns to end its turn the
  way the template expects. No template terminator means EOS as
  before. End-to-end confirmation needs a real chat-template
  tokenizer.
- T101 — paths in the Modelfile and the printed command are
  shlex-quoted, so `ollama create` works when pasted with a spaced
  path. Plain paths read exactly as before. Whether Ollama's
  Modelfile parser accepts a quoted FROM still wants a real-Ollama
  check.
- T103 — the converter and quantizer subprocesses time out after
  30 minutes each, failing with a plain error naming the step
  that hung, instead of hanging the export forever.
- T109 — progress for long phases, honest paused/resumed output:
  the probe prints a line per pass ("Probing before tuning...",
  "Probing after tuning..."), the GGUF export prints a line per
  phase, a paused run's closing line says "Paused after N steps"
  instead of reusing the completed-run wording, and a resumed run
  skips the validation line for an epoch it trained no new steps
  in.
- T110 — the library warnings are silenced on stderr: the CLI
  entry point filters the transformers/peft notices
  (torch_dtype deprecation, fan_in_fan_out, the peft notice for
  the metamorph_mode key), sets TRANSFORMERS_NO_ADVISORY_WARNINGS
  and TQDM_DISABLE, and filters library Future/Deprecation
  warnings from the two libraries' modules. The train.py float()
  fix this task also named had already landed (.detach() on both
  loss accumulations), so this task was the filtering only.
- T111 — CLI-appropriate error text: the no-dataset error on the
  CLI names --dataset (and create-project --dataset); the window
  still names the Train panel. The other error strings were
  audited for GUI pointers the same way — the no-dataset error
  was the only one.
- T141 — corrupt-block tests for every reader: null, missing-key,
  and wrong-type metamorph in project.json and in manifests,
  exercised against the CLI list, the GUI list + detail fill +
  save, export, and verify. Pins T37's defensive reader.
- T143 — the mode is recorded in training artifacts: the
  project's stored mode string goes into training_summary.json
  and the adapter config (a post-write edit, since peft writes
  that file) at train time. Recorded as stored — no MetaMorphAi
  reading picked.

## v0.16.0 — 2026-11-14

The pre-train estimates + probe cluster (audit tasks T83, T84, T85,
T90, T91, T92, T93, T94, T95, T96, T148): the window answers "will
this run fit, how long, how much disk" before training starts, and
the refusal probe is a real surface — informational for most
profiles, a gate for governing seats, with its evidence one click
away and a before/after preview before export.

- T83 — pre-train dataset health check: the Train panel shows the
  row count, format, and a rough token count for a healthy dataset
  (and the problem, with line numbers, for a bad one). A failing
  check blocks the run with the errors named; a tiny dataset
  (under 10 examples) asks to proceed in the window and warns on
  the CLI. Builds on T45's validator.
- T84 — RAM/time estimate in the Train panel: fit + time for the
  auto-config recipe, no settings on screen (T16). Updates when
  the model, dataset, or job selection changes. The metadata read
  is gated (local folder or downloaded weights only), so the
  label never hangs the window on a network fetch.
- T85 — dry-run estimate: an Estimate button in the Train panel
  and `stella train --dry-run` on the CLI show RAM fit, step
  count, disk needed, and a rough time — from metadata only, no
  model load. Reuses T84's display math.
- T90 — probe informational mode: `stella probe --informational`
  reports the counts and the change with no verdict and exits 0
  regardless. The window probes informationally for non-governing
  profiles; governing seats (judge, reviewer, merger, grader,
  router) still get the gate.
  Correction (v0.27.0, R70): the governing seats are driver,
  reviewer, tester, and fast, not judge, merger, grader, router.
  The code always gated the right seats; this bullet named the
  wrong ones.
- T91 — a failed probe gate exits 3 (not 1); a crashed probe
  still exits 1. The gate verdict goes to stderr, separate from
  the numbers on stdout.
- T92 — probe provenance in probe_results.json: timestamp,
  base_ref, adapter path, max_new_tokens, and a prompts-version
  marker (PROMPTS_VERSION, now 2).
- T93 — hard-benign prompts in the probe set: 6 legitimate
  near-boundary requests (your own lock, your own network, a
  contentious topic, a household chemical, a phishing check, a
  firm no), additional to the 12 trivial prompts, which stay.
- T94 — the probe results dialog: per-prompt reply + refused
  flag, before and after side by side, with the gate verdict (or
  the informational note). Opens when a probe finishes; re-open
  it any time with View probe results.
- T95 — proof-run button in the Train panel: a short capped run
  (5 steps), passed through as max_steps.
- T96 — the final val loss is returned from run_training_loop,
  written to training_summary.json, and shown in the Train
  panel's summary line and the CLI's closing line.
- T148 — before/after preview before export: Export GGUF shows
  the probe's before/after replies (the T94 dialog) when probe
  results exist; Export goes ahead, Go back cancels.

## v0.15.0 — 2026-11-14

The installer-coherence slice (audit tasks T42, T62, T63, T64, T65,
T66, T67, T68, T69, T130, T132, T133, T134, T135, T136, T137, T138,
T139, T140): the installer tells the truth about failures, installs
are pinned and receipted, the icons live in the hicolor theme, and
there is a double-click installer, an uninstaller, and a doctor.

- T42 — venv failures name the real cause: the python3-venv message
  prints only when the venv module is actually missing; any other
  failure prints the real venv error. Cleanup touches only a .venv
  this run created — a stray file already at .venv is never deleted.
- T62 — run.sh checks PySide6 before exec: a venv without PySide6
  prints a plain "run bash install.sh" message (with a zenity or
  kdialog dialog when there is no terminal to read it in) instead
  of a raw traceback invisible from the menu.
- T63 — install is atomic: the final `import stella` check runs
  before the launcher and symlink are written, so a failed install
  leaves no launcher behind.
- T64 — Install Stella.desktop ships in the tree: double-click it
  to install (it runs install.sh with bash and survives spaced
  paths). The README install section names the real first step,
  qualifies the `stella` command (new terminal or log out/in),
  and documents removal and repair.
- T65 — the scripts carry exec bits in the tree (run.sh,
  stella-cli, install.sh, install-training.sh, run_tests.sh,
  uninstall.sh, Install Stella.desktop), pinned by a test.
- T66 — `stella doctor` checks the venv, PySide6, launcher,
  symlink, and icon, and re-links what is stale after a move; a
  broken venv is reported with the fix named. `--check` only
  reports, without fixing.
- T67 — install.sh's pip lines carry `--timeout 120 --retries 10`,
  like install-training.sh already did.
- T68 — run_tests.sh refuses on a bare checkout with "run bash
  install.sh first" instead of pip-installing into system Python.
- T69 — tests/test_installer.py runs the real installers in a
  scratch HOME: desktop file, icon resolution, symlink, re-install
  idempotence, clone without PNGs, and the failure cases.
- T130 — LICENSE (MIT), pinned requirements (requirements-base.txt:
  PySide6-Essentials/Addons 6.12.0; requirements-train.txt: torch
  2.15.0+cpu, transformers 5.22.2, peft 0.21.2, accelerate 1.15.0),
  both installers consume the pinned files, and a GitHub Actions
  CI workflow runs the base suite (plus the training-stack suite
  in its own job). The repo description/topics half is GitHub-side,
  not tree work.
- T132 — pip failures end with a Stella line naming the step and
  the retry, in both installers.
- T133 — disk-space preflight: the base install refuses below
  ~500 MB free, the training install below ~3 GB, before
  downloading anything.
- T134 — a training re-run with everything already installed
  prints "Training packages are already installed." and exits in
  seconds instead of re-resolving the torch index.
- T135 — the PySide6 check creates a throwaway QApplication
  offscreen instead of import-only, and surfaces the real stderr
  on failure so a missing system lib names itself.
- T136 — the success message reflects reality: the desktop icon
  is claimed only when the copy landed, `stella` is claimed only
  when ~/.local/bin is on PATH (otherwise it says to open a new
  terminal), and the version line is labeled ("Stella 0.15.0").
- T137 — uninstall.sh removes the launcher, desktop copy, symlink,
  menu icons, venv, and receipt, and asks about ~/.stella before
  touching it (default No); the README documents removal.
- T138 — icons install into the hicolor theme at 16/22/24/32/48/
  64/128/256/512, rendered by render_icon.py, so the menu icon
  survives a folder move; the launcher uses the theme name.
- T139 — install.sh writes an install receipt (.stella-install-
  receipt): versions, artifact paths, install time. A failed
  install writes no receipt; install-training.sh refreshes it
  with the torch versions.
- T140 — the README documents the upgrade path: unzip the new
  version, run its install.sh, delete the old folder.

## v0.14.0 — 2026-11-14

The models + UI-polish slice (audit tasks T43, T45, T47, T49, T50,
T58, T59, T61, T145, T146, T147, T149): the model list is cached
and fetched off the UI thread, imports show a preview first and
check the base model, datasets are validated where they are
picked, and the window gets a finish moment, loading states, a
job morph, and accessibility presets.

- T43 — the Ollama model list is cached and fetched off the UI
  thread: one fetch at startup, none on any click, and a Refresh
  button (plus a refresh when the New Profile dialog opens) for
  the rest. The window keeps showing the last good list while a
  refresh is in flight, and a hung Ollama never blocks a click.
- T61 — base-health check on import: a package whose profile
  tag is not installed on this PC warns (naming the tag) instead
  of importing silently and failing later. The check uses the
  cached model list (T43); it never blocks the import.
- T45 — dataset picker + validation: the Project window has a
  Browse button next to the Dataset field, and the field now
  explains itself: a valid file shows its example count, the
  train/check split, and a 3-example preview; a missing file
  warns ("Dataset not found. Is the path right?") without
  blocking the save; a malformed file names the bad line. The
  Train panel's dataset pick reports the same check.
- T47 — the Train panel resets per project and stays pinned to
  the running project: switching projects resets the progress
  bar as well as the loss line, the no-selection state shows an
  empty bar, and switching mid-run leaves the panel on the
  running project (naming it) instead of mixing panels.
- T49 — the missing-training-packages hint is a warning dialog
  now, not a line in the below-fold Train log: on a first run
  without the training stack, the fix is visible without hunting.
- T50 — confirmations survive their refresh: the training-done
  and sleep-done messages are said after the refresh that used
  to overwrite them, so "Trained N steps." is still in the
  status bar after the lists settle (import already did this).
- T59 — the dataset is part of the package decision: export
  offers to copy the dataset in (with its size shown) or keep
  the reference; a bundled dataset is used on import; an
  unbundled reference that is missing on this PC warns and
  offers to locate the file here.
- T58 — import preview dialog: before anything lands, the
  window shows the package's profile, project, tag, version,
  and contents, with the existing-profile warning (T57's
  compare) and the base-health and dataset status, and the
  user confirms or cancels. Cancel imports nothing. The CLI
  prints the same summary before importing, and --preview
  prints it without importing.
- T145 — the finish moment: when a job completes, the job card
  glows gold once with a short summary line, under 300 ms,
  never looping. The reduced-motion preset skips the glow.
- T146 — loading states, never a dead screen: the model list
  shows skeleton rows while Ollama answers, replaced by the
  real rows (with fit verdicts) when they arrive; the Ollama
  status refresh shows it is working.
- T149 — the job picker becomes the job: the picked job tile
  morphs into the running-job card, under 400 ms, and the
  morph stops cleanly if the job is cancelled. Reduced motion
  swaps instantly instead.
- T147 — accessibility presets in Settings: reduced motion
  (turns off the press dip, the job morph, and the finish
  moment, and keeps every state change) and larger text (bigger
  words everywhere), both in plain words and remembered.

## v0.13.0 — 2026-11-14

The export/import + projects slice (audit #3/#8 tasks T23, T29,
T30, T34, T36, T40, T41, T48, T51, T53, T54, T57, T60): packages
are versioned, weights round-trip, deletes go to a trash, and
the project lifecycle has one vocabulary everywhere.

- T29 — one job at a time, enforced by the engine: a lock file
  (`job.lock` in the home) is held for the whole job, so a second
  job — from the window, the CLI, or a second Stella — is refused
  in plain words naming the running job. The kernel releases the
  lock if the holder dies, so a crash can never wedge the home.
  Sleep takes the lock once and its inner training call skips it.
- T36 — closing the window waits for every worker: close during
  a job asks the workers to stop, says "Stopping ..." in the
  status bar, the job card, and the log, and closes for real
  when the last worker ends. The window never destroys a running
  thread (the old Qt abort), and never blocks the UI waiting.
- T40 — package format versioning: the manifest carries `format`
  (this Stella writes and reads format 1), separate from the app
  version. A newer format is refused with "this package needs a
  newer Stella"; a package with no format field is a legacy
  v0.1-v0.12 package and reads as format 1. The three package
  kinds (`stella-export`, `stella-profile-export`,
  `stella-recipe-export`) are defined in one place, and importing
  a known kind this Stella cannot import yet says what the
  package is. The format is documented in docs/FORMAT.md.
- T41 — weights and probe results round-trip: the package's
  weights/ land in the project's adapter/ dir on import (byte
  identical), and probe_results.json comes back too. A package
  whose manifest claims a finished status but carries no weights
  imports as a draft, with a warning in the window and on the
  CLI. The placeholder note is never copied as a weight.
- T23 — trash on delete: deleting a profile or project moves it
  to `trash/` (dated folder), and the confirm dialog offers
  export-first. The File menu's Trash window lists what is
  there, purges one item forever (its own confirm, defaulting
  to No), or empties the trash. Moving a trash folder back
  restores it. Import rollback still destroys outright, so a
  failed import leaves no trash folder behind.
- T30 — probe v2: refusals are read from the reply's first
  sentence, with new markers, a compliance override (a reply
  that starts answering is not a refusal), and the "can't
  believe" idiom excluded. Replies with no answer are counted
  and shown in the CLI, the window, and the chat. The probe
  gate fails a silent model, and an empty prompt list is
  refused. Replies are generated through the chat template
  when the tokenizer has one.
- T34 — target-module override: `--target-modules` on the CLI
  (or `target_modules` in the project settings, CLI wins) picks
  the LoRA target modules instead of auto-detection. A name
  the model does not have is refused with the available names
  listed. No UI: training settings stay out of the window
  (T16).
- T48 — cheap checks first: training reports a bad profile,
  missing dataset, missing base, or nothing-to-resume BEFORE
  the dependency gate, so a mistake is never answered with
  "install the training stack". The dependency check fires
  only when everything else is ready.
- T51 — CLI help everywhere: every flag and positional on all
  15 commands has help, and every command's `--help` shows a
  worked example. The module docstring, the empty-home hint,
  the `stella-cli` wrapper comment, and the README now all list
  the same 15 commands.
- T54 — base_ref sync rule (interim, until Joshua decides drop
  vs define): changing a profile's tag moves base_ref to the
  new tag when the base was following the old tag (or empty);
  a deliberately split base stays split, and an explicit base
  in the same save always wins. Training trusts base_ref.
- T60 — config.json dropped: the manifest already holds the
  settings, and nothing ever read the config.json copy, so
  export stops writing it. Old packages that carry it still
  import; a disagreeing or unreadable config.json is ignored
  and the manifest's values win.
- T53 — one status lifecycle, reconciled: the task's enum
  (draft/ready/training/done/failed/exported) and the engine's
  `trained`/`paused` are now one vocabulary: `draft`, `ready`,
  `training`, `paused`, `done`, `failed`, `exported`. Mapping:
  engine `trained` is now `done` (the task's word, plainer);
  `paused` is kept (pause/resume is a real state with no slot
  in the task enum); `ready` and `failed` are new. A crash
  marks the project `failed`, a graceful stop marks it
  `paused`. `trained` survives only as a legacy alias: old
  project files and old packages read as `done`, and are
  rewritten with the current word on the next write. The
  window shows the status on every tree row and in the
  project window, with a Mark ready button on drafts.
- T57 — merge, don't discard, the profile block on import:
  when the profile already exists, tag / role / base are
  compared with the manifest — identical blocks import
  silently; differing blocks ask (a dialog in the window,
  `--profile-merge keep|take` or a prompt on the CLI). With no
  way to ask, the local values are kept and a warning says so.
  "Take" makes the stored block exactly the package's, and a
  failed import restores the local values. The window and the
  CLI both say when the profile already existed. Extension
  point for T58: `compare_profile_block` in export.py (and its
  diff shape) is what the import preview dialog reuses.

## v0.12.0 — 2026-11-14

The UI rebuild, P1 slice (audit #9, tasks T74-T82): every job
runs as a card, the chat plans before it runs, and STELLA gets
its own look.

- T74 — one job card for every job: Train, Sleep, GGUF export,
  refusal probe, re-quantize, and distill all run as a card
  under the hero, with a progress bar, a live status line, and
  a Cancel button. Sleep stops being a section at the bottom of
  a column. Starting a second job is refused in plain words
  ("A job is already running. Wait for it to finish, or cancel
  it first."). Train and Sleep cancel after the current step
  with a checkpoint saved; the other jobs stop at the next check
  point (a running subprocess is killed). The engines gained
  cancel checks and progress events to feed the card
  (`should_stop` / `on_event` in distill, requant, gguf, probe).
- T75 — re-quantize and distill get window surfaces: both jobs
  already started from the job picker; now they run as job
  cards too, and How to Use stops sending the user to the
  terminal for them. Both start from the window with no typing.
- T76 — chat: click-to-pick model, plan before it runs. When
  no chat model is picked, the chat shows clickable model
  buttons from the installed list instead of "type one of
  these". Before a multi-step plan runs, the agent shows the
  plan ("I will: 1. ... 2. ...") with Run and Cancel buttons
  and waits for the go-ahead. Replies stream as they arrive
  (Ollama `chat_stream`); a tool block is never streamed, so
  the user never sees JSON.
- T77 — the session follows the profile: the last project is
  remembered per profile, so switching profiles restores that
  profile's project. The memory lives in QSettings and survives
  restarts.
- T78 — tree rows show full names, with a health badge: the
  tree pane defaults wider (340 px), every row carries its full
  text as a tooltip, and each profile row shows a health dot —
  green when the weights are ready, amber when they are not,
  grey when Ollama is down and the weights are not ready
  (weights ready wins over Ollama down, since training can
  start without Ollama). The tooltip carries the health line.
- T79 — one honest download row: the Profile window's duplicate
  download row is gone; the main window's row is the only one.
  Download is disabled when there is no repo, and a "Set the
  model source..." button shows instead, opening the profile
  window where Base ref gets set. The Base ref field stops
  showing a tag as if it were a repo (a tag-valued base_ref
  shows blank, with a placeholder saying what belongs there).
- T80 — collapsible section headers: the main panel's train
  details (Dataset, Checkpoints, Training log, Sleep) and every
  Settings section are collapsible groups, open by default.
  The Project window's action row (Save, Rename, Delete,
  Close) is pinned below the scroll area, so Save is visible
  without scrolling.
- T81 — STELLA's own look: one stylesheet (`stella/style.py`),
  drawn from the icon — dark surfaces, the gold accent — applied
  by `main()` to every window. Button presses dip to 0.97 over
  150 ms. No per-frame cost: the sheet is static, the dip is a
  press-only geometry animation.
- T82 — keyboard: shortcuts for the main actions (Ctrl+N new
  profile, Ctrl+Shift+N new project, Ctrl+G run the picked job,
  Ctrl+S save, F1 How to Use, F2 Chat), a visible gold focus
  ring in the stylesheet, and tab order in visual order on the
  main screen and every dedicated window.

## v0.11.0 — 2026-11-14

The UI rebuild, P0 slice (audit #9, tasks T15-T20): the window
becomes toy-simple. Pick a model, pick a job, press go — nothing
else on the way.

- T15 — the main screen is a bento tile now: 1. Pick a model,
  2. Pick a job (Train, Sleep, Make smaller, Teach a small model),
  3. Press go. The Train and Sleep buttons are gone; Go runs the
  picked job. With no project yet, Go asks for the job name
  inline and creates the project as part of the pick (this
  supersedes T113). With no dataset yet, Go offers the sample or
  a file pick, inline. The tree stays as the library. The model
  pick, the job pick, and Go all sit above the fold at 1100x680.
- T16 — settings leave every screen. The settings form is gone
  from the Project window (name, dataset, notes stay), the
  settings line is gone from the session summary, the Training
  defaults block is gone from Settings, and the chat template,
  the chat greeting, and the How to Use topics stop naming
  settings. Stored settings still exist in the model for
  compatibility; nothing in the UI reads or writes them. The
  chat agent's set_project_settings tool is removed outright —
  a model-facing settings path would still be the user touching
  settings through the chat, which the Brief forbids.
- T17 — first-run setup checklist: on first launch the main
  screen shows three steps (1. Pick a model. 2. Get its weights.
  3. Run a tiny first training, a real 20-example run) instead
  of a disabled wall. Each step is a button that does the step;
  a finished step ticks. Dismissible, never reappears as a modal,
  and a running job always shows the main screen instead.
- T18 — the model picker is a list now: each row shows one plain
  line for what the model does plus a fit verdict (Fits this PC,
  Too big for this PC, or honestly unknown) from the backend's
  PC measurement. Details (size plus RAM numbers) appear on tap,
  not up front. Nothing is selected by default; Enter with no
  pick does nothing.
- T19 — a real menu bar (File, View, Help) replaces the Menu
  button. Actions that need a selection (New project, Export
  project, Profiles, Projects) are disabled until one exists,
  instead of opening a "pick one first" modal.
- T20 — live training graphs and stats: a loss curve drawn on
  new points only, plus speed (steps a minute), RAM used, time
  left, and epoch, in the glanceable card under the hero. The
  last run's curve is rebuilt from the project's run log, so it
  is still there after the run finishes.

## v0.10.0 — 2026-11-13

The finish list, second slice: the RAM guards estimate before
loading anything, the training loop is reproducible and honestly
capped, and the destructive paths (re-train, re-export) ask or
refuse instead of silently destroying finished work.

- T28 — the RAM guard estimates from the model's config + weight
  sizes (`load_model_metadata`, `estimate_training_from_metadata`)
  before loading anything; a run that will not fit is refused
  before the base is anywhere near memory. A second guard with
  the real param counts still runs after the load.
- T31 — merge RAM guard (`estimate_merge_bytes`, `check_merge_fit`
  in `gguf.py`): base + merged copy + headroom, refused before
  loading when it does not fit. The converter warning
  (`merge_warnings`, `on_warning`) tells the user to close other
  apps when merge + converter together pass the ceiling.
- T32 — seed everything: `torch.manual_seed` at fresh-run start
  (before the LoRA init), and the torch RNG state saved in every
  checkpoint and restored on resume. Same seed, same adapter;
  pause/resume is bit-identical to an uninterrupted run. Old
  checkpoints without RNG state still resume.
- T56 — `--steps` is a real cap: `run_training_loop` takes a
  remaining-steps budget, breaks mid-epoch at the cap, and
  reaching the cap is completion (adapter saved, status trained),
  not a pause. 0/negative refused in argparse and in the engine.
  The old epochs-shrink hack is gone.
- T25 — re-training a trained project refuses ("already trained.
  Use --force to re-train it") and leaves the adapter untouched;
  `--force` re-trains deliberately. `--resume` on a trained
  project announces the extension and the new total first (the
  `extending` event, printed by the CLI and the GUI). The GUI
  asks before re-training. Sleep is never blocked (it runs with
  `update_status=False`).
- T24 — GGUF export refuses to overwrite an existing GGUF (the
  REFUSE pick, checked before the merge); `--force` on
  `export-gguf` overwrites deliberately. Never deletes a previous
  export silently.
- T26 — `export_gguf` checks llama.cpp before the merge; a failed
  export removes the half-finished merged dir and the F16
  intermediate and says so in the error.
- T27 — the GGUF path validates `--quant` up front with the
  existing `requant.validate_quant` (no second validator): a
  bogus quant fails in a millisecond, before the merge.
- T102 — `find_llama_cpp` requires an executable quantizer; a
  non-executable file is refused naming the file and the
  `chmod +x` fix.
- T99 — completions are bound to `max_seq_len` (head + EOS kept,
  `truncated` flag); the loop warns with the count of cut
  examples, shown by the CLI, the GUI, and sleep.
- T2 — dirty tracking in the Profile and Project windows:
  snapshot-based `is_modified`, title asterisk, Save/Discard/
  Cancel on close and on rename, notes-only save.
- T3 — damaged manifests are rows, not silent skips: greyed +
  italic in the GUI tree (click = status message, double-click
  opens the manifest for repair), `(damaged: ...)` rows in the
  CLI lists, skipped by session restore and rename.
- T8 — Start training checks the open Project window's unsaved
  edits first (Save/Discard/Cancel); a bad learning rate sitting
  unsaved stops the start instead of training on stale settings.
- T10 — the refusal probe loads one base at a time (before run,
  free, after run) instead of holding both in memory.
- T12 — soft tag validation: creating a profile (or saving one)
  with an Ollama tag that is not installed locally warns and
  asks, default No. An empty tag or an unanswered Ollama never
  warns.
- T13 — the live training log keeps its in-memory lines when the
  panel refreshes; JSONL re-renders as friendly
  `step N/total loss x.xxxx` lines on project switch.
- T22 — checkpoint resume loads `optimizer.pt` with
  `weights_only=True`; a malicious pickle is refused, never
  executed.
- T33 — every dataset split keeps at least one validation row
  (n=2 is 1 train + 1 val, as `load_dataset` promises).
- T35 — the CLI closing line says "GB RAM (estimated)", not
  "GB RAM used": the figure is the pre-run estimate, not a
  measurement.
- T142 — tests for the risky CLI paths: unknown/no command (exit
  2 + usage), `--steps` 0/negative, `--quant BOGUS`, corrupt-home
  lists, resume-on-trained announcement, `--force` plumbing,
  converter-warning print.

## v0.9.0 — 2026-11-13

Auto-config backend plus the P0 foundations from the finish list.
The backend now measures the PC and picks the training settings,
so the user never has to; the trust boundary (import/export) is
strict and atomic; and the model, the CLI, and the engine all
validate settings the same way.

- Auto-config (new `stella/autoconfig.py`, Qt-free, stdlib only):
  `measure_pc()` reads CPU count + model, RAM total/available,
  free disk on the Stella home filesystem, and load; 
  `compute_settings()` picks the recipe by documented conservative
  rules — batch size always 1 on CPU; rank 8, learning rate 2e-4,
  3 epochs, max sequence length 1024; rank 4 and seq 512 when less
  than 4 GB of RAM is available. New projects get the computed
  settings with `settings_source="auto"`; training re-measures at
  run start for auto projects and stores the fresh values. Anything
  a human set (Project window, chat, import) is `"manual"` and is
  never recomputed. New command: `stella pc-info` prints the
  measurement and the picked settings in plain words.
- T37 — one defensive metamorph reader (`metamorph_mode` in the
  model layer): a missing, null, or wrong-type block yields the
  default mode instead of a crash. `get_project` defaults the
  block; `update_project` reads through the reader.
- T38 — export reads metamorph through the reader and builds the
  whole package in a staging dir, moved into place only when every
  file is written: no crash on `metamorph: null`, no partial
  package on failure.
- T39 — a string-metamorph project shows a warning row in the GUI
  tree and a warning line in the CLI project list, via the reader.
- T1 — trust-boundary import: strict manifest schema in
  `verify_export` (types for settings, config, dependencies,
  status, metamorph mode); slugs normalized once at import start,
  so returned names match stored names; import is atomic
  (settings validated before anything is created, plus rollback of
  anything created on a late failure); the GUI import handler gets
  a last-resort catch and refreshes the lists on failure. No format
  versioning here — that stays T40's.
- T4 — the train command's Ctrl+C handler no longer prints from
  inside the signal handler (the pause message already comes from
  the `paused` event), matching the sleep handler. Subprocess
  Ctrl+C-pause test: pause, checkpoint saved, exit 0.
- T5 — `main()` catches everything: one clean `stella:` line, exit
  1, no raw traceback on the default path. `profiles` reads
  defensively (a nameless manifest degrades to a warning line).
  HF load failures in `load_base_model` are wrapped as StellaError
  naming the repo/path and the likely cause.
- T6 — settings validated in the model (`validate_settings`,
  ranges matching the chat's table, now the single table both use):
  bad rank/epochs/batch/learning rate/seq len, unknown keys, and a
  bad method are all refused with the key named. `_write_json`
  refuses NaN/inf. The engine re-checks every numeric setting it
  reads (`validate_run_settings` at the top of `train_project` and
  `run_training_loop`) instead of bare int()/float().
- T21 — the Project window fills defensively: a bad stored value
  falls back to the default with a "stored value was invalid" note,
  the fill never aborts mid-way, and Save can never write another
  project's values back.
- Pinning tests (no behavior change): T44 geometry (Start training
  + progress bar inside the 1100x680 viewport), T71 (no metamorph
  promise text in any visible GUI string), T123 (no-project session
  summary holds no settings values; no project window opens with no
  selection), T162 (a second launch against a live first instance
  exits 0 with no second window).

## v0.8.0 — 2026-11-13

This completes the stopped v0.5 scope (re-quantize + distill),
shipping as v0.8.0 because v0.6 and v0.7 shipped in between. The
new work is engine, command line, and Chat tools, plus one window
change: the MetaMorphAi control is gone from the Project window.
It did nothing (training ignored it), so it gets no control. The
stored mode stays in project files for compatibility, and saving
a project leaves it untouched.

- Re-quantize (new `stella/requant.py`, `stella-cli requant <tag>`):
  take an installed Ollama model and make a smaller copy at a
  smaller quant (default Q4_K_M). Stella finds the model's GGUF
  file from Ollama's own manifests (with `ollama show --modelfile`
  as the fallback), checks llama-quantize and Ollama exist, checks
  free disk before writing, quantizes, and registers the copy as a
  new tag with `ollama create`. The original model is never
  touched, and the new tag must not already exist. Bogus quant
  names are rejected up front, never passed to the tool.
- Distillation (new `stella/distill.py`, `stella-cli distill
  <profile> <project> --teacher <tag> --prompts <file>`): a teacher
  model in Ollama answers a list of prompts, one per line, and its
  answers become the project's dataset (distilled.jsonl, prompt /
  completion rows, validated like any dataset). Empty answers are
  skipped and counted, identical pairs are kept once, and a re-run
  skips prompts already answered. Training is not started: the
  user looks at the dataset first, then runs `stella train`.
- Ollama client gains `generate()` (one /api/generate call, plain
  words on failure) and `reachable()`; distill uses both.
- Chat gains two tools: `distill` and `requant`, so the Chat can
  run both jobs for you. The training template is unchanged: the
  full template rework is a later version.
- How to Use gains two topics: "Making a model smaller" and
  "Teaching a small model", honest about the limits: re-quantizing
  an already-quantized model loses a little quality, and neither
  feature removes capabilities from the original model. They make
  a new smaller one.

## v0.7.0 — 2026-11-13

Provider connections: the chat can talk to Groq, Gemini, or any
OpenAI-compatible service with your own key, as well as to a model
on this PC through Ollama.

- New `stella/providers.py`: provider registry, key storage, and
  chat clients. Keys live only in `~/.stella/providers.json`,
  file mode 0600, and never appear in code, exports, or debug
  reports. Groq and Gemini speak the OpenAI chat shape (Gemini
  through Google's OpenAI-compatible endpoint, key as the Bearer
  token). Custom takes any base URL, key, and model name.
- Settings gains an AI providers section: one row per keyed
  provider with a password-style key field, Save, Test (one tiny
  call, run off the UI thread), and Remove. A short line says the
  keys stay on this PC.
- The chat-model picker now groups models by provider: On this PC
  (Ollama), then Groq, Gemini, and Custom. A provider with no key
  saved shows its models greyed out.
- ChatAgent takes a provider + model; a missing key is a plain-words
  message naming Settings, never a crash. `stella-cli chat` takes
  `--provider groq|gemini|custom|ollama` and `--model`.
- Debug-log scrubber now also redacts bare Groq (gsk_...) and
  Google (AIza...) keys.

## v0.6.0 — 2026-11-13

Provider chat: an AI chat inside Stella that sets up and runs
training for the user, instead of forms and panels. Built to the
"as simple as a toy for a 5-year-old" bar.

- Chat window (Menu, then Chat): talk in plain words ("train LFM3
  to write short replies") and the chat asks only for what it
  needs, fills the rest with defaults, and runs the job. Tool calls
  are narrated in plain words while they run, and a Cancel button
  stops the current job. One chat window at a time; the agent loop
  runs in a worker thread, never on the UI thread.
- The training template (new `stella/chat_agent.py`): the 8 steps
  every training run needs, whatever the model (Goal, Base model,
  Data, Settings, Train, Check, Export, Test and back up). The
  agent walks one step at a time and says which step it is on. On
  "just do it" it runs the whole template end to end with the
  defaults and the sample dataset.
- Tool calling that works with small local models: the model emits
  a fenced ```tool block holding one JSON object; the agent
  parses it, runs the tool, and feeds the result back. Malformed
  tool JSON never crashes the loop: the agent asks the user in
  plain words. Capped at 12 tool calls per message.
- Tools wrap the existing engine only (no new training logic):
  list/create profile and project, settings, dataset, sample
  dataset, start training, training status, refusal probe, GGUF
  export, checkpoints, sleep, sleep status, weight downloads,
  How to Use lookup. Settings are validated (rank 1-64, learning
  rate 0-1, and so on); "full" fine-tuning is refused in plain
  words.
- Chat model picker in Settings: pick which installed Ollama model
  the chat talks to. Nothing is picked by default; if none is
  picked, the chat asks which installed model to use instead of
  failing.
- `stella-cli chat`: the same agent as an interactive REPL
  (--model to pick the model, /quit to exit).
- How to Use gains a Chat topic (11 topics now).

## v0.4.0 — 2026-11-13

Redesign + one-click model downloads + built-in guide, from Joshua's
sketch and the "teenagers and old people can use it" bar. The
three-pane window is gone.

- Window redesign: a Menu button top-left (Profiles, New profile,
  Projects, New project, Export, Import, Settings, How to Use
  Stella); a collapsible profile tree on the left (each profile
  expands to show its projects); the main area shows the current
  training session: profile and project summary, model download,
  Train panel, Sleep panel. Clicking a project in the tree sets the
  training session, and the session is remembered across restarts.
  Nothing is selected on first run.
- Dedicated windows, no cramming: double-clicking a profile or a
  project row opens its own window, with the v0.3.1 plain-words help
  lines under every field. Settings has its own window (Stella home,
  Ollama status + host, training defaults, Debug report button).
- One-click model downloads (new `stella/provision.py`): a Download
  model button in the Profile window and the session view. Base
  weights download from Hugging Face in a separate process with a
  progress bar and a Cancel button; interrupted downloads resume
  where they left off. Status shows Not downloaded / Downloading x%
  / Ready + size on disk. When training starts and the weights are
  missing, Stella offers the download first instead of failing.
  Plain-words failures: no network, no Base ref set, not enough disk
  (checked before the download starts).
- How to Use Stella window: a full index (Getting started, Picking a
  model, Profiles, Projects, Training, Sleep, Export and import, The
  refusal probe, GGUF export to Ollama, Troubleshooting) in plain
  words, accurate about what Stella actually does: MetaMorphAi modes
  do nothing yet, full fine-tuning doesn't run on this PC, training
  takes hours on CPU.
- Debug log layer (U12): rotating timestamped logs under the Stella
  home, last-200 ring buffer, traceback capture, scrubbed debug
  report from the Settings window, crash handler in the real app
  entry.
- Single instance (U27): re-clicking the icon focuses the running
  app, never starts a second copy.
- Destructive confirmations default to No, and Escape leaves things
  untouched (U23/U31). The delete confirm used to default to Yes.
- Window geometry and tree expansion are remembered between runs
  (U5); tree expansion and scroll survive refreshes (U28); a visible
  activity light + status text shows what Stella is doing during
  downloads, training, and sleep (U16).
- No em-dashes in any visible UI text (U33): every user-visible
  string in the window, the dialogs, the status messages, and the
  engine error messages was swept. Same words, em-dashes out.

## v0.3.1 — 2026-11-13

Real-PC usability patch, from Joshua's first run on his Mint PC.
The v0.3 window opened, but the New Profile form rendered as a
garbled smear over the main window, the desktop icon showed the
generic gear, and the desktop launcher was untrusted.

- New Profile is a real window now (QDialog + exec()), not a
  frameless QWidget child — the form can no longer smear over the
  main window (merged-list T11, audit #4 W1).
- New Profile asks for ONE thing: pick a model. No role, no display
  name, no base ref up front — the profile's name comes from the
  model (`LiquidAI/LFM3-1.7B` -> `lfm3-1-7b`), a clash gets `-2`,
  and role/display/base can be changed later in the profile panel.
  An installed model becomes the Ollama tag; a namespaced id that
  isn't installed becomes the Hugging Face base ref.
- The profile panel explains itself: one plain line under Display
  name, Role, Ollama tag, and Base ref saying what each one is for.
  The Processor row is gone — nothing in Stella ever read that
  field, so showing it only asked a question nobody could answer.
  The stored value stays in profile.json for compatibility.
- New icon: the ✨ sparkles (gold, on transparent), in the SVG,
  all PNG sizes, the window title bar, and the launcher.
- Installer fixes (merged-list T14): `Icon=` is unquoted (GLib
  never stripped quotes from Icon=, which is why the menu showed
  the gear); `StartupNotify=false` so a slow cold start no longer
  trips a "Timeout was reached" launch error; the desktop launcher
  is marked trusted with gio so Cinnamon stops asking; and
  install.sh renders the icon PNGs from the SVG when they're
  missing (fresh clone), using QtSvg from PySide6-Addons.

## v0.3 — 2026-11-13

Sleep phase (Item 4): consolidate new rows without forgetting old ones.

- Sleep engine (stella/sleep.py): a sleep cycle trains a NEW
  low-rank LoRA adapter (rank capped at 8) on the dataset rows
  added since the last sleep, tracked by content hash in a sleep
  manifest. The base and all prior adapters stay frozen. Each cycle
  stores its adapter, checkpoints, rows, and report under
  `sleep/cycle-N/`; an interrupted cycle resumes instead of
  restarting. Consolidation reuses the training engine
  (train_project with a per-cycle work dir) — it does not fork it.
- Dreaming (optional, `--dream`): the local Ollama model writes
  synthetic practice examples, seeded by real rows. Every dreamed
  row passes the same validation as real data, dedupes against
  real and already-dreamed rows, and dreamed rows are capped at
  the number of real rows in the cycle (at most 10 per call). If
  Ollama is unreachable, dreaming is skipped with a plain message
  and sleep still runs on real rows.
- Replay check (the forgetting guard): before a cycle is accepted,
  the new adapter is evaluated on held-out OLD validation rows
  (kept from prior cycles) plus NEW validation rows. A cycle whose
  old loss degrades more than 10% relative (configurable) is
  flagged DEGRADED — saved, never silently accepted. The replay
  loads the base model ONCE and evaluates sequentially by adapter
  swapping; it never loads two models at once.
- RAM guard reused: sleep refuses when the estimate does not fit
  8 GB, with a plain message. Sleep leaves the project status
  alone — it is a background job, not a retrain.
- CLI: `sleep` (with --dream, --dream-model, --rows, --threshold)
  and `sleep-status` (per-cycle stats + unslept row count). Cheap
  checks run before the dependency gate, so a missing dataset or
  "nothing new" is reported even on a base install. The Ctrl+C
  handler sets the pause flag only (no printing inside the signal
  handler — the train command's pause crash is not repeated here).
- Sleep panel in the window: Sleep button (worker-threaded, gated
  on save success), Dream checkbox, cycle list with per-cycle
  stats, click a cycle to read its full report. Sleep and training
  cannot run at the same time (each loads the base model).
- Export/import: sleep cycles travel with the export (manifest +
  adapters + rows + replay reports) and import restores them
  whole — a round-trip test pins it.
- Training engine refactors (small, backward-compatible): per-row
  dataset validation shared by load_dataset and dreaming; one
  public evaluate_loss used by per-epoch validation and the replay
  check; train_project takes a work dir, a status flag, and a
  settings override so sleep can reuse it. The requires_grad
  UserWarning from float(out.loss) is fixed in both places it
  occurred.

## v0.2 — 2026-11-12

First proof loop: the training engine (Item 3).

- Training engine (stella/train.py): CPU micro-LoRA (transformers +
  PEFT), batch 1 with gradient accumulation, completion-only loss,
  train/validate split, per-epoch validation loss, loss log per
  project. LoRA target modules auto-detected from the model.
- RAM guard: estimates base weights + LoRA gradients + AdamW states
  + activations + 1 GB headroom before loading anything, and refuses
  a run that will not fit 8 GB. A full 1.7B fine-tune (~28 GB of
  optimizer state) is refused outright.
- Checkpoints + resume: adapter + optimizer + training state saved
  every N steps; Pause (button or Ctrl+C) checkpoints cleanly and
  `--resume` continues from the saved step, optimizer included.
- GGUF round-trip (stella/gguf.py): merge the adapter into the base,
  convert with llama.cpp to F16 GGUF, quantize (Q4_K_M default),
  write an Ollama Modelfile with the exact `ollama create` command.
  llama.cpp missing is a clear error with install steps, never a
  silent failure.
- Refusal probe (stella/probe.py): 12 benign prompts run before and
  after tuning, refusal-rate change reported and saved. Informational
  for LFM3; a gate for governing-seat tunes.
- Train panel in the window: dataset picker + sample dataset button,
  Start / Pause / Resume, progress bar + loss readout, checkpoint
  list, Export GGUF, Run refusal probe, training log. Training runs
  in a worker thread; the window stays responsive.
- CLI: `train`, `export-gguf`, `probe`; `create-profile --base` sets
  the Hugging Face base ref.
- Sample dataset (data/sample-tool-calls.jsonl): 20 synthetic Forge
  tool-call traces (14 tool calls, 6 plain answers) so the proof
  loop runs without real data.
- Training packages are optional: `bash install-training.sh`
  installs torch CPU + transformers + peft + accelerate (about 2 GB)
  into the private venv. The base install stays light; training
  without them names the installer instead of failing cryptically.
- Exports now carry the trained adapter in `weights/` (and the
  probe results when run) instead of the placeholder note.

## v0.1 — 2026-11-12

First skeleton. No training engine yet (Item 3).

- Profiles with friendly role names, Ollama tag picker (works offline
  when Ollama is down), full create/rename/delete.
- Projects inside profiles: dataset ref, training settings, MetaMorphAi
  mode (morph / compress / both), checkpoints dir, notes.
- Export a project as a folder (manifest, config, README, weights,
  checkpoints) and import it back with verification.
- Native Qt window: profiles left, projects middle, detail right.
- CLI: profiles, projects, export, import, create-profile,
  create-project.
- Installer: private venv, app-menu launcher with star icon, desktop
  icon, `stella` command on PATH.
- Verification fixes (same day): status text shown once, in the
  status bar only (a duplicate label was removed); launcher Exec/Icon
  quoted so install paths with spaces work; installer names the
  `sudo apt install python3-venv` fix if the venv module is missing.
