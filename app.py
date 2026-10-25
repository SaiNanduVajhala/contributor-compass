"""
Contributor Compass - Flask backend for Hacktoberfest MVP
Single-file Flask app with GitHub REST API integration and Gemma 4 agent loop.
"""
import os
import re
import json
import base64
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from functools import lru_cache

import requests
from flask import Flask, request, Response, send_file, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma-4-31b-it")
FALLBACK_MODEL = "gemma-4-26b-a4b-it"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_TIMEOUT = 25  # seconds
MAX_TURNS = 8
MAX_FILE_LINES = 250
MAX_LINE_CHARS = 300
MAX_README_CHARS = 3000
MAX_CONTRIBUTING_CHARS = 4000
MAX_PR_TEMPLATE_CHARS = 2000
TREE_DEPTH_LIMIT = 2  # for large trees

# Noise patterns to filter from file tree
NOISE_PATTERNS = [
    r"node_modules/",
    r"dist/",
    r"build/",
    r"vendor/",
    r"\.lock$",
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
    r"\.(png|jpg|jpeg|gif|webp|svg|ico|woff|woff2|ttf|eot|otf)$",
    r"\.(exe|dll|so|dylib|bin|class|jar|war|ear)$",
    r"\.git/",
    r"__pycache__/",
    r"\.pyc$",
    r"\.min\.js$",
    r"\.min\.css$",
    r"coverage/",
    r"\.next/",
    r"\.nuxt/",
    r"target/",
    r"\.idea/",
    r"\.vscode/",
]

# Flask app
app = Flask(__name__)
CORS(app)
app.config["JSON_SORT_KEYS"] = False

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class RepoContext:
    owner: str
    repo: str
    default_branch: str
    tree: List[Dict[str, Any]] = field(default_factory=list)
    tree_map: Dict[str, Dict] = field(default_factory=dict)  # path -> {path, type, size}
    readme_excerpt: str = ""
    file_contents_cache: Dict[str, str] = field(default_factory=dict)
    files_read_by_agent: set = field(default_factory=set)
    
    def is_valid_path(self, path: str) -> bool:
        return path in self.tree_map
    
    def get_file_info(self, path: str) -> Optional[Dict]:
        return self.tree_map.get(path)


@dataclass
class AgentEvidence:
    path: str
    start_line: int
    end_line: int
    content: str


# ============================================================================
# GitHub Helpers
# ============================================================================

def parse_repo_url(repo_input: str) -> Tuple[str, str]:
    """Parse various repo formats into (owner, repo)."""
    repo_input = repo_input.strip()
    # Remove .git suffix
    if repo_input.endswith(".git"):
        repo_input = repo_input[:-4]
    # Handle full URL
    if repo_input.startswith("http"):
        # https://github.com/owner/repo or similar
        match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_input)
        if match:
            return match.group(1), match.group(2)
    # Handle owner/repo format
    if "/" in repo_input and not repo_input.startswith("http"):
        parts = repo_input.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    raise ValueError("Paste a link like https://github.com/owner/repo")


