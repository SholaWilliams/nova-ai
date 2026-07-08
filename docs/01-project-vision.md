# NOVA — Project Vision

| | |
|---|---|
| **Document** | Phase 1 — Project Vision |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Owner** | Project Lead |
| **Last updated** | 2026-07-08 |
| **Depends on** | — (root document) |
| **Feeds into** | Phase 2 (PRD), Phase 3 (Architecture), all subsequent phases |

---

## 1. Executive Summary

**NOVA** is a modern desktop AI assistant for Windows 11, built in Python with PySide6 and powered by cloud LLMs. It listens, reasons, selects tools, executes real Windows actions, remembers information, and speaks its responses.

NOVA is **primarily an educational instrument**. Its defining feature is not any single capability but its **transparency**: every stage of the AI pipeline — listening, understanding, reasoning, tool selection, execution, memory, and speech — is visualized live in the interface. A child watching NOVA work should be able to answer the question: *"What is the AI doing right now, and why?"*

The core message NOVA exists to teach:

> **"AI does not magically perform actions. It reasons, chooses tools, executes them, then responds."**

NOVA is not another chatbot. It is a glass-walled AI agent: polished enough that developers admire it, simple enough that a 7-year-old can follow it.

---

## 2. Mission

Build a polished, futuristic desktop AI assistant that **demonstrates — visibly and live — how modern AI agents work**, by exposing every step of the perceive → reason → act → remember → respond loop, while performing genuinely useful actions on a real Windows machine.

---

## 3. The Problem NOVA Addresses

1. **AI literacy gap.** Children (and many adults) experience AI as magic: text goes in, answers come out. They have no mental model for *how* an agent decides and acts. This produces both unrealistic fear and unrealistic trust.
2. **Chatbots hide the interesting part.** Commercial assistants deliberately conceal their internals. The reasoning, the tool choice, the execution — the parts that actually explain AI agency — are invisible.
3. **Educational demos are usually toys.** Most "AI for kids" material is either a slideshow or a scripted illusion. There is a shortage of *real*, working, inspectable agents suitable for a live classroom demonstration.

NOVA answers all three: a real agent, doing real things, with the walls made of glass.

---

## 4. Vision Statement

> By the time a child has watched NOVA handle five requests, they should be able to explain — in their own words — that an AI assistant *hears*, *thinks*, *picks a tool*, *uses the tool*, *remembers*, and *answers*. By the time a developer has read the codebase, they should consider it a reference implementation of a clean, modular, tool-based agent architecture.

Two audiences, one artifact:

- **For learners (7–12, extendable to teens):** a friendly, animated, talking assistant whose "brain" is visible.
- **For developers:** an open-source-quality, modular, documented Python agent framework they can study and extend.

---

## 5. Product Pillars

Every design decision in later phases must be defensible against these five pillars:

| # | Pillar | Meaning |
|---|--------|---------|
| P-1 | **Transparency over magic** | Every processing stage is visible in the UI, in real time, in child-comprehensible language. Nothing important happens invisibly. |
| P-2 | **Tools, not tricks** | Every capability is a discrete Tool. The LLM never touches Windows; it only *chooses*. Python executes. This separation is architectural, not cosmetic. |
| P-3 | **Modular by construction** | One module, one responsibility. Tools, providers, speech engines, and memory stores are pluggable behind interfaces. |
| P-4 | **Polish is pedagogy** | Smooth animation, a coherent futuristic dark theme, and responsive feedback are not decoration — they hold a child's attention long enough to teach. |
| P-5 | **Runs on real, modest hardware** | 16 GB RAM, no discrete GPU, ~2 GHz CPU. Cloud LLMs only; anything local must be lightweight. |

---

## 6. Goals

### Primary Goals

| ID | Goal |
|----|------|
| G-1 | Deliver a working Windows 11 desktop assistant supporting both **voice and typed** conversation. |
| G-2 | Implement a **tool-based agent loop**: the LLM plans and selects tools; Python validates and executes them; results feed back into the response. |
| G-3 | Provide a **live pipeline visualization** showing each stage (listening → transcribing → thinking → tool selection → executing → remembering → speaking) as it happens. |
| G-4 | Ship an initial toolset covering real utility: desktop organization, browser control, app launching, calculator, weather, file search, and memory. |
| G-5 | Implement **persistent memory**: conversation history, long-term facts, and user preferences that survive restarts. |
| G-6 | Provide **speech in and speech out**: speech recognition for input, text-to-speech for responses. |
| G-7 | Present a **futuristic, dark-themed, animated UI** (pulse ring, status indicators, smooth transitions) that is professional in quality and child-friendly in comprehension. |
| G-8 | Architect for **extension**: adding a new Tool or a new LLM provider must require no changes to core agent code. |

### Secondary Goals

| ID | Goal |
|----|------|
| G-9 | Produce documentation of open-source quality: architecture, contributing guide, API docs, AI-agent assets (CLAUDE.md etc.). |
| G-10 | (Deferred track) Produce a teaching guide and presentation script enabling a live classroom demonstration for ages 7–12 / teens. |
| G-11 | Keep the codebase small and readable enough to be studied end-to-end by an intermediate Python developer. |

