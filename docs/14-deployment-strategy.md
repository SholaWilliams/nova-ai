# NOVA — Deployment Strategy

| | |
|---|---|
| **Document** | Phase 14 — Deployment Strategy |
| **Status** | Ready for review |
| **Version** | 1.0.0 |
| **Last updated** | 2026-07-08 |
| **Depends on** | Phase 4 (TD-13), Phase 11 (§5 settings), Phase 13 (release gates) |
| **Feeds into** | Phase 20 (release strategy), `scripts/build_release.ps1` |

---

## 1. Packaging

- **PyInstaller one-folder** (TD-13) via a committed `.spec`: entry `nova/__main__.py`, PySide6 hooks, bundled `assets/` (fonts, icons, sounds, QSS), app icon, version stamped from the git tag into `nova/_version.py` at build time.
- Distribution artifact: `NOVA-v{X.Y.Z}-win64.zip` (the one-folder dir zipped) + `SHA256SUMS.txt`, attached to a GitHub Release. No installer in v1.0 (NG-8); unzip-and-run with a `NOVA.exe` at the folder root.
- **Unsigned binaries caveat:** SmartScreen will warn. README/Release notes include the "More info → Run anyway" guidance and the checksum verification step. Code signing is a post-1.0 cost decision.
- Build entry: `scripts/build_release.ps1` — clean venv from lockfile → run full test suite → `pyinstaller nova.spec` → smoke `--self-check` (Phase 13 §7) → zip + checksums.

## 2. Configuration & Environment

Runtime data root: `%APPDATA%\NOVA\` (created on first run):

```
%APPDATA%\NOVA\
├── settings.json      # Phase 11 §5 schema
├── .env               # secrets (written by Settings UI, 600-style intent)
├── memory\  conversations\  logs\
```

| Env var | Purpose |
|---|---|
| `NOVA_GEMINI_API_KEY` / `NOVA_GROQ_API_KEY` | provider + STT keys |
| `NOVA_DATA_DIR` | override data root (tests, portable mode) |
| `NOVA_LOG_LEVEL` | `DEBUG`…`ERROR` (default `INFO`) |
| `NOVA_DESKTOP_OVERRIDE` | test-only Desktop redirect (Phase 13 §5) |

Precedence: process env > `%APPDATA%\NOVA\.env` > repo `.env` (dev only). `.env.example` documents every var; `.gitignore` blocks `.env` (NFR-8).

**First run:** no keys → welcome pane with plain-language key setup steps (links to each provider's key page) + "Test" buttons (FR-47, T-603). App is fully navigable keyless (typed UI, Settings, About).

## 3. Logging (NFR-14)

- `logs\nova.log`, `RotatingFileHandler` 2 MB × 5 files. Format: `ts level module request_id message` — `request_id` threads a request across all layers (matches pipeline events, A-2).
- Levels: pipeline events at INFO (via the event→log bridge), provider/tool internals at DEBUG, all errors with stack at ERROR. **Keys and full prompts are never logged**; prompts at DEBUG are truncated to 200 chars.
- Troubleshooting affordance: Settings → About → "Open logs folder".

## 4. Release Process

- **SemVer**: MAJOR (breaking contract/file-format changes), MINOR (features, new tools), PATCH (fixes). Persisted-file `version` fields migrate forward (Phase 11 §7).
- **CHANGELOG.md**: Keep-a-Changelog format, updated per PR (Phase 20 gate).
- **Checklist per release:** CI green on `main` → version bump PR (changelog + docs sync check) → tag `vX.Y.Z` → CI builds artifact → clean-VM manual smoke (Phase 13 §6) → publish GitHub Release with notes + checksums → post-release: verify download-unzip-run on a second machine.
- Cadence: milestone-driven, not calendar-driven. `v1.0.0` at M6; fixes as `v1.0.x`.
- **Updates:** manual download in v1.0; the app shows its version in About + a "check for updates" link to the Releases page (no auto-update — NG-8).

## 5. Support Matrix

Windows 11 x64, working audio in/out for voice features (app degrades to typed-only without), network required for LLM/STT/weather (offline behavior per SC-6/Phase 8 §6); **`takada-tts-service` must be running locally for primary TTS** (falls back to `pyttsx3` otherwise, docs/04 TD-6). **Disk ≈ 300–400 MB unpacked** (revised M9: pocket-tts's PyTorch dependency, added M4, moved out of Nova's own process into the separately-run `takada-tts-service`, docs/04 TD-6 — ⚠️ exact figure pending an actual M9-era PyInstaller artifact).

---

## Revision History

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-07-08 | Initial version for Phase 14 review. |
| 1.1.0 | 2026-07-10 | M4: disk footprint revised for pocket-tts's PyTorch dependency (docs/04 TD-6) — ≈ 400 MB → ≈ 1.2–2 GB, ⚠️ pending actual M6 build measurement. |
| 1.2.0 | 2026-07-23 | M9 (Stream A): PyTorch dependency moved out of Nova's process into the separately-run `takada-tts-service` (docs/04 TD-6) — disk footprint reverts toward ≈ 300–400 MB; added a support-matrix note that `takada-tts-service` must be running locally for primary TTS. ⚠️ pending actual M9-era build measurement. |

**Exit check:** a stranger with the zip + README can run NOVA in < 10 minutes; secrets never touch git or logs; every release step is checklisted.