def github_request(endpoint: str, token: Optional[str] = None, params: Optional[Dict] = None) -> requests.Response:
    """Make a GitHub API request with optional auth."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{GITHUB_API_BASE}{endpoint}"
    return requests.get(url, headers=headers, params=params, timeout=GITHUB_TIMEOUT)


def fetch_repo_metadata(owner: str, repo: str, token: Optional[str] = None) -> Dict:
    """Fetch basic repo metadata."""
    resp = github_request(f"/repos/{owner}/{repo}", token=token)
    if resp.status_code == 404:
        raise ValueError("Not found on GitHub. Is the repository public and the link correct?")
    if resp.status_code == 403:
        raise ValueError("GitHub rate limit exceeded. Add a token in Settings to increase the limit.")
    resp.raise_for_status()
    return resp.json()


def fetch_tree(owner: str, repo: str, branch: str, token: Optional[str] = None) -> List[Dict]:
    """Fetch recursive git tree, handling truncation."""
    resp = github_request(f"/repos/{owner}/{repo}/git/trees/{branch}", 
                          token=token, params={"recursive": "1"})
    if resp.status_code == 404:
        raise ValueError("Could not fetch repository tree.")
    resp.raise_for_status()
    data = resp.json()
    tree = data.get("tree", [])
    truncated = data.get("truncated", False)
    if truncated:
        logger.warning(f"Tree truncated for {owner}/{repo}")
    return tree


def filter_tree(tree: List[Dict]) -> List[Dict]:
    """Filter out noise files from the tree."""
    filtered = []
    for item in tree:
        if item["type"] != "blob":
            continue
        path = item["path"]
        # Check noise patterns
        is_noise = False
        for pattern in NOISE_PATTERNS:
            if re.search(pattern, path, re.IGNORECASE):
                is_noise = True
                break
        if not is_noise:
            filtered.append({"path": path, "size": item.get("size", 0)})
    return filtered


def build_tree_map(filtered_tree: List[Dict]) -> Dict[str, Dict]:
    """Build a path -> info map for quick lookups."""
    return {item["path"]: item for item in filtered_tree}


def fetch_file_content(owner: str, repo: str, path: str, branch: str, 
                       token: Optional[str] = None, start_line: int = 1, 
                       max_lines: int = MAX_FILE_LINES) -> Tuple[str, int, int]:
    """Fetch file content from GitHub, return (content, start_line, end_line)."""
    resp = github_request(f"/repos/{owner}/{repo}/contents/{path}", 
                          token=token, params={"ref": branch})
    if resp.status_code == 404:
        raise ValueError(f"File not found: {path}")
    resp.raise_for_status()
    data = resp.json()
    
    if data.get("encoding") == "base64":
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    else:
        content = data.get("content", "")
    
    lines = content.splitlines()
    total_lines = len(lines)
    start = max(1, min(start_line, total_lines))
    end = min(start + max_lines - 1, total_lines)
    selected = lines[start - 1:end]
    
    # Truncate long lines
    truncated_lines = [line[:MAX_LINE_CHARS] + ("…" if len(line) > MAX_LINE_CHARS else "") 
                       for line in selected]
    
    return "\n".join(truncated_lines), start, end


def fetch_readme(owner: str, repo: str, branch: str, token: Optional[str] = None) -> str:
    """Fetch README excerpt."""
    # Try common README names
    for name in ["README.md", "README.rst", "README.txt", "README"]:
        try:
            resp = github_request(f"/repos/{owner}/{repo}/contents/{name}", 
                                  token=token, params={"ref": branch})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("encoding") == "base64":
                    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                    return content[:MAX_README_CHARS]
        except Exception:
            continue
    return ""


def fetch_contributing_and_pr_template(owner: str, repo: str, branch: str, 
                                        token: Optional[str] = None) -> Tuple[str, str]:
    """Fetch CONTRIBUTING guide and PR template."""
    contributing = ""
    pr_template = ""
    
    # CONTRIBUTING files
    for name in ["CONTRIBUTING.md", "CONTRIBUTING.rst", "CONTRIBUTING.txt", 
                 "docs/CONTRIBUTING.md", ".github/CONTRIBUTING.md"]:
        try:
            resp = github_request(f"/repos/{owner}/{repo}/contents/{name}", 
                                  token=token, params={"ref": branch})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("encoding") == "base64":
                    contributing = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                    contributing = contributing[:MAX_CONTRIBUTING_CHARS]
                    break
        except Exception:
            continue
    
    # PR template
    for name in [".github/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE.md",
                 "pull_request_template.md", "PULL_REQUEST_TEMPLATE.md",
                 ".github/pull_request_template.txt", "pull_request_template.txt"]:
        try:
            resp = github_request(f"/repos/{owner}/{repo}/contents/{name}", 
                                  token=token, params={"ref": branch})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("encoding") == "base64":
                    pr_template = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                    pr_template = pr_template[:MAX_PR_TEMPLATE_CHARS]
                    break
        except Exception:
            continue
    
    return contributing, pr_template


def fetch_issues(owner: str, repo: str, token: Optional[str] = None) -> List[Dict]:
    """Fetch open issues for Issue Radar."""
    resp = github_request(f"/repos/{owner}/{repo}/issues", 
                          token=token, params={"state": "open", "per_page": 100, "sort": "updated"})
    if resp.status_code == 404:
        raise ValueError("Repository not found.")
    if resp.status_code == 403:
        raise ValueError("GitHub rate limit exceeded. Add a token in Settings.")
    resp.raise_for_status()
    
    issues = resp.json()
    # Filter out PRs (they have a pull_request key)
    issues = [i for i in issues if "pull_request" not in i]
    
    # Sort by priority: good first issue > help wanted > others
    def priority(issue):
        labels = [l["name"].lower() for l in issue.get("labels", [])]
        if "good first issue" in labels:
            return 0
        if "help wanted" in labels:
            return 1
        return 2
    
    issues.sort(key=priority)
    return issues[:10]


# ============================================================================
# Tree Digest for Agent
# ============================================================================

def create_tree_digest(filtered_tree: List[Dict]) -> str:
    """Create a digest of the file tree for the agent prompt."""
    paths = [item["path"] for item in filtered_tree]
    
    if len(paths) <= 350:
        return "\n".join(f"- {p}" for p in paths)
    
    # For large trees: show depth 0-1 + top-level dir counts
    depth_0_1 = [p for p in paths if p.count("/") <= 1]
    top_dirs = {}
    for p in paths:
        top = p.split("/")[0] if "/" in p else p
        top_dirs[top] = top_dirs.get(top, 0) + 1
    
    lines = [f"- {p}" for p in depth_0_1]
    lines.append("\n[Tree truncated. Top-level directories with file counts:]")
    for d, count in sorted(top_dirs.items(), key=lambda x: -x[1]):
        lines.append(f"  {d}/ ({count} files)")
    lines.append("Use search_paths to explore deeper.")
    return "\n".join(lines)


# ============================================================================
# Agent Tools
# ============================================================================

def tool_search_paths(ctx: RepoContext, keywords: str) -> Dict[str, Any]:
    """Search file tree for paths matching keywords."""
    kw_list = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    if not kw_list:
        return {"results": [], "count": 0}
    
    scored = []
    for path in ctx.tree_map:
        score = sum(1 for kw in kw_list if kw in path.lower())
        if score > 0:
            scored.append((score, path))
    
    scored.sort(key=lambda x: -x[0])
    results = [{"path": p, "score": s} for s, p in scored[:40]]
    return {"results": results, "count": len(results)}


def tool_read_file(ctx: RepoContext, owner: str, repo: str, branch: str, 
                   path: str, start_line: int = 1, token: Optional[str] = None) -> Dict[str, Any]:
    """Read a file from the repo."""
    if not ctx.is_valid_path(path):
        return {
            "error": f"Path '{path}' not found in repository tree. Use search_paths to find valid paths.",
            "valid": False
        }
    
    try:
        content, start, end = fetch_file_content(owner, repo, path, branch, token, start_line)
        # Cache for verification
        cache_key = f"{path}:{start}-{end}"
        ctx.file_contents_cache[cache_key] = content
        ctx.files_read_by_agent.add(path)
        
        return {
            "path": path,
            "start_line": start,
            "end_line": end,
            "content": content,
            "valid": True
        }
    except Exception as e:
        return {"error": str(e), "valid": False}


def tool_read_contributing(ctx: RepoContext, owner: str, repo: str, branch: str, 
                           token: Optional[str] = None) -> Dict[str, Any]:
    """Read CONTRIBUTING guide and PR template."""
    contributing, pr_template = fetch_contributing_and_pr_template(owner, repo, branch, token)
    return {
        "contributing": contributing or "No CONTRIBUTING guide found.",
        "pr_template": pr_template or "No PR template found."
    }


# ============================================================================
# JSON Extraction
# ============================================================================

def extract_json(text: str) -> Optional[Dict]:
    """Extract JSON from model output, handling fences and prose."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON in code fences
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to find first { ... } block
    brace_match = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except json.JSONDecodeError:
            pass
    
    return None


