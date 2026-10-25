# MISSION BRIEF: Build "Contributor Compass" (hackathon MVP)

You are a senior full-stack engineer working under a hard deadline. Build the complete MVP described below, test it, and deliver a runnable project. Follow this brief literally. When something is ambiguous, choose the simplest option that satisfies the acceptance criteria, state your choice in the README, and keep moving. Do not stop to ask questions unless a required secret is missing.

---

## 1. Context

- **Event:** Hacktoberfest Hack Day Hyderabad x Kramer's Community (MLH), in person, Sunday 25 Oct 2026.
- **Hard deadline:** project submission closes **12:30 PM IST**. Treat 12:15 PM as the real deadline. A working, demo-able subset beats a broken full build.
- **Target prize categories (one submission can enter both):**
  1. **Best Use of Gemma 4** (Google DeepMind): build a focused AI tool that uses Gemma 4's multimodal intelligence through the Gemini API for learning, creativity, productivity or community.
  2. **Best Open-Source AI Project** (DigitalOcean): original project where open-weight AI is an important part of how it works.
- **Judges** are developers. They reward: a clear user problem, a live working demo, visible use of Gemma 4's specific features (image input, function calling, structured JSON, long context), and honest engineering.

## 2. Product in one paragraph

**Contributor Compass** helps first-time open-source contributors get unstuck. A user pastes a public GitHub repository link and either describes an issue, attaches a screenshot of a bug or UI problem, or picks an issue from an "Issue Radar" list of open `good first issue` tickets. A Gemma 4 agent then explores the repository through the GitHub REST API using function calling (search the file tree, read files, read CONTRIBUTING and the PR template), and produces a verified **contribution brief**: the 1-5 files that matter and what each does in plain language, a step-by-step fix plan, a test checklist, a commit message, a PR description that follows the repo's own template, and a ready-to-post "can I work on this?" comment for the maintainers. Every file the AI cites is checked against the real repo tree and linked, so nothing is hallucinated.

## 3. Target user and core promise

- **User:** a student or newcomer who wants to contribute for Hacktoberfest but does not know where to start in an unfamiliar codebase.
- **Promise:** "Paste a repo and an issue. In under a minute, know exactly which files to open, what to change, and how to open the PR."

## 4. Tech stack (fixed, do not substitute)

| Layer | Choice |
|---|---|
| Language | Python 3.10+ |
| Backend | Flask (single `app.py`), streaming via NDJSON |
| AI | `google-genai` Python SDK, model **`gemma-4-31b-it`** (configurable via env `GEMMA_MODEL`; fallback `gemma-4-26b-a4b-it`) |
| GitHub | REST API v3 via `requests`, unauthenticated by default, optional user token |
| Frontend | One static `index.html` with inline CSS and vanilla JS. No framework, no build step, no CDN dependencies that could fail on venue Wi-Fi |
| Storage | None. No database. Optional `sessionStorage` for the GitHub token |
| Config | env var `GEMINI_API_KEY` (also accept `GOOGLE_API_KEY`), optional `.env` via python-dotenv |

## 5. Functional requirements

### 5.1 MUST HAVE (MVP, build in this order)
1. **Repo ingestion.** Parse `https://github.com/owner/repo` (also `owner/repo`). Fetch repo metadata, default branch, README excerpt (max 3000 chars) and the recursive git tree. Filter noise (node_modules, dist, build, vendor, lock files, images, fonts, binaries). Handle GitHub's truncated-tree flag.
2. **Multimodal issue input.** Free-text issue description AND optional screenshot (PNG/JPEG/WebP, max 5 MB). Support file picker, drag-and-drop and **Ctrl+V paste** of a screenshot.
3. **Gemma 4 function-calling agent loop** with exactly these three tools:
   - `search_paths(keywords)`: case-insensitive keyword match against the in-memory file tree, returns up to 40 real paths ranked by number of matching keywords.
   - `read_file(path, start_line=1)`: returns up to 250 numbered lines. Reject any path not in the tree with an instructive error so the model self-corrects.
   - `read_contributing()`: returns CONTRIBUTING guide (first 4000 chars) and PR template (first 2000 chars) if present, else a note.
   - Loop limit: **max 8 model turns**. Disable SDK automatic function calling; run the loop manually. Handle multiple parallel function calls in one turn.
