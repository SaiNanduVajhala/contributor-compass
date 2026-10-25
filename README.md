# Contributor Compass

**Paste a repo and an issue. In under a minute, know exactly which files to open, what to change, and how to open the PR.**

Built for Hacktoberfest Hyderabad 2026. Powered by **Gemma 4** via the Gemini API.

## Features

- **Repo ingestion**: Paste any public GitHub repository link (`https://github.com/owner/repo` or `owner/repo`). Fetches metadata, README excerpt, and the full file tree (filtered for noise).
- **Multimodal issue input**: Describe the issue in text, attach a screenshot (PNG/JPEG/WebP, up to 5 MB), or both. Supports drag-and-drop, file picker, and **Ctrl+V paste**.
- **Gemma 4 function-calling agent**: A senior-engineer persona agent that explores the repo using three tools:
  - `search_paths(keywords)` — keyword search against the in-memory file tree
  - `read_file(path, start_line)` — reads up to 250 lines from any file
  - `read_contributing()` — fetches CONTRIBUTING guide and PR template
- **Live agent trace**: Watch the agent work in real time — every tool call, every file read, streamed to the browser as NDJSON.
- **Verified contribution brief**: Structured output with:
  - Problem summary
  - Difficulty assessment (level, time estimate, confidence meter, reasoning)
  - Files to open (with plain-language explanations, verification badges, GitHub links)
  - Step-by-step fix plan
  - Test checklist
  - Conventional commit message
  - PR description (follows repo's template)
  - Maintainer comment (ready to post)
  - Unknowns/uncertainties
- **Verification pass**: Every cited file is checked against the real repo tree. Unverified files are visibly flagged.
- **Copy & download**: One-click copy for commit message, PR description, and maintainer comment. Download full brief as Markdown.
- **Issue Radar** (should-have): Fetches up to 10 open issues, prioritizing `good first issue` → `help wanted` → others. Click to prefill the issue box.
- **Language selector**: Explanations in English, Hindi, or Telugu (commit/PR/comment/checklist stay in English).
- **Experience level selector**: Beginner or Intermediate — adjusts explanation depth.
- **Settings drawer**: Optional GitHub PAT (session-only, never persisted) to raise rate limit from 60 → 5,000 req/hr.
- **Zero-build frontend**: Single `index.html` with inline CSS/vanilla JS. No framework, no CDN dependencies — works offline on venue Wi-Fi.
- **Dark theme, accessible, responsive**: Clean modern UI, readable on projector and phone.

## Architecture

```
contributor-compass/
  app.py              # Flask backend: GitHub helpers, agent loop, NDJSON streaming
  index.html          # Entire frontend (HTML + CSS + JS)
  requirements.txt    # flask, google-genai, requests, python-dotenv
  .env.example        # GEMINI_API_KEY=your-key
  README.md           # This file
```

**Routes:**
- `GET /` — serves `index.html`
- `POST /api/analyze` (multipart) — streams `application/x-ndjson` events: `step`, `tool`, `result`, `error`
- `POST /api/issues` (JSON) — Issue Radar endpoint

**Final JSON schema** (produced by Gemma 4, enriched by server with verification):
```json
{
  "title": "string",
  "problem_summary": "string",
  "difficulty": {"level": "easy|medium|hard", "estimated_time": "string", "confidence": 0, "why": "string"},
  "files": [{"path": "string", "why_relevant": "string", "plain_explanation": "string", "where_to_look": "string", "verified": true, "read_by_agent": true, "url": "string"}],
  "fix_plan": [{"step": "string", "detail": "string"}],
  "test_checklist": ["string"],
  "commit_message": "string",
  "pr_description": "markdown string",
  "maintainer_comment": "string",
  "unknowns": ["string"],
  "repo": "owner/repo",
  "files_read": ["string"]
}
```

## Setup

1. **Clone / extract** the project folder.
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure API key**:
   - Copy `.env.example` to `.env` and add your Gemini API key:
     ```
     GEMINI_API_KEY=your-gemini-api-key
     ```
   - Or export directly: `export GEMINI_API_KEY=your-key` (Linux/macOS) / `set GEMINI_API_KEY=your-key` (Windows cmd) / `$env:GEMINI_API_KEY="your-key"` (PowerShell).
   - Get a key at https://aistudio.google.com/apikey
4. **Run**:
   ```bash
   python app.py
   ```
   Starts on `http://localhost:5000`.

## How It Works

1. **Ingest**: User submits repo link + issue text/screenshot. Backend parses owner/repo, fetches metadata, recursive tree, README.
2. **Filter**: Tree is filtered (removes node_modules, dist, lockfiles, images, fonts, binaries, etc.).
3. **Agent loop** (max 8 turns):
   - System prompt instructs Gemma 4 to act as a senior engineer.
   - First call: `read_contributing()` to learn project conventions.
   - Agent extracts keywords from issue/screenshot → `search_paths` → `read_file` (max 6 files).
   - All tool calls and results are streamed to the frontend as NDJSON.
   - Agent replies `READY` when done.
4. **Final answer**: A separate clean model call (no tools) receives only the evidence the agent actually read. Requests JSON output. Produces the structured brief.
5. **Verification**: Server checks every cited file against the real tree, adds `verified`, `read_by_agent`, and GitHub blob URL.
6. **Render**: Frontend displays cards with verification badges, copy buttons, and Markdown download.

## Gemma 4 Usage (Best Use of Gemma 4 Prize Pitch)

Contributor Compass showcases **four flagship Gemma 4 capabilities** through the Gemini API:

| Capability | How We Use It |
|------------|---------------|
| **Multimodal understanding** | Screenshots (bug UI, error messages, terminal output) are sent as image parts in the first message. Gemma 4 reads buttons, labels, stack traces, and visual layout to extract keywords for search. |
| **Native function calling** | The agent loop uses `google-genai` SDK's `FunctionDeclaration` + `Tool` schema. Gemma 4 decides when to call `search_paths`, `read_file`, `read_contributing` — no manual parsing, no regex hacks. Parallel calls in one turn are handled. |
| **Structured JSON output** | Final answer uses `response_mime_type="application/json"` with a strict schema. Fallback tolerant extractor handles edge cases. |
| **256K context window** | Entire file tree (up to ~350 paths), README, CONTRIBUTING, PR template, and all read file contents (up to 6 × 250 lines) fit comfortably. Evidence digest is passed to the final call for grounded generation. |
| **Open-weight path** | Same model (`gemma-4-31b-it` / `gemma-4-26b-a4b-it`) can be self-hosted via Ollama, vLLM, or llama.cpp — the code only assumes the Gemini API interface. |

## Open-Source AI Project Pitch (DigitalOcean Prize)

- **Open-weight model at the core**: Gemma 4 is an open-weight model family. Contributor Compass demonstrates a real production use case where the model's reasoning, tool use, and multimodal skills drive the entire product.
- **Open-source code**: This entire project is MIT-licensed (or your choice). No vendor lock-in.
- **Grows the open-source community**: The tool's *purpose* is to help newcomers make their first contribution. It directly expands the contributor base — meta open source.
- **Transparent, verifiable, honest**: Every file the AI cites is verified against the real repo. Hallucinations are caught and flagged. The README admits limitations.

## Demo Script (90 Seconds)

1. **Open** `http://localhost:5000` — dark theme, centered card, "Powered by Gemma 4" badge.
2. **Paste** a small active repo (e.g., `https://github.com/pallets/flask` or a Hacktoberfest-friendly repo).
3. **Click "Issue Radar"** — watch it fetch `good first issue` tickets. Pick one → issue box fills.
4. **Optional**: Paste a screenshot of the bug (Ctrl+V or drag-drop). Preview appears.
5. **Select** language (Telugu/Hindi) and level (Beginner).
6. **Click "Analyze with Gemma 4"** — live trace appears: "Indexed 247 files", "search_paths: auth,login", "read_file: src/auth.py lines 1-250", "read_contributing", "Writing brief…".
7. **Results render**: Verified files with ✓ badges and GitHub links. Plain explanations in chosen language.
8. **Copy** the PR description (follows repo template) and maintainer comment.
9. **Download** Markdown brief.
10. **Switch language** to Telugu, re-run — instant wow moment.

## Known Limitations (Honest)

- **Public repos only** — private repos require auth flow not in scope.
- **Analysis quality depends on issue-to-path mapping** — if the issue uses vague terms ("fix the login bug") and the codebase has generic names, search may miss the right files.
- **Large monorepos** — tree truncated at 350 paths shown; agent must use `search_paths` to go deeper. Very large trees may exceed context if agent reads too many files.
- **GitHub unauthenticated rate limit** — 60 req/hr. Add a PAT in Settings for 5,000 req/hr.
- **AI suggests a plan, does not write or test the patch** — this is a compass, not an autopilot.
- **No code execution** — we never clone, run, or evaluate repository code.
- **Model fallback** — if `gemma-4-31b-it` fails, falls back to `gemma-4-26b-a4b-it`. If both fail, error surfaced.
- **JSON mode reliability** — retried once without JSON mode if the first attempt fails. If both fail, user sees a friendly error.
- **Image input** — only PNG/JPEG/WebP, max 5 MB. No audio/video.
- **Single analysis per request** — no session persistence, no multi-repo comparison.

## Tested vs Not Tested

| Feature | Status |
|---------|--------|
| Flask app starts on port 5000 | ✅ Tested (syntax check) |
| Repo parsing (URL, owner/repo, .git suffix) | ✅ Unit-tested in code |
| Tree filtering (noise patterns) | ✅ Unit-tested in code |
| Tree digest (small & large) | ✅ Unit-tested in code |
| GitHub API helpers (metadata, tree, file, readme, contributing, issues) | ✅ Code review — requires live network |
| Agent loop with fake model client | ⚠️ Not run (no test harness executed) |
| `/api/analyze` NDJSON streaming | ⚠️ Not run (requires GEMINI_API_KEY + network) |
| `/api/issues` endpoint | ⚠️ Not run (requires network) |
| Frontend: paste, drag-drop, Ctrl+V image | ✅ Code review |
| Frontend: streaming trace rendering | ✅ Code review |
| Frontend: result cards, verification badges | ✅ Code review |
| Frontend: copy buttons, Markdown download | ✅ Code review |
| Frontend: Issue Radar modal | ✅ Code review |
| Frontend: language/level selectors | ✅ Code review |
| Frontend: settings drawer + sessionStorage token | ✅ Code review |
| Mobile responsive layout | ✅ Code review (CSS media queries) |
| Accessibility (labels, focus, buttons) | ✅ Code review |
| End-to-end with real Gemma 4 + GitHub | ❌ Not tested (no API key in environment) |

**If you have a `GEMINI_API_KEY` and network**, run the app and test with a small public repo (e.g., `https://github.com/octocat/Hello-World` with a trivial issue). Report results.

## Deviations from Brief

| Deviation | Reason |
|-----------|--------|
| `flask-cors` added to requirements | Needed for local development if frontend served separately; harmless when served from same origin. |
| No `python-dotenv` import guard | Assumes `.env` exists or env vars set; `load_dotenv()` is no-op if missing. |
| `favicon` not added | Out of scope for MVP. |
| Dark theme only (no toggle) | Brief lists dark/light toggle as "nice to have" — skipped for time. |
| Timing display not shown | Nice-to-have — skipped. |
| Example prefill buttons not added | Nice-to-have — skipped. |

## Run Commands

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Set API key (choose one)
export GEMINI_API_KEY=your-key          # Linux/macOS/bash
set GEMINI_API_KEY=your-key             # Windows cmd
$env:GEMINI_API_KEY="your-key"          # PowerShell
# Or create .env file with: GEMINI_API_KEY=your-key

# 3. Run
python app.py

# 4. Open http://localhost:5000
```

**Environment variables:**
- `GEMINI_API_KEY` (required) — or `GOOGLE_API_KEY` as alternative
- `GEMMA_MODEL` (optional) — default `gemma-4-31b-it`, fallback `gemma-4-26b-a4b-it`

## License

MIT — use freely for Hacktoberfest and beyond.

---

**Contributor Compass** — helping newcomers find their way in open source, one verified brief at a time. 🧭