# ============================================================================
# Agent System Prompts
# ============================================================================

SYSTEM_PROMPT = """You are a senior software engineer helping a newcomer contribute to an open-source repository.
Your task is to explore the repository using the provided tools and produce a contribution brief.

TOOLS AVAILABLE:
1. search_paths(keywords): Search the file tree for paths matching keywords (comma-separated). Returns up to 40 paths ranked by relevance.
2. read_file(path, start_line): Read up to 250 lines from a file. Path must exist in the tree.
3. read_contributing(): Read the CONTRIBUTING guide and PR template.

WORKFLOW:
1. Call read_contributing() ONCE at the start to understand project conventions.
2. Analyze the issue/screenshot to extract concrete keywords (button labels, error messages, feature names, function names, file extensions).
3. Call search_paths with those keywords to find relevant files.
4. Call read_file on the most promising paths (max 6 files total) to understand the code.
5. When you have enough evidence, reply with exactly "READY" (no other text).

RULES:
- Never invent paths, function names, or line numbers. Only cite what you actually read.
- If a path is invalid, the tool will return an error - correct and retry.
- Admit uncertainty when you don't have enough information.
- Maximum 8 tool-calling turns.
- Reply "READY" when done investigating."""


def build_initial_user_message(ctx: RepoContext, issue_text: str, 
                                has_image: bool, language: str, level: str) -> str:
    """Build the first user message for the agent."""
    tree_digest = create_tree_digest(ctx.tree)
    
    msg = f"""Repository: {ctx.owner}/{ctx.repo}
Default branch: {ctx.default_branch}
Main language: (detected from tree)
README excerpt:
{ctx.readme_excerpt or "No README found."}

File tree:
{tree_digest}

Issue description:
{issue_text or "(no text provided - screenshot only)"}

Screenshot provided: {"Yes" if has_image else "No"}

Target explanation language: {language}
Experience level: {level}

Begin investigation. Call read_contributing() first."""
    return msg