4. **Final structured answer** produced in a separate, clean model call (no tools) from a text digest of the evidence the agent actually read. Request JSON (`response_mime_type="application/json"`); if that errors, retry without it and parse with a tolerant extractor (strip code fences, find first `{...}`).
5. **Verification pass.** For every file in the answer set `verified` (path exists in tree), `read_by_agent` (the agent actually opened it) and a `url` to the GitHub blob. Unverified files must be visibly marked in the UI.
6. **Live agent trace.** Stream events to the browser as they happen: loading repo, indexed N files, each tool call with arguments and a one-line result summary, writing the brief. The user should watch the agent work.
7. **Result UI** with cards: problem summary, difficulty (level, time estimate, confidence meter, reason), files to open (with plain explanation, where to look, verification badge, link), fix plan (numbered steps), test checklist, commit message, PR description, maintainer comment, unknowns.
8. **Copy buttons** for commit message, PR description and maintainer comment. **Download** the full brief as Markdown.
9. **Error handling** with human-readable messages (see section 9).

### 5.2 SHOULD HAVE (only after all MUST items work end to end)
10. **Issue Radar:** button that lists up to 10 open issues for the repo, trying label `good first issue`, then `help wanted`, then any open issues; excludes pull requests; shows number, title, labels, comment count; clicking one fills the issue textbox with title + body (max 1200 chars).
11. **Language selector** for explanations: English, Hindi, Telugu (PR description, commit message, maintainer comment, test checklist stay in English).
12. **Experience level selector:** beginner or intermediate; changes the explanation style in the prompt.
13. **Settings drawer** for an optional GitHub personal access token (raises the rate limit from 60 to 5000 requests/hour). Never persist beyond the browser session, never log it.

### 5.3 NICE TO HAVE (skip unless everything above is done and tested)
- Example buttons that prefill a known small repo and issue for the demo.
- Dark/light theme toggle.
- Timing display ("brief ready in 34s").

### 5.4 OUT OF SCOPE (do not build)
Accounts or login, database, cloning repos, running or executing repository code, creating PRs or comments on GitHub automatically, private repos, browser extension, multi-repo analysis, payment, analytics, Docker, CI.

## 6. Architecture and file layout

```
contributor-compass/
  app.py              # Flask app, GitHub helpers, tools, agent loop, routes
  index.html          # entire frontend
  requirements.txt    # flask, google-genai, requests, python-dotenv
  .env.example        # GEMINI_API_KEY=your-key
  README.md           # setup, features, how it works, demo script, pitch, limitations
```

### Routes
- `GET /` serves `index.html`.
- `POST /api/analyze` (multipart form). Fields: `repo` (string), `issue` (string, optional if image present), `image` (file, optional), `level` (`beginner`|`intermediate`), `language` (`English`|`Hindi`|`Telugu`), `token` (optional). Responds `application/x-ndjson`, one JSON object per line, with headers `X-Accel-Buffering: no` and `Cache-Control: no-cache`.
  - Event shapes: `{"type":"step","text":"..."}`, `{"type":"tool","name":"...","args":"...","summary":"..."}`, `{"type":"result","data":{...}}`, `{"type":"error","text":"..."}`. Exactly one terminal event (`result` or `error`).
- `POST /api/issues` (JSON `{repo, token?}`) returns `{repo, source, issues:[{number,title,url,labels,comments,body}]}` or `{error}` with HTTP 400.

### Final JSON schema (the model must produce this; the server adds `repo`, `files_read`, and per-file `verified`, `read_by_agent`, `url`)
```json
{
  "title": "string",
  "problem_summary": "string",
  "difficulty": {"level": "easy|medium|hard", "estimated_time": "string", "confidence": 0, "why": "string"},
  "files": [{"path": "string", "why_relevant": "string", "plain_explanation": "string", "where_to_look": "string"}],
  "fix_plan": [{"step": "string", "detail": "string"}],
  "test_checklist": ["string"],
  "commit_message": "string",
  "pr_description": "markdown string",
  "maintainer_comment": "string",
  "unknowns": ["string"]
}
```

