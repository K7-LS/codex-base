---
name: understanding-map
description: Render an inspectable map of goals, assumptions, gaps and solution flow.
---

# understanding-map

Use when the user asks how Codex understood a consequential or ambiguous task,
or after a long clarification sequence. Skip trivial work.

## Build the map

1. Produce a small JSON document using `examples/sample_map.json`:
   - `ok` — confirmed facts;
   - `as` — assumptions requiring confirmation;
   - `pe` — unresolved gaps;
   - optional `flow`, `arch` and `stamp`.
2. Do not place secrets, personal data or untrusted raw HTML in the JSON.
3. Render deterministically:

```powershell
python "<skill-root>\tools\render_map.py" map.json `
  --mode standalone --out "<output>\understanding-map.html"
```

4. If a visualization capability is already available in the current Codex
   surface, the same JSON may also be rendered inline. Detect the capability
   from the active tool list; do not rely on a provider-specific environment
   variable and do not install a connector.
5. Ask the user to confirm or correct the assumptions before implementation.

The model creates only the structured content; `tools/render_map.py` owns HTML
generation. An inline widget and the standalone file must communicate the same
facts.
