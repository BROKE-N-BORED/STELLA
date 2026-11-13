# STELLA Design Brief — under the design philosophy

2026-11-13. STELLA is the worked example of the philosophy in
`~/workspace/design-philosophy.md`: complex underneath, simple on top.
This brief applies it to STELLA concretely. It is a brief, not a build
order — the STELLA thread builds from it on Joshua's word.

## The bar

A child could train a model with it. If the UI shows complexity, the
design failed. STELLA does four jobs: train, fine-tune, trim, and
compress AI models. All four must be that simple.

## The UI

- Toy-simple: toggles, buttons, and options. Nothing else on screen
  that doesn't need to be there.
- One dropdown menu button (Profiles, New Profile, Projects, New
  Project, Settings) that opens the thing and sets the training
  session.
- Real Windows-style menus and drop-down menus. Collapsible headers
  in panels.
- Pick a model, pick a job, press go. That is the whole flow.
- Real graphs and stats, live and ongoing, middle-school science
  software feel: loss, speed, RAM, progress. The user watches the
  measurements; the backend does the adjusting.

## The backend (the user never sees this)

- Measures the PC's specs and performance silently and ongoing:
  CPU, RAM, disk, current load.
- Sets all training settings to the best values for this machine:
  learning rate, batch size, and everything else. The user never
  sees these settings and never touches them.
- Builds the right environment for the job on this PC, so training
  is fluid and seamless on the front end.

## Model selection

- Shows what the model does and whether it fits this PC.
- Sizes are handled under the hood. The user never guesses at sizes
  or specs.
- One-click setup: picking a model pulls everything it needs, with
  a progress bar.

## What the user never sees

Learning rate, batch size, optimizer settings, memory settings, and
anything else that doesn't change. If a setting doesn't need a human
decision, it doesn't get a control.

## Release

Every release ships a desktop installer executable that installs or
updates all dependencies, plus a creative and beautiful desktop icon.