---

## 7. Success Criteria

Success criteria are measurable and testable. They become acceptance anchors in the PRD (Phase 2) and the testing strategy (Phase 13).

### Functional

| ID | Criterion | Measure |
|----|-----------|---------|
| SC-1 | End-to-end voice loop works | User speaks a request → NOVA transcribes, reasons, executes, and speaks a response, with no keyboard use. |
| SC-2 | Pipeline is always visible | For every request, each pipeline stage lights up in the UI in the correct order and with a human-readable label. |
| SC-3 | Tool execution is real | At minimum: NOVA can open an application, perform a calculation, report the weather, find a file, control the browser, tidy the desktop, and store/recall a memory — on a stock Windows 11 machine. |
| SC-4 | Memory persists | A fact told to NOVA ("my favorite color is blue") is recalled correctly after a full application restart. |
| SC-5 | Typed mode is first-class | Every capability available by voice is also available by typing. |
| SC-6 | Graceful degradation | If the microphone, speakers, or a specific tool fails, NOVA reports the failure conversationally and remains usable. |

### Non-Functional

| ID | Criterion | Measure |
|----|-----------|---------|
| SC-7 | Responsiveness | UI never freezes; all speech, network, and tool work runs off the UI thread. Perceived response start (first visible pipeline activity) < 1 s after end of user input. |
| SC-8 | Hardware fit | Steady-state RAM use of the app (excluding OS) ≤ 1.5 GB; runs acceptably with no discrete GPU on a ~2 GHz CPU. |
| SC-9 | Extension cost | A competent Python developer can add a new Tool (spec → code → registered → usable) in under one hour using only the documentation. |
| SC-10 | Provider swap | Switching the active LLM provider (e.g., Gemini ↔ Groq) requires a settings change only — zero code changes. |

### Educational

| ID | Criterion | Measure |
|----|-----------|---------|
| SC-11 | The core message lands | After a demo, children can articulate (in their own words) that the AI *chose a tool* rather than "just did it." Verified via the teaching guide's comprehension questions (Phase 15). |
| SC-12 | Stage vocabulary sticks | Children can name at least three pipeline stages (e.g., "listening," "thinking," "using a tool") after one session. |
| SC-13 | Demo reliability | A scripted 15-minute demo (Phase 16) completes without unrecoverable failure, including a rehearsed fallback path for internet loss. |

---

## 8. Non-Goals

Explicitly out of scope. Each has a rationale so future scope debates can be settled by reference.

| ID | Non-Goal | Rationale |
|----|----------|-----------|
| NG-1 | **Being a general-purpose chatbot** | Open-ended chat is allowed as a fallback, but the product's identity is the visible agent loop. Features that don't reinforce the pipeline story are deprioritized. |
| NG-2 | **Local LLMs** | Hardware constraints (no GPU, 16 GB RAM) make local models slow and pedagogically counterproductive (long waits lose children). Cloud only. Local *speech* components remain a Phase 8 decision. |
| NG-3 | **Cross-platform support (macOS/Linux)** | Windows-specific tools (desktop organization, app launching) are core. Abstracting the OS layer now would triple complexity. Architecture may *permit* future porting but must not pay for it. |
| NG-4 | **Autonomous/unattended operation** | NOVA acts only on explicit user requests. No background agency, no scheduled autonomous actions. This is both a safety stance and the honest version of the educational message. |
| NG-5 | **Destructive actions without confirmation** | No file deletion, no system settings changes, nothing irreversible without an explicit user confirmation step. Child-facing software; classroom machines. |
| NG-6 | **Multi-user / cloud accounts / telemetry** | Single local user. No sign-in, no analytics, no data leaving the machine except LLM/STT/weather API calls. |
| NG-7 | **Mobile or web versions** | Desktop-native is the product. |
| NG-8 | **Production-grade commercial hardening** | NOVA is educational open source, not an enterprise product. Security and robustness are taken seriously, but SLAs, auto-update infrastructure, and enterprise deployment are out of scope. |
| NG-9 | **Simulated/faked demos** | The pipeline visualization must reflect what is actually happening. No pre-scripted fake reasoning. (Cached/offline fallback for demos is allowed but must be labeled as such in presenter materials.) |

---

## 9. Educational Objectives

Target audience: **children ages 7–12**, extendable to teens. Each objective maps to a product feature that makes it observable — the curriculum is built into the UI.

