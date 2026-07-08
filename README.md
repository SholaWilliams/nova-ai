<div align="center">

# ✦ NOVA

**A glass-walled AI assistant that shows you how it thinks.**

*Windows 11 · Python · PySide6 · Cloud LLMs (Gemini + Groq)*

</div>

---

NOVA is a desktop AI assistant built to teach children (ages 7–12) how modern AI agents actually work. It listens, reasons, chooses tools, executes real Windows actions, remembers, and speaks — and **every one of those stages is visualized live** in the interface.

> **The lesson:** AI does not magically perform actions. It reasons, chooses tools, executes them, then responds.

Unlike a chatbot, NOVA's "brain" is on display: watch it transcribe your voice, think, pick the Weather tool, call it, check the result, and compose its answer — every step lighting up as it truly happens. The visualization is driven by the same event stream as the logs; it *cannot* show something that didn't happen.

## What NOVA can do

| | |
|---|---|
| 🎙️ **Voice & typed conversation** | Push-to-talk speech recognition + neural text-to-speech (with full typed parity) |
| 🧰 **Real tools** | Calculator · Weather · App launcher · Browser · File search · Desktop organizer · Memory |
| 🧠 **Memory** | Remembers facts across restarts — and shows you exactly what it remembers |
| 🔍 **Pipeline visualization** | Every stage of every request, live and honest |
| 🛡️ **Safe by design** | The LLM never touches Windows — it only chooses tools; validated Python executes them. Anything that modifies files asks permission first. Move, never delete. |

## Project status

**📐 Documentation-first phase — no application code yet, by design.** The entire system is specified before implementation: vision, requirements, architecture, UI spec, agent design, tool specs, contracts, roadmap. Start at the **[documentation map](docs/00-documentation-map.md)**.

## Quickstart (once v1.0 ships)

1. Download `NOVA-vX.Y.Z-win64.zip` from [Releases], verify the checksum, unzip, run `NOVA.exe` (SmartScreen: *More info → Run anyway* — builds are unsigned).
2. On first run, follow the in-app guide to add free API keys (Google Gemini + Groq).
3. Press the mic and say *"What's the weather?"* — then watch the pipeline.

**Requirements:** Windows 11 x64 · internet connection · microphone/speakers for voice (typed mode works without).

## For developers

NOVA doubles as a reference implementation of a clean, modular, tool-based agent architecture — small enough to read end-to-end.

- [Developer guide](docs/guides/developer-guide.md) — setup, tour, add your own tool in under an hour
- [System architecture](docs/03-system-architecture.md) · [API contracts](docs/11-api-contracts.md) · [Contributing](CONTRIBUTING.md)
- [Troubleshooting](docs/guides/troubleshooting.md)

## License & credits

License: MIT (proposed — confirm before first release). Fonts: Inter, JetBrains Mono (OFL) · Icons: Lucide (ISC) · Weather: Open-Meteo.
