# NOVA — UI/UX Design Specification

| | |
|---|---|
| **Document** | Phase 5 — UI/UX Design Specification |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | Phase 2 (FR-35…FR-45, NFR-9/10), Phase 3 (UI flow §12, stages §7.1) |
| **Feeds into** | Phase 12 (UI tasks), `src/nova/ui/theme.py`, `assets/styles/` |

---

## 1. Design Language — "Glass Cockpit"

NOVA's UI is the cockpit of a friendly spaceship: dark, calm, luminous. Information glows into view; nothing jumps. Two rules govern every screen:

1. **The pipeline is the hero.** The most visually alive element is always the stage rail — because that's the lesson (P-1).
2. **Calm by default, glow when active.** Idle NOVA breathes slowly; activity is shown by light, not by motion clutter (P-4, NFR-9).

---

## 2. Color Palette (design tokens)

All colors ship as tokens in `theme.py` / QSS variables. Dark theme only in v1.0 (FR-41).

| Token | Hex | Usage |
|-------|-----|-------|
| `bg.base` | `#0A0E1A` | App background (deep space navy) |
| `bg.surface` | `#111827` | Cards, panels, input bar |
| `bg.raised` | `#1A2332` | Hovered surfaces, active chips |
| `stroke.subtle` | `#233046` | Hairline borders, dividers |
| `accent.primary` | `#22D3EE` | Cyan — NOVA's signature: pulse ring, active stage, links, focus |
| `accent.secondary` | `#8B5CF6` | Violet — thinking/reasoning states, agent-related accents |
| `state.success` | `#34D399` | Completed stages, success toasts |
| `state.warning` | `#FBBF24` | Degraded (fallback provider, offline TTS) |
| `state.error` | `#F87171` | Error stage, failed status |
| `text.primary` | `#E5E7EB` | Main text (≥ 4.5:1 on all surfaces — AA) |
| `text.secondary` | `#94A3B8` | Labels, timestamps, hints |
| `text.inverse` | `#0A0E1A` | Text on accent fills |
| `bubble.user` | `#1E3A5F` | User message fill |
| `bubble.nova` | `#161F32` | NOVA message fill (+1 px `accent.primary` @ 25 % border) |

Accent color is user-adjustable in Settings (FR-44) from a fixed set of 4 (cyan, violet, emerald, amber) — all pre-verified for AA contrast.

## 3. Typography

| Role | Font | Size / weight | Usage |
|------|------|--------------|-------|
| Display | Inter | 24 px / 700 | Screen titles, big state word ("Listening…") |
| Body | Inter | 15 px / 400 | Chat messages (children read these — generous size) |
| Label | Inter | 13 px / 500, +2 % tracking | Stage chips, buttons, status bar |
| Caption | Inter | 12 px / 400 | Timestamps, hints |
| Mono | JetBrains Mono | 14 px / 400 | Live transcript, calculator expressions, tool args in detail view |

Line height 1.5 for body. Minimum body size never below 14 px (NFR-9). Fonts bundled from `assets/fonts/` (TD-14).

## 4. Spacing, Shape, Elevation

- **4 px base grid.** Spacing tokens: `xs 4 · sm 8 · md 16 · lg 24 · xl 32 · xxl 48`.
- **Radii:** chips 8 px · cards/bubbles 12 px · input bar 16 px · pulse ring circular.
- **Elevation:** flat design; depth via 1 px strokes + soft outer glow (`accent @ 20%`, blur 24) on *active* elements only. No drop-shadow stacks (GPU-less machine, FR-45).

## 5. Iconography

Lucide SVG, 20 px default, 1.75 px stroke, `text.secondary` tint (active: `accent.primary`).

| Concept | Icon | Concept | Icon |
|---------|------|---------|------|
| Calculator tool | `calculator` | Weather tool | `cloud-sun` |
| App launcher | `rocket` | Browser tool | `globe` |
| File search | `file-search` | Desktop organizer | `layout-grid` |
| Memory tool | `brain` | Listening | `mic` |
| Thinking | `sparkles` | Executing | `zap` |
| Remembering | `bookmark` | Speaking | `volume-2` |
| Confirmation | `shield-question` | Error | `alert-triangle` |
| Network ok/off | `wifi` / `wifi-off` | Provider | `cpu` |
| Settings | `settings` | History | `history` |

---

## 6. Screen Inventory & Layouts

### 6.1 Main Window (default 1200×760, min 980×640)