| ID | Learning objective | The child can… | Made visible by |
|----|--------------------|----------------|-----------------|
| EO-1 | **Agents follow a loop** | Name the stages: listen → think → choose tool → act → remember → speak. | Pipeline visualization (G-3) |
| EO-2 | **AI reasons before acting** | Explain that the assistant "thought about" the request before doing anything. | "Thinking" stage with a child-readable summary of the plan |
| EO-3 | **Capabilities are tools** | Say which tool the AI picked and why ("it used the calculator because I asked a math question"). | Tool-selection stage displaying the chosen tool's name and icon |
| EO-4 | **The AI doesn't touch the computer — the program does** | Articulate the separation: the AI *chooses*, the computer program *does*. | Distinct "AI decided" vs. "Executing on your PC" stages |
| EO-5 | **AI has memory, and memory is stored data** | Show that the assistant remembers a fact, and understand it's saved information, not mind-reading. | Memory stage indicator + a viewable "What NOVA remembers" panel |
| EO-6 | **Speech is recognition + synthesis, not understanding sound magically** | Explain that their voice becomes text before the AI reads it. | Live transcription display during the listening stage |
| EO-7 | **AI can be wrong and can fail safely** | Observe an error, see NOVA explain it, and understand failure is normal and handled. | Conversational error reporting (SC-6), error state in the pipeline |
| EO-8 | **Healthy skepticism** | Understand the AI is a program following instructions — impressive, not alive. | Teaching guide framing (Phase 15) reinforced by the transparent UI |

---

## 10. Project Scope

### 10.1 In Scope — Version 1.0

**Conversation & Speech**
- Typed conversation with full chat history
- Voice conversation: speech-to-text input, text-to-speech output
- Voice activity handling (start/stop of listening clearly indicated)

**Agent Core**
- Cloud LLM reasoning (multi-provider: initially Gemini and Groq, behind a provider abstraction)
- Tool selection via structured tool-calling
- Tool registry with schema-validated inputs/outputs
- Conversational error recovery

**Tools (initial set)**
- Desktop organization (safe, non-destructive tidying)
- Browser control (open sites, searches)
- Application launcher
- Calculator
- Weather
- File search
- Memory (store/recall facts and preferences)

**Memory**
- Conversation history (persistent)
- Long-term facts and user preferences (JSON-backed)

**UI**
- Futuristic dark theme, animated pulse ring, smooth transitions
- Live pipeline visualization of every processing stage
- Chat history view, status indicators, settings screen
- "What NOVA remembers" viewer

**Engineering**
- Modular architecture with documented internal APIs
- Full documentation suite + AI-agent engineering assets
- Test strategy across unit / integration / UI / acceptance levels
- Packaged Windows distribution

### 10.2 Deferred — Post-1.0 (documented now, built later)

- Wake-word activation ("Hey NOVA") — specified in Phase 8, implementation deferred
- Offline speech fallback — Phase 8 future section
- Vector-database memory retrieval — Phase 9 future section
- Additional tools (per Phase 7 "Future Tools" section)
- Additional LLM providers beyond the initial two
- Teaching guide & presentation script (Education Track — after Build Track)

### 10.3 Out of Scope (see Non-Goals)

Local LLMs, cross-platform support, autonomy, multi-user, mobile/web, telemetry, destructive unconfirmed actions.

### 10.4 Constraints (binding on all later phases)

| Constraint | Value |
|-----------|-------|
| OS | Windows 11 |
| Language | Python |
| UI framework | PySide6 |
| LLM | Cloud providers only |
| RAM budget | ≤ 1.5 GB app steady-state (16 GB machine) |
| GPU | None assumed |
| CPU | ~2 GHz, modest core count |
| Storage | Modest footprint; ~46 GB free on target machine |
| Network | Required for LLM/weather; app must fail gracefully without it |

---

## 11. Guiding Design Philosophy

Restated from the project charter; every later phase inherits these rules:

1. **Everything is modular.** One module, one responsibility.
2. **Every capability is a Tool.** No special cases smuggled into the core.
3. **The AI never touches Windows.** The LLM emits *decisions* (structured tool calls). Python code validates and executes them. The boundary is absolute.
4. **The pipeline is honest.** The visualization shows what is genuinely happening — it is instrumentation, not theater.
5. **Documentation before implementation.** Code is written only against approved specifications.

---

## 12. Glossary

| Term | Definition |
|------|------------|
| **Agent** | The reasoning core: receives user intent, plans, selects tools, composes responses. |
| **Tool** | A discrete, schema-defined capability executed by Python (e.g., Calculator, Weather). The only mechanism by which NOVA acts on the world. |
| **Pipeline** | The visible sequence of processing stages for one request: listen → transcribe → think → select tool → execute → remember → speak. |
| **Provider** | A cloud LLM backend (e.g., Gemini, Groq) behind a common interface. |
| **STT / TTS** | Speech-to-text (recognition) / text-to-speech (synthesis). |
| **Memory** | Persistent stored information: conversation history, long-term facts, preferences. |
| **Tool Registry** | The catalog of available tools, their schemas, and metadata, presented to the LLM and used to validate calls. |

---

## 13. Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 1 review. |

---

## 14. Phase 1 Exit — Review Checklist

- [ ] Mission and vision reflect the intended product identity (educational, transparent, not a chatbot)
- [ ] Goals G-1…G-11 are complete and correctly prioritized
- [ ] Success criteria SC-1…SC-13 are measurable and agreed
- [ ] Non-goals NG-1…NG-9 are agreed (especially NG-4 autonomy and NG-5 confirmations)
- [ ] Educational objectives EO-1…EO-8 match the intended audience
- [ ] Scope split (v1.0 / deferred / out) is agreed
- [ ] Constraints table is accurate for the target hardware

**On approval → Phase 2: Product Requirements Document.**
