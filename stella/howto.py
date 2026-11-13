"""STELLA How to Use index: the built-in guide.

Eleven topics, plain words, no jargon left unexplained. Every claim
here is checked against what Stella actually does: things that do
not work yet say so in plain words. No em-dashes in this text
(Stella rule U33) and no bare ampersands (U11).
"""

from __future__ import annotations

TOPICS: list[tuple[str, str]] = [
    (
        "Getting started",
        """Stella fine-tunes small AI models on your own PC. A
fine-tune teaches a model a new skill by showing it examples.

The short path, first time:
1. Pick a model. Menu button, top left, then New Profile. Pick
   one from the list, or type a Hugging Face name like
   LiquidAI/LFM3-1.7B. That is the whole step.
2. Get the model's weights. Open the profile (double-click it in
   the left panel) and press Download model. It is a few gigabytes,
   so it takes a while. If it stops, press it again. It picks up
   where it left off.
3. Make a project. Menu, then New Project. A project is one
   fine-tune job: its own examples, settings, and results.
4. Set the dataset. In the project window, Dataset is the file of
   examples to learn from. To try it out, press Use sample dataset
   in the Train panel. The sample has 20 small examples.
5. Press Start training. Training on this PC takes hours, not
   minutes. The progress bar and the loss number show it working.
   You can pause and pick it up later.

You need the training packages installed once before training
works. If they are missing, Stella tells you to run this once in
the Stella folder: bash install-training.sh""",
    ),
    (
        "Chat",
        """Chat is the easy way to use Stella: talk to it, and it
does the work. Menu, then Chat. Say what you want in plain words,
for example: train LFM3 to write short replies. The chat asks
only for what it needs, sets everything else to the usual
settings, and runs the job.

The chat walks the same steps every training run needs, whatever
the model:
1. Goal. What should the model learn to do?
2. Base model. Which model to start from.
3. Data. The examples it learns from, or the sample dataset.
4. Settings. Rank, learning rate, epochs, batch size, sequence
   length. The defaults are fine for this PC.
5. Train. Run it. This takes hours on CPU.
6. Check. Validation loss and the refusal probe.
7. Export. A GGUF file and an Ollama model.
8. Test and back up. Try the tuned model, keep the export safe.

Say just do it and the chat runs the whole list with the defaults
and the sample dataset, telling you which step it is on.

The chat talks to a model you pick in Settings. It can be a model
on this PC through Ollama, or a cloud model: Groq or Gemini with
your own key. Add keys in Settings, under AI providers. Your keys
stay on this PC in a private file. They only leave the PC to talk
to that provider, and never appear in a debug report. Custom lets
you point the chat at any other service that works like OpenAI:
paste its address, key, and model name there.

How smart the chat is depends on which model you pick. A bigger
model answers better but slower. Pick the chat model in Settings,
or the chat asks you when you open it.

Honest limits: the chat can only do what Stella's engine does.
It cannot train a model that does not fit in 8 GB, it cannot make
training faster than the CPU allows, and if the chat model
misunderstands you, say it again in simpler words. It never
deletes anything: profiles and projects are only deleted from
their own windows.""",
    ),
    (
        "Picking a model",
        """A profile is one base model. The base is never changed:
training only ever makes a small add-on (an adapter) that sits on
top of it.

Good first pick: LFM3, the smallest model Stella is set up for
(1.7 billion parameters, about 3.5 GB to download). Type
LiquidAI/LFM3-1.7B when you make the profile.

You can also pick a model you already have in Ollama. Those show
up in the list when you make a profile. Note: an Ollama model is
for chatting, not for training. Training needs the Hugging Face
version of the same model, which is what Base ref points to. If
you picked an Ollama model and want to train it, open the profile
and set Base ref to its Hugging Face name.

Bigger models need more memory. This PC has 8 GB. Models around
1.5 to 2 billion parameters fit. An 8 billion parameter model does
not fit, and Stella will refuse rather than freeze your PC.""",
    ),
    (
        "Profiles",
        """A profile is one base model with its own home: its weights,
its settings, and its projects. The base model itself is never
touched.

The left panel lists your profiles. Click the arrow next to one
to see its projects. Double-click a profile to open its window.

The profile window has four things:
Display name. Just a label for the list.
Role. Only matters if Code Forge uses this profile as a seat
(driver, reviewer, and so on). Leave blank otherwise.
Ollama tag. The model as Ollama knows it on this PC. Used for
dreaming and the refusal probe.
Base ref. Where training loads the base model from: a Hugging
Face name like LiquidAI/LFM3-1.7B. Needed before you train.

The profile window also has the Download model button, which
pulls the base weights with a progress bar, and a Cancel button
while it runs.""",
    ),
    (
        "Projects",
        """A project lives inside a profile. It is one fine-tune job:
its own dataset, its own training settings, its own checkpoints,
and its own notes.

Click a project in the left panel and it becomes the training
session: the main window shows it, and Start training trains it.
Stella remembers the session and restores it next time you open
the program.

Double-click a project to open its window. The settings there are
explained under each box. The defaults are good for this PC, and
you can leave them alone:
LoRA rank 8. How big the adapter is.
Learning rate 0.0002. How big each training step is.
Epochs 3. How many full passes over the data.
Batch size 1. Examples per training step.
Max seq len 1024. Longest example, in tokens.

Method is always lora. Full fine-tuning would retrain the whole
model, which does not run on this PC, so that option is switched
off.

MetaMorphAi does nothing yet. The modes are stored but training
ignores them. Leave that setting alone for now.""",
    ),
    (
        "Training",
        """Training teaches the model from your examples. On this PC
it is slow: a small job takes hours. That is normal. The loss
number should fall as it goes. If it climbs or jumps around, the
learning rate may be too high.

Start, Pause, Resume are in the Train panel. Pause stops after
the current step and saves a checkpoint, so nothing is lost.
Resume picks up from the last checkpoint.

Your examples live in a dataset file. It must be JSONL: one
example per line, each line a JSON object with a prompt and a
completion, or a messages list. One format per file, at least 2
rows. Stella checks the file before training starts and names
the first problem it finds.

Training loads the base model plus the training tools into
memory. Stella checks the estimate first and refuses if it will
not fit in 8 GB, rather than freezing your PC.

When training finishes, the adapter is saved in the project
folder. It is small (tens of megabytes). The base model is
untouched. To use the tuned model in Ollama, export it as GGUF
(see GGUF export to Ollama).""",
    ),
    (
        "Sleep",
        """Sleep is for teaching a model new things without it
forgetting the old things.

Each sleep cycle trains a NEW small adapter on the examples added
since the last sleep. The base model and all earlier adapters stay
frozen. The cycle is checked before it is accepted: the new
adapter is tested on old examples as well as new ones. If the old
score gets worse by more than 10 percent, the cycle is flagged
DEGRADED. It is still saved, never silently passed.

Dream first (optional) asks your local Ollama model to write
extra practice examples, seeded from your real ones. Every dreamed
example is checked the same way real ones are, and dreamed rows
never outnumber real rows. If Ollama is down, dreaming is skipped
with a message and sleep still runs on real rows.

Honest limits: sleep trains with the same plain training as the
Train panel. There is no fancy reinforcement step on this PC, and
Ollama cannot run several adapters at once, so sleep adapters are
merged through the same GGUF export as everything else.""",
    ),
    (
        "Export and import",
        """Export packs a project into a folder you can keep, share,
or move to another PC. Menu, then Export project, and pick a
folder.

The package holds: the project record and settings, your notes,
the checkpoints, the sleep cycles, and the trained adapter if
there is one. The base model weights are not included. They are
gigabytes, and the other PC downloads them the same way you did.

Import brings a package back in. Menu, then Import package, and
pick the export folder. It creates the profile if it is not there
yet, and brings back the settings, notes, checkpoints, and sleep
cycles.

One honest gap: import does not put the trained adapter or the
probe results back into the project. They stay in the export
folder, in weights/ and probe_results.json. The project keeps its
"trained" status, but the adapter itself is not restored. If you
need the adapter on the new PC, copy the weights/ folder into the
project folder by hand and name it adapter/.""",
    ),
    (
        "The refusal probe",
        """The refusal probe checks whether tuning taught the model
to refuse things it used to answer. It runs 12 plainly harmless
prompts (coding help, plain questions) through the model before
and after tuning, and counts refusals each time.

Run refusal probe is in the Train panel. It loads the base model,
so it takes a few minutes on this PC.

The result is a rough check, not a guarantee. The refusal
detector looks for common refusal phrases, and it can be wrong
both ways: it can miss a real refusal, and it can flag a helpful
answer that happens to contain the word "cannot". Read the counts
as a signal, not a verdict.

For most projects the probe is information only. For a model
headed to a governing seat in Code Forge (a judge, a reviewer
with veto, a merger), a probe that shows refusals going up after
tuning is a stop sign.""",
    ),
    (
        "GGUF export to Ollama",
        """To use a tuned model in Ollama or Code Forge, export it as
a GGUF file. Export GGUF is in the Train panel.

It does three steps: it merges the adapter into the base model,
converts the result to GGUF format, and quantizes it to Q4_K_M
(4-bit, the size that runs well on this PC). Then it shows you
the exact ollama create command to run.

You need llama.cpp installed for the convert and quantize steps.
Stella checks for it first and tells you if it is missing. The
merge step needs several gigabytes of free disk for the merged
model; Stella cleans up the intermediate files when it is done.

The tuned model keeps the base model's name with the project
name added, so you can tell it apart in Ollama.""",
    ),
    (
        "Troubleshooting",
        """Stella is not answering, or a model is missing from the
list. Ollama may not be running. Start Ollama, then reopen the
profile window. The list refreshes each time the window opens.

Training packages missing. Run this once in the Stella folder:
bash install-training.sh. It downloads about 2 GB.

Weights missing. Open the profile and press Download model. If
Base ref is empty, set it to the Hugging Face name first, for
example LiquidAI/LFM3-1.7B.

Not enough disk. Model weights are gigabytes. Free space, then
download again. The download picks up where it left off.

Download stopped or froze. Press Download model again. The
Hugging Face hub resumes interrupted downloads, so nothing is
downloaded twice.

Learning rate must be a number. The learning rate box takes a
number like 0.0002, not words.

Something crashed or behaved oddly. Open Settings from the menu
and press Debug report. It writes a report file with the recent
log and the app's state, with any secrets scrubbed out. That file
is safe to share.""",
    ),
]


def topic_titles() -> list[str]:
    """The eleven topic titles, in order."""
    return [title for title, _ in TOPICS]


def topic_text(title: str) -> str | None:
    """The body text for one topic title, or None."""
    for topic_title, body in TOPICS:
        if topic_title == title:
            return body
    return None