```
┌────────────────────────────────────────────────────────────────────┐
│  ◉ NOVA          ● online · Gemini · 🎤 ready          ⌂ 🕘 🧠 ⚙   │  ← Header (56px)
├───────────────────────────────────┬────────────────────────────────┤
│                                   │        PIPELINE PANEL          │
│           CHAT VIEW               │  ┌──────────────────────────┐  │
│                                   │  │       (  pulse  )        │  │
│  ┌──────────────────────────┐     │  │        (  ring  )        │  │
│  │ You: What's the weather  │     │  │       "Thinking…"        │  │
│  │      in Lagos?       9:41│     │  └──────────────────────────┘  │
│  └──────────────────────────┘     │                                │
│     ┌──────────────────────────┐  │  ● Listening        ✓ 0.8s    │
│     │ NOVA: It's 31° and       │  │  ● Understanding    ✓ 0.4s    │
│     │ sunny in Lagos! ☀️   9:41│  │  ● Thinking         ✓ 1.2s    │
│     └──────────────────────────┘  │  ● Choosing a tool  ✓ 🌤️Weather│
│                                   │  ● Doing it         ✓ 0.6s    │
│                                   │  ● Remembering      ─ skipped │
│                                   │  ● Speaking         ◉ now     │
├───────────────────────────────────┴────────────────────────────────┤
│  [ 🎤 ]   Type or press the mic to talk…                    [Send] │  ← Input bar (64px)
└────────────────────────────────────────────────────────────────────┘
```

- **Split:** chat 60 % / pipeline 40 %; divider draggable; pipeline collapsible (presenter may want full-screen chat — persisted preference).
- **Header:** logo-dot pulses subtly with app state; status cluster (FR-43): network, provider name, mic; nav buttons: Home, History, Memory, Settings.
- **Input bar:** mic button (64 px hit target — child fingers), text field, Send. Enter submits; Esc cancels listening.

### 6.2 Pipeline Panel (the hero — FR-35…FR-40)

- Top: **Pulse Ring** (§7.1) with the current stage word beneath in Display type.
- Below: **Stage Rail** — vertical list of `StageChip`s in fixed pipeline order with connecting line. Chips: label + status icon + (after completion) duration + detail string (e.g., tool name + icon at "Choosing a tool" — FR-37).
- After completion the rail stays populated until the next request (FR-40); clicking a chip expands its plain-language detail (`PipelineEvent.detail`).
- **Skipped** chips render dimmed with a "—" and the label struck through lightly (FR-38): visible but visibly not-taken.

### 6.3 Settings View (FR-44)

Sections (single scrolling page, left icon rail): **Brain** (provider pick, API keys with show/hide + "Test" button per key), **Voice** (TTS on/off, voice choice, input/output device dropdowns, mic test meter), **Weather** (default city), **Look** (accent color, reduced motion), **About**. Keys display masked; a red banner appears at top when keys are missing/invalid (FR-47) with a "Fix now" link.

### 6.4 Memory View (FR-32, FR-33)

"**What NOVA remembers**" — card list: memory text in Body, created date in Caption, kind badge (`fact`/`preference`), per-card delete (trash icon → confirm), header "Forget everything" (danger-styled, confirm dialog). Empty state: friendly illustration + "I don't remember anything yet. Tell me something to remember!"

### 6.5 History Drawer (FR-5, FR-6)

Right-side drawer listing sessions (date + first user message). Selecting loads that transcript read-only into Chat View with a "Back to today" pill. "New conversation" button on top.

### 6.6 Confirmation Dialog (FR-20)

Modal, `shield-question` icon in accent, title "**May I?**", body = plain-language action preview (for Desktop Organizer: scrollable list of planned moves — FR-26), buttons **"Yes, do it"** (accent fill) / **"No, stop"** (ghost). Esc = No. The pipeline shows `AWAITING_CONFIRMATION` ("Asking your permission") while open.

---

## 7. Widget Specifications

### 7.1 PulseRing (FR-42)

Custom `QPainter` widget, 160 px, concentric rings around a soft-glow core.

| State | Animation | Color | Params |
|-------|-----------|-------|--------|
| Idle | slow breathe (scale 0.96→1.0) | accent @ 60 % | 3 s loop, InOutSine |
| Listening | outward ripples (2 rings) + core tracks mic level | `accent.primary` | ripple 1.2 s; level→core radius ±8 px |
| Thinking | rotating 270° arc | `accent.secondary` | 1.6 s/rev, linear |
| Executing | fast double-pulse | `accent.primary` | 0.5 s ×2, then hold |
| Speaking | amplitude pulsation (waveform feel) | `accent.primary` | driven by playback chunks |
| Error | two quick flashes then dim | `state.error` | 0.15 s ×2 |

