"""STELLA How to Use index: the built-in guide.

Thirteen topics, plain words, no jargon left unexplained. Every claim
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
1. Pick a model. File menu, then New Profile. Pick
   one from the list, or type a Hugging Face name like
   LiquidAI/LFM3-1.7B. That is the whole step.
2. Get the model's weights. Press Download model on the main
   screen. It is a few gigabytes, so it takes a while. If it
   stops, press it again. It picks up where it left off.
3. Make a project. Pick Train, then press Go: Stella asks for
   the project name as part of the job. A project is one
   fine-tune job: its own examples and results.
4. Set the dataset. In the project window, Dataset is the file of
   examples to learn from. To try it out, press Use sample dataset
   under Dataset on the main screen. The sample has 20 small examples.
5. Press Go. Training on this PC takes hours, not
   minutes. The loss curve and the numbers show it working.
   You can pause and pick it up later.

You need the training packages installed once before training
works. If they are missing, Stella tells you to run this once in
the Stella folder: bash install-training.sh""",
    ),
    (
        "Chat",
        """Chat is the easy way to use Stella: talk to it, and it
does the work. Help menu, then Chat. Say what you want in plain words,
for example: train LFM3 to write short replies. The chat asks
only for what it needs, sets everything else itself,
and runs the job.

The chat walks the same steps every training run needs, whatever
the model:
1. Goal. What should the model learn to do?
2. Base model. Which model to start from.
3. Data. The examples it learns from, or the sample dataset.
4. Recipe. Stella measures this PC and picks the training
   recipe. Nothing to set.
5. Train. Run it. This takes hours on CPU.
6. Check. Validation loss and the refusal probe.
7. Export. A GGUF file and an Ollama model.
8. Test and back up. Try the tuned model, keep the export safe.

Say just do it and the chat runs the whole list with the
sample dataset, telling you which step it is on.

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
        """A profile is one base model with its own home: its weights
and its projects. The base model itself is never touched.

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

The main window has the Download model button, next to the
model picker. It pulls the base weights with a progress bar,
and a Cancel button while it runs. If no Base ref is set, the
button is greyed out and a "Set the model source..." button
shows instead: it opens the profile window, where Base ref
gets set.""",
    ),
    (
        "Projects",
        """A project lives inside a profile. It is one fine-tune job:
its own dataset, its own checkpoints, and its own notes.

Click a project in the left panel and it becomes the training
session: the main window shows it. Pick Train and press Go to
train it. Stella remembers the session and restores it next time
you open the program.

Double-click a project to open its window. It holds the name,
the dataset, and your notes, each explained under its box.
Stella picks the training recipe for this PC itself: there is
nothing to set.""",
    ),
    (
        "Training",
        """Training teaches the model from your examples. On this PC
it is slow: a small job takes hours. That is normal. The loss
number should fall as it goes. If it climbs or jumps around,
check the examples: they may be mixed up, or too different from
each other.

Pick Train and press Go to start. Pause stops after the current
step and saves a checkpoint, so nothing is lost.
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
Train job. There is no fancy reinforcement step on this PC, and
Ollama cannot run several adapters at once, so sleep adapters are
merged through the same GGUF export as everything else.""",
    ),
    (
        "Export and import",
        """Export packs a project into a folder you can keep, share,
or move to another PC. File menu, then Export project, and pick a
folder.

The package holds: the project record, your notes,
the checkpoints, the sleep cycles, and the trained adapter if
there is one. The base model weights are not included. They are
gigabytes, and the other PC downloads them the same way you did.

Import brings a package back in. File menu, then Import package, and
pick the export folder. It creates the profile if it is not there
yet, and brings back the notes, checkpoints, sleep cycles, the
trained adapter (into the project's adapter folder), and the
refusal-probe results. A package that says the project finished
training but carries no weights imports as a draft instead, with a
warning. A project with no weights must not claim to be
finished.""",
    ),
    (
        "The refusal probe",
        """The refusal probe checks whether tuning taught the model
to refuse things it used to answer. It runs 12 plainly harmless
prompts (coding help, plain questions) through the model before
and after tuning, and counts refusals each time.

Run refusal probe is on the main screen, under the training
details. It loads the base model,
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
a GGUF file. Export GGUF is on the main screen, under the training
details.

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
        "Making a model smaller",
        """A model you already have in Ollama can be made smaller
and faster. This is called re-quantizing: the same weights,
packed tighter. A Q8_0 model at 2.7 GB becomes a Q4_K_M model
around 1.8 GB, and it runs faster because there is less to read
from memory.

Pick a model, pick Make smaller, and press Go. Stella makes the
smaller copy for you: a new model called qwen3.5:4b-q4-k-m, for
example. The original model is never touched: the smaller one
is a separate copy. The job runs as a card under the picker,
with a progress bar and a Cancel button.

Honest limits: re-quantizing a model that is already quantized
loses a little quality, because the weights get rounded twice.
The smaller model is a touch less sharp than the original. That
is the trade for the size and speed. And it does not remove
anything the model knows: it is the same model, smaller, not a
model with skills taken out. To make a model that only does
certain jobs, teach a small one instead (see Teaching a small
model).

You need llama.cpp installed for this step, the same tool the
GGUF export uses. Stella checks for it first and tells you if
it is missing.""",
    ),
    (
        "Teaching a small model",
        """Distillation is how you make a small model that only
does the jobs you want. A big teacher model answers a list of
prompts, and its answers become the training examples for a
small student model. The student learns only what it was taught.

First, make a plain text file with one prompt per line, the
jobs you want the small model to learn. Then pick a model, pick
Teach a small model, and press Go. Stella asks for the teacher
and the prompts file, then runs it. Or ask the Chat to do it for
you: it picks the teacher and the file itself. The job runs as
a card under the picker, with a progress bar and a Cancel
button.

Stella asks the teacher each prompt and saves the answers as
the project's dataset. Empty answers are skipped. If you stop
part way and run it again, it skips the prompts already
answered, so no teacher time is wasted.

Then train the student the usual way: pick Train and press Go
in the window.

Honest limits: the student is only as good as the teacher's
answers. A teacher that answers badly teaches badly, so look
at the dataset before you train. Distillation does not take
skills out of the teacher: the teacher is untouched. It makes
a new small model that knows the jobs you picked, and nothing
else.""",
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

Something crashed or behaved oddly. Open Settings from the File
menu and press Debug report. It writes a report file with the recent
log and the app's state, with any secrets scrubbed out. That file
is safe to share.""",
    ),
]


def topic_titles() -> list[str]:
    """The thirteen topic titles, in order."""
    return [title for title, _ in TOPICS]


def topic_text(title: str) -> str | None:
    """The body text for one topic title, or None."""
    for topic_title, body in TOPICS:
        if topic_title == title:
            return body
    return None