### Agent design rules
- System prompt instructs the model to: call `read_contributing` once; extract concrete keywords from the issue or screenshot (button labels, error text, feature names); call `search_paths`; confirm with `read_file`; read at most 6 files; never invent paths, function names or line numbers; admit uncertainty; reply `READY` when done.
- The first user message contains: repo name, description, main language, README excerpt, tree digest, the issue text, and the screenshot as an image part.
- **Tree digest rule:** if there are 350 or fewer paths, send them all; otherwise send paths at depth 0-1 plus a list of top-level directories with file counts and tell the model to use `search_paths` to go deeper.
- Final prompt receives only evidence the agent really read (path, line range, numbered content). This prevents the model from citing files it never opened.
- Use `temperature` 0.3 in the investigation loop and 0.2 for the final answer.

## 7. Gemma 4 and Gemini API specifics

- Gemma 4 is available through the Gemini API. Use model IDs `gemma-4-31b-it` (primary) and `gemma-4-26b-a4b-it` (faster fallback). Both support native function calling, structured JSON output, system instructions, image input and a 256K context window. Output is text only. Audio input is not available on these API models, so do not build audio features.
- Use `google-genai` (`pip install google-genai`). Declare functions with `types.FunctionDeclaration` and `types.Schema` using `types.Type` enums (do not pass lowercase JSON-schema type strings). Send tool results back with `types.Part.from_function_response(name=..., response={"result": ...})` in a `user` turn. Append the model's own `content` object to history unchanged before replying with tool results.
- **Verify early (first 10 minutes), do not assume:** (a) function calling works with an image part in the first message, (b) JSON mode works without tools, (c) the system instruction is honored. If an assumption fails, apply the documented fallback in this brief and note it in the README.
- Do not enable thinking or reasoning config unless a one-line test call proves the parameter is accepted by the model; if it errors, remove it. Reliability beats cleverness.

## 8. UI/UX requirements

- Single column, max width about 960px, clean modern dark theme, readable on a projector (base font at least 16px, strong contrast).
- Page order: header (name, one-line tagline, "Powered by Gemma 4" badge), input card (repo field + Issue Radar button, issue textarea, screenshot drop zone with preview and remove button, level/language selects, Analyze button, Settings link), live trace timeline, results.
- Disable the Analyze button while running; show a visible spinner and the streaming trace. Scroll results into view when finished.
- Responsive down to phone width (users may demo on a phone).
- Accessibility basics: labels on inputs, visible focus states, buttons are real `<button>` elements.
- **Security:** escape all model output and GitHub text before inserting into the DOM (use `textContent` or an escape helper). Never use `innerHTML` with unescaped data. The PR description is shown in a `<pre>`.

## 9. Error handling (each must show a clear message, never a stack trace)

| Situation | Behavior |
|---|---|
| Invalid repo link | "Paste a link like https://github.com/owner/repo" |
| Repo not found or private | "Not found on GitHub. Is the repository public and the link correct?" |
| GitHub rate limit | Suggest adding a token in Settings |
| Missing `GEMINI_API_KEY` | Server-side error message naming the variable (never the key) |
| Model returns invalid JSON | Retry once without JSON mode, then show "Gemma returned an unreadable answer. Please try again." |
| Model calls unknown tool or bad path | Return an error object to the model so it can recover; do not crash |
| No issue text and no image | HTTP 400 with message |
| Wrong image type or over 5 MB | HTTP 400 with message |
| Agent hits the 8-turn cap | Proceed to the final answer using evidence gathered so far |

## 10. Constraints (non-negotiable)

**Time**
- Total build budget: 60 minutes. A working end-to-end path must exist by minute 35. Stop adding features at minute 50 and spend the rest on testing, README and packaging.

**Security and privacy**
- The Gemini API key lives only on the server in an environment variable. It must never appear in `index.html`, logs, error messages or the zip.
- Only call `api.github.com`. Never fetch arbitrary URLs supplied by the user (SSRF). Repo links are parsed into owner and repo only.
- Do not log screenshots, issue text, tokens or file contents.
- Never execute, import or evaluate code from the analyzed repository.

**Reliability and limits**
- GitHub unauthenticated rate limit is 60 requests/hour. Budget requests: about 3 for repo load, up to 8 for file reads, 1 for issues. Cache file contents in memory per request. Keep a single analysis under about 15 GitHub calls.
- Truncate file reads at 250 lines and 300 characters per line, README at 3000 characters, contributing guide at 4000, PR template at 2000.
- Ignore binaries, lockfiles and build output in the tree.
- Request timeout of 25 seconds for GitHub calls. Flask must run threaded so streaming does not block other requests.