FINAL_PROMPT_TEMPLATE = """Based on the evidence below, produce a complete contribution brief as JSON matching this schema:

{{
  "title": "string",
  "problem_summary": "string",
  "difficulty": {{"level": "easy|medium|hard", "estimated_time": "string", "confidence": 0-100, "why": "string"}},
  "files": [{{"path": "string", "why_relevant": "string", "plain_explanation": "string", "where_to_look": "string"}}],
  "fix_plan": [{{"step": "string", "detail": "string"}}],
  "test_checklist": ["string"],
  "commit_message": "string",
  "pr_description": "markdown string",
  "maintainer_comment": "string",
  "unknowns": ["string"]
}}

RULES:
- Only cite files from the evidence. Every file in "files" must appear in the evidence.
- PR description must follow the repo's PR template if provided.
- Commit message: conventional commits format (type: short description).
- Maintainer comment: polite, concise, ready to post.
- Test checklist: concrete, verifiable steps.
- Explanations in {language}, but commit/PR/comment/checklist in English.
- Experience level: {level} - adjust technical depth accordingly.
- Confidence: 0-100 based on how well evidence supports the plan.
- Unknowns: list genuine uncertainties.

EVIDENCE (only what you actually read):
{evidence}

Return ONLY valid JSON. No markdown fences, no extra text."""


# ============================================================================
# Agent Loop
# ============================================================================

