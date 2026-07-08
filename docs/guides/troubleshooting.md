# NOVA — Troubleshooting

First stop for anything broken. Logs live at `%APPDATA%\NOVA\logs\nova.log` (Settings → About → *Open logs folder*).

## Users & presenters

| Symptom | Likely cause | Fix |
|---|---|---|
| "I can't reach my brain right now" | No internet, or both providers down | Check network; Settings → Brain → *Test* each key; status bar shows which provider is active |
| Red banner: API key missing/invalid | Key not set, typo, or revoked | Settings → Brain → paste key → *Test*. Keys are free: follow the in-app links |
| Mic button struck through | No mic, or Windows denied access | Windows Settings → Privacy → Microphone → allow desktop apps; then NOVA Settings → Voice → pick device → *Mic test* |
| NOVA hears me wrong | Noisy room / soft voice | Get closer to the mic; the transcript always shows *before* NOVA acts — cancel and retry, or type instead |
| Voice sounds robotic + "Voice: offline" | edge-tts unreachable → offline fallback voice | Normal offline behavior; returns to the neural voice when network is back |
| No sound at all | Wrong output device / TTS muted | Settings → Voice: check device + TTS toggle; speaker icon in a reply bubble replays nothing — it only stops speech |
| Windows SmartScreen blocks launch | Unsigned build (expected) | *More info → Run anyway*; verify the SHA256 from the release page first |
| App opens but looks frozen mid-request | One-request-at-a-time rule | Wait for the pipeline to finish or press Esc to cancel |
| Demo day: internet is gone | — | Typed mode + offline voice still work for conversation about stored memories; follow the Phase 16 offline script |
| Reset NOVA between classes | — | Memory view → *Forget everything* (check "also clear conversations"); Settings are kept |

## Developers

| Symptom | Fix |
|---|---|
| `lint-imports` fails | You crossed a layer boundary (D-1…D-7). Move the code, don't silence the contract — see [architecture §6](../03-system-architecture.md) |
| pytest-qt tests hang locally | Set `QT_QPA_PLATFORM=offscreen`; ensure no real `QApplication` leaks between tests |
| PyInstaller build missing DLLs/plugins | Use the committed `nova.spec` (has PySide6 hooks); rebuild in a clean venv from the lockfile |
| `webrtcvad` install fails | Use `webrtcvad-wheels` (TD-7), not `webrtcvad` |
| edge-tts suddenly erroring everywhere | Upstream endpoint changed (known risk TD-6). App auto-falls back to pyttsx3; check for an `edge-tts` package update, else pin the last working version and file an issue |
| Provider works in tests, fails live | Golden fixtures may be stale vs API changes — re-record with `pytest -m record` (your keys) and diff |
| RAM climbing across requests | Run the leak-trend test (`tests/unit/test_memory_trend.py`); usual suspects: event subscribers never unsubscribed, QPixmap caches |
| Where do I ask? | Open a GitHub issue with the log excerpt (keys are never logged — safe to paste) |
