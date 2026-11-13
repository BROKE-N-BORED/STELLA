# Sample dataset

`sample-tool-calls.jsonl` — 20 synthetic examples in the Forge
tool-call trace shape, so the proof loop runs without real data.

- 14 examples teach the tool-call habit: a user asks for something
  that needs a tool, and the assistant answers with exactly one
  `<tool_call>{...}</tool_call>` block naming a Forge-style tool
  (`run_shell`, `read_file`, `write_file`, `search_code`) with its
  arguments as JSON. No fenced code blocks, no chatter around the
  call — the exact failure the Qwen2.5-Coder audit found was a model
  emitting bare fenced JSON as chat text instead of a structured call.
- 6 examples are plain answers with no tool call, so the model does
  not learn to call a tool for every question.

To use it: set a project's dataset to `sample-tool-calls.jsonl`
(the Train panel's "Use sample dataset" button does this), or pass
it to the CLI: `stella train lfm3-tool tool-calls`.

To replace it with real Forge traces: write one JSON object per line,
either `{"prompt": ..., "completion": ...}` or `{"messages": [...]}`,
and point the project at that file. Stella validates the file before
training starts and names the exact line of any bad row.