**Honesty and quality**
- The AI must only cite files it actually read. The server enforces this with the verification pass.
- No fabricated demo data, benchmark numbers or claims in the README. If something was not tested, say so.
- Keep dependencies to the four listed. No heavy frameworks.

**Code quality**
- Readable, commented where non-obvious, no dead code, type-safe handling of model output (the model may return strings where numbers are expected, missing keys or extra keys). The UI must render gracefully when optional fields are missing.

## 11. Build order and time boxes

1. (0-10 min) Skeleton: Flask app, `/` route, key loading, one test call to Gemma with an image + a trivial function declaration. Record what works.
2. (10-25 min) GitHub helpers, tree filtering, the three tools, tool dispatch, manual agent loop.
3. (25-35 min) Final JSON call, verification pass, `/api/analyze` streaming. **Milestone: curl the endpoint and get a valid result for a real small public repo.**
4. (35-50 min) Frontend: input card, paste/drag image, trace timeline, result cards, copy and download.
5. (50-55 min) Issue Radar, language and level selects, settings drawer (if time allows).
6. (55-60 min) README, requirements, `.env.example`, zip.

## 12. Testing (do all of these before declaring done)

1. Unit-level checks without the network: `parse_repo` (full URL, `.git` suffix, trailing slash, `owner/repo`, garbage), `is_noise`, `tree_digest` (small and large), `extract_json` (clean JSON, fenced JSON, JSON with prose around it, garbage), tool dispatch with a fake `RepoContext`.
2. Agent loop test with a fake model client that returns a scripted sequence: a `search_paths` call, a `read_file` call with a bad path, a corrected `read_file`, then text. Assert the loop terminates, the evidence is recorded, and the final result marks only really-read files as `read_by_agent`.
3. Flask test client: `/api/analyze` rejects empty input and bad image types; `/api/issues` returns a clean error for a bad repo.
4. If a real `GEMINI_API_KEY` and network are available: run one real end-to-end analysis on a small public repo and confirm the UI renders it. If they are not available, say so explicitly in your report. Do not claim a live test you did not run.
5. Frontend: open `index.html` served by Flask; verify paste, drag-drop, streaming trace, copy buttons, download, and mobile width.

## 13. Acceptance criteria (definition of done)

- [ ] `pip install -r requirements.txt && export GEMINI_API_KEY=... && python app.py` starts the app on port 5000 with no errors.
- [ ] Given a public repo link and an issue description, the user sees a live trace of tool calls and then a complete brief within roughly 60 seconds.
- [ ] Given a screenshot only (no text), the app still produces a brief.
- [ ] Every cited file is verified against the real tree and linked, and unverified citations are visibly flagged.
- [ ] The PR description follows the repo's template when one exists.
- [ ] Copy buttons and Markdown download work.
- [ ] All error cases in section 9 show friendly messages.
- [ ] No secret appears anywhere in the project files.
- [ ] README includes: what it is, features, setup, architecture, how Gemma 4 is used, known limitations, a 90-second demo script, and a short pitch for both prize categories.

## 14. README content requirements

- **Pitch for "Best Use of Gemma 4":** emphasize multimodal screenshot understanding, native function calling driving a real tool-using agent, structured JSON output, and the 256K context used for evidence, plus the open-weights path (the same model can be self-hosted later).
- **Pitch for "Best Open-Source AI Project":** open-weight model at the core, open-source code, helps grow the open-source community itself.
- **Demo script (90 seconds):** (1) paste a small active repo, click Issue Radar, pick an issue; (2) paste a screenshot of the bug; (3) click Analyze and narrate the live tool trace; (4) show verified files with links; (5) copy the PR description and the maintainer comment; (6) switch language to Telugu or Hindi and re-run for the wow moment.
- **Limitations (be honest):** public repos only; analysis quality depends on how well the issue maps to file or path names; large monorepos may exceed the tree limit; GitHub unauthenticated rate limit; the AI suggests a plan but does not write or test the patch.

## 15. Final report format (what you send back)

1. One paragraph: what was built and what is not built.
2. The project folder zipped, plus the list of files.
3. A "tested vs not tested" table (be exact).
4. Any deviations from this brief and why.
5. Exact run commands and any env vars needed.

---

### One-line reminder

Ship a **working, verified, demo-ready** Contributor Compass by 12:15 PM IST. Correctness and honesty over feature count.