Implementation: one `QVariantAnimation` driving a phase float; `paintEvent` derives geometry — no per-frame allocations (FR-45).

### 7.2 StageChip

States: `pending` (dim stroke, gray text) → `active` (accent glow border, label bold, 3-dot micro-anim) → `done` (success check + duration) / `skipped` (dimmed, "—") / `failed` (error tint + `alert-triangle`). Transition: 250 ms color/glow crossfade. Height 40 px; full-width in rail.

### 7.3 MessageBubble

User right-aligned (`bubble.user`), NOVA left (`bubble.nova` + accent hairline). Max width 72 % of chat pane. Entry animation: 12 px rise + fade, 250 ms OutCubic. NOVA text reveals with the TTS start (text appears at once — no fake typewriter, NG-9 spirit). While NOVA speaks, a small `volume-2` glyph pulses in the bubble corner; clicking it stops speech (FR-13).

### 7.4 Status cluster · Input bar · Toasts

- Status items: icon + label, `state.warning` tint when degraded (e.g., "Groq (fallback)" — US-14), tooltip with detail.
- Mic button: idle = outline mic; listening = filled + ring ripple + red recording dot; disabled (no mic) = struck-through with tooltip.
- Toasts: bottom-center, surface bg, auto-dismiss 4 s, used only for non-conversational notices (settings saved, provider switched).

---

## 8. Motion System

| Token | Duration | Easing | Used for |
|-------|----------|--------|----------|
| `motion.fast` | 150 ms | OutCubic | hovers, presses, focus rings |
| `motion.base` | 250 ms | OutCubic | chips, bubbles, panel reveals |
| `motion.slow` | 400 ms | InOutCubic | view transitions, drawer |
| `motion.breathe` | 3 s | InOutSine | idle pulse |

Rules: max 2 concurrently animated properties per widget; no animation on layout-affecting properties during streaming; all loops via one shared ticker where possible. **Reduced motion** setting (§10) swaps loops for static state colors. Performance budget: 60 fps target, 30 fps floor on reference CPU (FR-45) — verified by the Phase 13 perf check.

## 9. UI Copy Guidelines (child-facing)

- Second person, present tense, ≤ 10 words per stage detail. No jargon: "tool", "remember", "thinking" — never "API", "LLM", "executing" in child-visible copy ("Doing it on your PC" not "Executing tool").
- Errors are honest and blame-free: "I can't reach my brain right now — is the internet on?" (FR-46).
- NOVA says "I" and refers to itself as a computer program when asked (EO-8 alignment).
- Full stage label ↔ enum mapping lives in Phase 3 §7.1 and is the single source for copy.

## 10. Accessibility (NFR-9, NFR-10)

- **Contrast:** all text tokens ≥ 4.5:1 on their surfaces (verified in tokens table); status never conveyed by color alone (icons + labels).
- **Keyboard:** Tab order: input field → mic → send → nav; `Ctrl+M` toggle mic, `Ctrl+,` settings, `Esc` cancel/close. Visible 2 px accent focus ring on all interactives.
- **Captions:** everything spoken is on-screen text (FR-9); live transcript shown during listening (FR-8).
- **Reduced motion:** setting disables loops/ripples (respects Windows "Show animations" too).
- **Hit targets:** ≥ 40 px for child-facing controls (mic 64 px).

## 11. State Transition Map (UI ↔ pipeline)

| UI state (Phase 3 §12) | Pulse ring | Stage rail | Input bar |
|---|---|---|---|
| IDLE | Idle breathe | last run visible (FR-40) | enabled |
| LISTENING | Listening | Listening chip active; live transcript under input | mic = stop |
| PROCESSING | Thinking/Executing | chips progress in real order (FR-36) | disabled + "one moment" hint |
| AWAITING_CONFIRMATION | Executing (held) | "Asking your permission" active | modal open |
| SPEAKING | Speaking | Speaking chip active | enabled (new input stops speech) |
| ERROR | Error flash | failed chip + friendly detail | enabled |

---

## 12. Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 5 review. |

**Exit check:** palette/typography/motion tokens final enough to code `theme.py`; every FR-35…FR-45 requirement has a concrete visual answer; copy rules aligned with the educational objectives.