def run_agent_loop(ctx: RepoContext, issue_text: str, image_data: Optional[bytes],
                  language: str, level: str, token: Optional[str]) -> Tuple[Dict, List[Dict]]:
    """Run the Gemma 4 agent loop and return (final_result, trace_events)."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY environment variable not set.")
    
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Define function declarations
    search_paths_decl = types.FunctionDeclaration(
        name="search_paths",
        description="Search repository file tree for paths matching keywords (comma-separated).",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "keywords": types.Schema(type=types.Type.STRING, description="Comma-separated keywords to search for")
            },
            required=["keywords"]
        )
    )
    
    read_file_decl = types.FunctionDeclaration(
        name="read_file",
        description="Read a file from the repository (up to 250 lines).",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "path": types.Schema(type=types.Type.STRING, description="File path relative to repo root"),
                "start_line": types.Schema(type=types.Type.INTEGER, description="Starting line number (1-indexed)", default=1)
            },
            required=["path"]
        )
    )
    
    read_contributing_decl = types.FunctionDeclaration(
        name="read_contributing",
        description="Read CONTRIBUTING guide and PR template.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={})
    )
    
    tools = types.Tool(function_declarations=[search_paths_decl, read_file_decl, read_contributing_decl])
    config = types.GenerateContentConfig(
        tools=[tools],
        system_instruction=SYSTEM_PROMPT,
        temperature=0.3,
        # Don't enable automatic function calling - we run the loop manually
    )
    
    # Build initial message
    initial_text = build_initial_user_message(ctx, issue_text, image_data is not None, language, level)
    
    # Prepare content parts
    parts = [types.Part.from_text(text=initial_text)]
    if image_data:
        parts.append(types.Part.from_bytes(data=image_data, mime_type="image/png"))
    
    # History for conversation
    history = [
        types.Content(role="user", parts=parts),
    ]
    
    trace_events = []
    evidence_collected: List[AgentEvidence] = []
    turn = 0
    
    while turn < MAX_TURNS:
        turn += 1
        logger.info(f"Agent turn {turn}")
        
        try:
            print(f"[DEBUG] Calling model: {GEMMA_MODEL} with key: {GEMINI_API_KEY[:20]}...")
            response = client.models.generate_content(
                model=GEMMA_MODEL,
                contents=history,
                config=config
            )
            print(f"[DEBUG] Model call succeeded")
        except Exception as e:
            logger.error(f"Model call failed: {e}")
            # Try fallback model
            try:
                print(f"[DEBUG] Trying fallback model: {FALLBACK_MODEL}")
                response = client.models.generate_content(
                    model=FALLBACK_MODEL,
                    contents=history,
                    config=config
                )
                print(f"[DEBUG] Fallback model call succeeded")
            except Exception as e2:
                raise ValueError(f"Model call failed: {e2}")
        
        # Add model response to history
        if response.candidates:
            model_content = response.candidates[0].content
            history.append(model_content)
            
            # Check for function calls
            function_calls = []
            for part in model_content.parts:
                if part.function_call:
                    function_calls.append(part.function_call)
            
            if function_calls:
                # Execute all function calls
                tool_results = []
                for fc in function_calls:
                    name = fc.name
                    args = dict(fc.args) if fc.args else {}
                    
                    trace_events.append({
                        "type": "tool",
                        "name": name,
                        "args": args,
                        "summary": ""
                    })
                    
                    if name == "search_paths":
                        result = tool_search_paths(ctx, args.get("keywords", ""))
                        summary = f"Found {result['count']} matching paths"
                    elif name == "read_file":
                        result = tool_read_file(ctx, ctx.owner, ctx.repo, ctx.default_branch,
                                               args.get("path", ""), args.get("start_line", 1), token)
                        if result.get("valid"):
                            summary = f"Read {result['path']} lines {result['start_line']}-{result['end_line']}"
                            evidence_collected.append(AgentEvidence(
                                path=result["path"],
                                start_line=result["start_line"],
                                end_line=result["end_line"],
                                content=result["content"]
                            ))
                        else:
                            summary = f"Error reading {args.get('path')}: {result.get('error')}"
                    elif name == "read_contributing":
                        result = tool_read_contributing(ctx, ctx.owner, ctx.repo, ctx.default_branch, token)
                        summary = "Read CONTRIBUTING and PR template"
                    else:
                        result = {"error": f"Unknown tool: {name}"}
                        summary = f"Unknown tool: {name}"
                    
                    trace_events[-1]["summary"] = summary
                    tool_results.append(types.Part.from_function_response(
                        name=name,
                        response={"result": result}
                    ))
                
                # Add tool results to history
                history.append(types.Content(role="user", parts=tool_results))
                continue  # Next turn
            
            # Check for READY signal
            text_content = ""
            for part in model_content.parts:
                if part.text:
                    text_content += part.text
            
            if "READY" in text_content.strip():
                logger.info("Agent signaled READY")
                break
        else:
            logger.warning("No candidates in response")
            break
    
    # Build evidence digest for final call
    evidence_text = ""
    for ev in evidence_collected:
        evidence_text += f"\n--- File: {ev.path} (lines {ev.start_line}-{ev.end_line}) ---\n{ev.content}\n"
    
    # Final structured answer call
    final_prompt = FINAL_PROMPT_TEMPLATE.format(
        language=language,
        level=level,
        evidence=evidence_text or "No evidence collected."
    )
    
    final_config = types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json"
    )
    
    try:
        final_response = client.models.generate_content(
            model=GEMMA_MODEL,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=final_prompt)])],
            config=final_config
        )
        final_text = final_response.text or ""
        result = extract_json(final_text)
        
        if result is None:
            # Retry without JSON mode
            final_config_no_json = types.GenerateContentConfig(temperature=0.2)
            final_response = client.models.generate_content(
                model=GEMMA_MODEL,
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=final_prompt)])],
                config=final_config_no_json
            )
            final_text = final_response.text or ""
            result = extract_json(final_text)
            
            if result is None:
                raise ValueError("Gemma returned an unreadable answer. Please try again.")
    
    except Exception as e:
        if "response_mime_type" in str(e) or "JSON" in str(e):
            # Retry without JSON mode
            final_config_no_json = types.GenerateContentConfig(temperature=0.2)
            final_response = client.models.generate_content(
                model=GEMMA_MODEL,
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=final_prompt)])],
                config=final_config_no_json
            )
            final_text = final_response.text or ""
            result = extract_json(final_text)
            if result is None:
                raise ValueError("Gemma returned an unreadable answer. Please try again.")
        else:
            raise
    
    # Verification pass
    verified_files = []
    for f in result.get("files", []):
        path = f.get("path", "")
        verified = ctx.is_valid_path(path)
        read_by_agent = path in ctx.files_read_by_agent
        url = f"https://github.com/{ctx.owner}/{ctx.repo}/blob/{ctx.default_branch}/{path}" if verified else ""
        verified_files.append({
            **f,
            "verified": verified,
            "read_by_agent": read_by_agent,
            "url": url
        })
    result["files"] = verified_files
    
    # Add repo info
    result["repo"] = f"{ctx.owner}/{ctx.repo}"
    result["files_read"] = list(ctx.files_read_by_agent)
    
    return result, trace_events


# ============================================================================
# Flask Routes
# ============================================================================

@app.route("/")
def index():
    return send_file("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """Main analysis endpoint - streams NDJSON."""
    repo_input = request.form.get("repo", "").strip()
    issue_text = request.form.get("issue", "").strip()
    level = request.form.get("level", "beginner")
    language = request.form.get("language", "English")
    token = request.form.get("token", "").strip() or None
    
    image_file = request.files.get("image")
    image_data = None
    if image_file:
        # Validate image
        if image_file.content_type not in ["image/png", "image/jpeg", "image/webp"]:
            return Response(
                json.dumps({"type": "error", "text": "Invalid image type. Use PNG, JPEG, or WebP."}) + "\n",
                mimetype="application/x-ndjson",
                status=400
            )
        image_data = image_file.read()
        if len(image_data) > 5 * 1024 * 1024:
            return Response(
                json.dumps({"type": "error", "text": "Image too large. Maximum 5 MB."}) + "\n",
                mimetype="application/x-ndjson",
                status=400
            )
    
    if not repo_input:
        return Response(
            json.dumps({"type": "error", "text": "Paste a link like https://github.com/owner/repo"}) + "\n",
            mimetype="application/x-ndjson",
            status=400
        )
    
    if not issue_text and not image_data:
        return Response(
            json.dumps({"type": "error", "text": "Provide an issue description or a screenshot."}) + "\n",
            mimetype="application/x-ndjson",
            status=400
        )
    
    def generate():
        try:
            # Parse repo
            yield json.dumps({"type": "step", "text": "Parsing repository link..."}) + "\n"
            owner, repo = parse_repo_url(repo_input)
            
            # Fetch repo metadata
            yield json.dumps({"type": "step", "text": f"Fetching {owner}/{repo} metadata..."}) + "\n"
            meta = fetch_repo_metadata(owner, repo, token)
            default_branch = meta.get("default_branch", "main")
            
            # Fetch tree
            yield json.dumps({"type": "step", "text": "Fetching file tree..."}) + "\n"
            raw_tree = fetch_tree(owner, repo, default_branch, token)
            filtered_tree = filter_tree(raw_tree)
            tree_map = build_tree_map(filtered_tree)
            
            yield json.dumps({"type": "step", "text": f"Indexed {len(filtered_tree)} files"}) + "\n"
            
            # Fetch README
            readme = fetch_readme(owner, repo, default_branch, token)
            
            # Build context
            ctx = RepoContext(
                owner=owner,
                repo=repo,
                default_branch=default_branch,
                tree=filtered_tree,
                tree_map=tree_map,
                readme_excerpt=readme
            )
            
            # Run agent
            yield json.dumps({"type": "step", "text": "Starting Gemma 4 agent..."}) + "\n"
            result, trace_events = run_agent_loop(ctx, issue_text, image_data, language, level, token)
            
            # Send trace events
            for event in trace_events:
                yield json.dumps(event) + "\n"
            
            # Send final result
            yield json.dumps({"type": "result", "data": result}) + "\n"
            
        except ValueError as e:
            yield json.dumps({"type": "error", "text": str(e)}) + "\n"
        except Exception as e:
            logger.exception("Analysis error")
            yield json.dumps({"type": "error", "text": f"Analysis failed: {str(e)}"}) + "\n"
    
    return Response(
        generate(),
        mimetype="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
    )


@app.route("/api/issues", methods=["POST"])
def issues():
    """Issue Radar endpoint."""
    data = request.get_json() or {}
    repo_input = data.get("repo", "").strip()
    token = data.get("token", "").strip() or None
    
    if not repo_input:
        return jsonify({"error": "Paste a link like https://github.com/owner/repo"}), 400
    
    try:
        owner, repo = parse_repo_url(repo_input)
        issues_list = fetch_issues(owner, repo, token)
        
        formatted = []
        for issue in issues_list:
            formatted.append({
                "number": issue["number"],
                "title": issue["title"],
                "url": issue["html_url"],
                "labels": [l["name"] for l in issue.get("labels", [])],
                "comments": issue.get("comments", 0),
                "body": (issue.get("body") or "")[:1200]
            })
        
        source = "good first issue" if any("good first issue" in i["labels"] for i in formatted) else \
                 "help wanted" if any("help wanted" in i["labels"] for i in formatted) else "open issues"
        
        return jsonify({"repo": f"{owner}/{repo}", "source": source, "issues": formatted})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Issues fetch error")
        return jsonify({"error": f"Failed to fetch issues: {str(e)}"}), 400


# Health check
@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print("WARNING: GEMINI_API_KEY not set. Set it in .env or environment.")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)