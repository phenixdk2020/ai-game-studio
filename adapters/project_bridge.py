"""One task/result contract for Ollama, local Copilot and GitHub agent tasks.

No queue access. The PowerShell orchestrator owns queue transactions. This adapter
owns per-task receipts, isolated checkouts, external jobs and local validation.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import uuid

from asset_pipeline import ROOT, contained, read_json, task_lock, write_json

BACKENDS = {"ollama", "copilot-local", "copilot-github"}
PROTECTED = {"tasks", "results", "logs", "state"}


def now():
    return datetime.now(timezone.utc)


def role_name(name):
    aliases = {"auto": "project_manager", "project-manager": "project_manager", "research-agent": "historical_research",
               "historical-research-agent": "historical_research", "blender-agent": "character3d",
               "pinokio-hunyuan3d-agent": "character3d", "gameplay-ai-agent": "gameplay",
               "hud-ui-agent": "gameplay"}
    return aliases.get(name, (name or "project_manager").removesuffix("-agent").replace("-", "_"))


def validate(task, config):
    if not isinstance(task, dict) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", str(task.get("id", ""))):
        raise ValueError("Invalid task id")
    if not isinstance(task.get("id"), str) or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", task["id"], re.I):
        raise ValueError("Invalid task id")
    backend = task.get("backend")
    if backend not in BACKENDS:
        raise ValueError("Select ollama, copilot-local or copilot-github")
    for key in ("title", "description"):
        if not isinstance(task.get(key), str) or not task[key].strip():
            raise ValueError(f"Task requires {key}")
    role = role_name(task.get("role") or task.get("agent"))
    if role not in config["roles"]:
        raise ValueError(f"Unknown specialist role: {role}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", config["repository"]):
        raise ValueError("Invalid configured GitHub repository")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", config["base_branch"]) or ".." in config["base_branch"]:
        raise ValueError("Invalid configured base branch")
    for key in ("command_timeout", "poll_seconds"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"Invalid {key}")
    commands = config.get("validation_commands")
    if not isinstance(commands, list) or not commands or any(
        not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg for arg in command)
        for command in commands
    ):
        raise ValueError("Configure argument-array validation_commands")
    root = Path(config["jobs_root"])
    if not root.is_absolute():
        root = ROOT / root
    directory = contained(root / task["id"], root)
    source = {key: task.get(key, default) for key, default in (
        ("title", ""), ("description", ""), ("attachments", []), ("projectPath", ""), ("dependencyResults", []))}
    if not isinstance(source["attachments"], list) or any(not isinstance(path, str) for path in source["attachments"]):
        raise ValueError("attachments must be an array of paths")
    payload = {"source": source, "backend": backend, "role": role, "kind": task.get("kind", "task"),
               "repository": config["repository"], "base": config["base_branch"]}
    signature = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return directory, role, source, signature


def pr_number(url, repository):
    match = re.fullmatch(r"https://github\.com/" + re.escape(repository) + r"/pull/([1-9][0-9]*)", url or "")
    if not match:
        raise ValueError("PR URL must belong to the configured repository")
    return int(match.group(1))


def normalize_plan(value, parent, source, roles):
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```json") and text.endswith("```"):
            text = text[7:-3].strip()
        value = json.loads(text)
    steps = value.get("tasks") if isinstance(value, dict) else None
    if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
        raise ValueError("Planner must return 1..12 tasks")
    keys = [step.get("key") for step in steps if isinstance(step, dict)]
    if len(keys) != len(steps) or any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", key) for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("Plan keys must be unique identifiers")
    mapping = {key: "TASK-" + uuid.uuid4().hex[:20].upper() for key in keys}
    graph = {}
    rows = []
    for step in steps:
        if step.get("backend") not in BACKENDS | {"asset3d"} or step.get("role") not in roles:
            raise ValueError("Plan contains an unsupported backend or role")
        if any(not isinstance(step.get(key), str) or not step[key].strip() for key in ("title", "description")):
            raise ValueError("Every planned task requires title and description")
        deps = step.get("dependencies", [])
        if not isinstance(deps, list) or any(key not in mapping or key == step["key"] for key in deps):
            raise ValueError("Invalid plan dependencies")
        graph[step["key"]] = deps
        rows.append({"schemaVersion": 1, "id": mapping[step["key"]], "parentId": parent,
            "title": step["title"], "description": step["description"], "role": step["role"],
            "agent": step["role"], "backend": step["backend"], "kind": "task", "status": "Queued",
            "dependencies": [mapping[key] for key in deps], "attachments": source["attachments"],
            "projectPath": source["projectPath"], "createdAt": now().isoformat(), "priority": 10})
    resolved = set()
    while len(resolved) < len(graph):
        ready = {key for key, deps in graph.items() if set(deps) <= resolved}
        if ready <= resolved:
            raise ValueError("Cyclic plan dependencies")
        resolved |= ready
    return {"schemaVersion": 1, "parentId": parent, "source": source, "tasks": rows}


class Bridge:
    def __init__(self, task, config, runner=subprocess.run, http=None):
        self.task, self.config, self.runner = task, config, runner
        self.directory, self.role, self.source, self.signature = validate(task, config)
        self.path = self.directory / "bridge"
        self.receipt_path = self.path / "receipt.json"
        self.http = http or self.request_llm

    def tool(self, name):
        value = self.config[name + "_executable"]
        found = shutil.which(value)
        if not found:
            raise ValueError(f"Executable not found: {value}")
        return found

    def command(self, args, label, cwd=None, timeout=None, check=True):
        result = self.runner(args, cwd=str(cwd or ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout or self.config["command_timeout"],
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"})
        (self.path / (label + ".stdout.txt")).write_text(result.stdout or "", encoding="utf-8")
        (self.path / (label + ".stderr.txt")).write_text(result.stderr or "", encoding="utf-8")
        if check and result.returncode:
            raise RuntimeError(f"{label} failed ({result.returncode}); see bridge/{label}.stderr.txt")
        return result

    def save(self, receipt):
        receipt["updatedAt"] = now().isoformat()
        write_json(self.receipt_path, receipt)

    def result(self, receipt):
        return {"schemaVersion": 1, "taskId": self.task["id"], "status": receipt["status"],
            "backend": self.task["backend"], "role": self.role, "pipelineStage": receipt.get("stage", "bridge"),
            "resultPath": receipt.get("resultPath", str(self.path)), "bridgeReceipt": str(self.receipt_path),
            "prUrl": receipt.get("prUrl", ""), "sessionId": receipt.get("sessionId", ""),
            "validatedHead": receipt.get("validatedHead", ""), "error": receipt.get("error", ""),
            "question": receipt.get("question", ""), "nextPollAt": receipt.get("nextPollAt", "")}

    def prompt(self):
        instructions = (ROOT / "agents" / (self.role + ".md")).read_text(encoding="utf-8-sig")
        prompt = (f"AI Game Studio task {self.task['id']}\nRole: {self.role}\n\n{instructions}\n\n"
            f"Title: {self.source['title']}\nTask: {self.source['description']}\n\n"
            "Read and obey AGENTS.md. Preserve unrelated work. Do not modify tasks/, results/, logs/ or state/. "
            "Never merge or force-push. Work only on this task. Return changes through a pull request. "
            "Local Blender/Unreal execution evidence is collected separately by the studio runner.\n")
        if self.source["attachments"]:
            prompt += "Reference paths (do not claim to have read unavailable files):\n" + json.dumps(self.source["attachments"]) + "\n"
            if self.task['backend'] == 'copilot-github':
                prompt += "Local absolute paths are unavailable remotely; request repository-accessible references where needed.\n"
        if self.source['dependencyResults']:
            prompt += '\nApproved dependency results:\n' + json.dumps(self.source['dependencyResults'], ensure_ascii=False) + '\n'
        return prompt

    def request_llm(self, payload):
        config = read_json(ROOT / "config" / "studio.json")["llm"]
        request = urllib.request.Request(config["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json",
                "Authorization": "Bearer " + config.get("api_key", "local")})
        with urllib.request.urlopen(request, timeout=config.get("timeout_seconds", 600)) as response:
            return json.load(response)

    def ollama(self, receipt):
        llm = read_json(ROOT / "config" / "studio.json")["llm"]
        model = llm["models"][llm["routing"].get(self.role, "light")]
        instructions = self.prompt()
        planning = self.task.get("kind") == "plan"
        if planning:
            instructions += ('\nReturn only JSON {"tasks":[{"key":"step1","title":"...","description":"...",'
                '"role":"project_manager","backend":"ollama","dependencies":[]}]}. '
                'Use 1..12 tasks, acyclic dependency keys, explicit backends ollama/asset3d/copilot-local/copilot-github. '
                'Do not claim execution. Allowed roles: ' + ", ".join(self.config["roles"]))
        answer = self.http({"model": model, "temperature": 0.2, "messages": [
            {"role": "system", "content": instructions}, {"role": "user", "content": self.source["description"]}]})
        content = answer["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty model result")
        if planning:
            plan = normalize_plan(content, self.task["id"], self.source, self.config["roles"])
            target = self.path / "plan.json"
            write_json(target, plan)
        else:
            target = self.path / "result.md"
            target.write_text(content, encoding="utf-8")
        receipt.update(status="AwaitingPlanReview" if planning else "AwaitingVisualReview",
            stage="plan-review" if planning else "specialist-review", resultPath=str(target), model=model,
            question="Review the generated plan before applying child tasks." if planning else "Review the specialist result; model text is not execution evidence.")

    def clone(self, receipt):
        checkout = self.path / ("checkout-" + uuid.uuid4().hex[:12])
        self.command([self.tool("git"), "clone", "--no-checkout", "https://github.com/" + self.config["repository"] + ".git", str(checkout)], "clone")
        receipt["checkout"] = str(checkout)
        self.save(receipt)
        return checkout

    def local_copilot(self, receipt):
        checkout = self.clone(receipt)
        branch = "studio/" + self.task["id"].lower() + "-" + uuid.uuid4().hex[:8]
        git = self.tool("git")
        self.command([git, "checkout", "-b", branch, "origin/" + self.config["base_branch"]], "local-branch", checkout)
        receipt.update(branch=branch, stage="copilot-local", status="Running")
        self.save(receipt)  # A crash after this point must not start another coding session.
        session = str(uuid.uuid4())
        receipt["sessionId"] = session
        self.save(receipt)
        self.command([self.tool("copilot"), "-C", str(checkout), "--trust-folder", "--session-id", session,
            "--no-auto-update", "--disable-builtin-mcps", "--no-remote", "--no-ask-user", "--allow-all-tools",
            "--deny-tool=shell(git push)", "--deny-tool=shell(gh pr create)", "--output-format=json",
            "--log-dir", str(self.path / "copilot-logs"), "-p", self.prompt()], "copilot", checkout)
        changed = self.command([git, "status", "--porcelain", "--untracked-files=all"], "local-status", checkout).stdout
        committed = self.command([git, 'diff', '--name-only', 'origin/' + self.config['base_branch'], 'HEAD'], 'local-committed', checkout).stdout
        if not changed.strip() and not committed.strip():
            raise RuntimeError("Copilot returned no code changes; no PR was published")
        receipt["stage"] = "local-validation"
        self.save(receipt)
        if changed.strip():
            self.command([git, "add", "--all"], "stage", checkout)
            self.command([git, "commit", "-m", f"{self.task['id']}: {self.task['title']}"], "commit", checkout)
        self.validate_checkout(checkout, receipt)
        receipt.update(stage="publishing", branch=branch)
        self.save(receipt)
        self.command([git, "push", "origin", "HEAD:refs/heads/" + branch], "push", checkout)
        body = self.path / "pr-body.md"
        body.write_text(f"Task {self.task['id']}: {self.task['description']}\n\nLocal validation passed. Studio receipt: {self.task['id']}.\n", encoding="utf-8")
        result = self.command([self.tool("github"), "pr", "create", "--repo", self.config["repository"],
            "--base", self.config["base_branch"], "--head", branch, "--draft", "--title", self.task["title"],
            "--body-file", str(body)], "create-pr", checkout)
        receipt["prUrl"] = self.parse_url(result.stdout)
        receipt["validatedHead"] = self.command([git, "rev-parse", "HEAD"], "local-head", checkout).stdout.strip()
        receipt.update(status="AwaitingCodeReview", stage="code-review", resultPath=str(self.path / "validation.json"),
                       question="Local tests passed; review the draft PR. No merge or local installation update was performed.")

    def parse_url(self, text):
        urls = re.findall(r"https://github\.com/" + re.escape(self.config["repository"]) + r"/pull/[1-9][0-9]*", text)
        if len(set(urls)) != 1:
            raise ValueError("Dispatch returned no unambiguous PR URL; reconcile receipt before retrying")
        pr_number(urls[0], self.config["repository"])
        return urls[0]

    def github_start(self, receipt):
        prompt_path = self.path / "prompt.md"
        prompt_path.write_text(self.prompt(), encoding="utf-8")
        receipt.update(status="Dispatching", stage="github-dispatch")
        self.save(receipt)  # Prevent duplicate submissions after an interrupted/ambiguous request.
        result = self.command([self.tool("github"), "agent-task", "create", "--repo", self.config["repository"],
            "--base", self.config["base_branch"], "--from-file", str(prompt_path)], "github-dispatch")
        receipt.update(prUrl=self.parse_url(result.stdout), status="WaitingForRemote", stage="github-session")
        receipt["nextPollAt"] = now().isoformat()

    def github_poll(self, receipt):
        if datetime.fromisoformat(receipt.get("nextPollAt", now().isoformat())) > now():
            return
        ref = receipt.get("sessionId") or receipt["prUrl"]
        result = self.command([self.tool("github"), "agent-task", "view", ref, "--repo", self.config["repository"],
            "--json", "id,state,pullRequestUrl,updatedAt"], "github-session")
        session = json.loads(result.stdout)
        if isinstance(session, list):
            if len(session) != 1:
                raise ValueError("Multiple GitHub sessions; bind one explicit session before continuing")
            session = session[0]
        if not isinstance(session.get("id"), str) or not session["id"] or session["id"].startswith("-"):
            raise ValueError("GitHub session id is missing")
        if receipt.get("sessionId") and receipt["sessionId"] != session["id"]:
            raise ValueError("GitHub session changed unexpectedly")
        receipt["sessionId"] = session["id"]
        if session.get("pullRequestUrl") != receipt["prUrl"]:
            raise ValueError("Session/PR mismatch")
        state = str(session.get("state", "")).lower()
        receipt.update(remoteState=state, nextPollAt=(now() + timedelta(seconds=self.config["poll_seconds"])).isoformat())
        self.save(receipt)
        if state in {"queued", "pending", "running", "in_progress"}:
            return
        if state in {"completed", "success", "succeeded"}:
            self.github_validate(receipt)
        elif state in {"failed", "failure", "cancelled", "canceled", "timed_out"}:
            receipt.update(status="Failed", error="GitHub session ended: " + state)
        else:
            receipt.update(status="NeedsInput", error="Unrecognized GitHub session state: " + state)

    def validate_checkout(self, checkout, receipt):
        git = self.tool("git")
        before = self.command([git, "diff", "HEAD", "--binary"], "before-tests", checkout).stdout
        head = self.command([git, "rev-parse", "HEAD"], "before-head", checkout).stdout.strip()
        self.command([git, "diff", "--check"], "diff-check", checkout)
        self.command([git, 'diff', '--check', 'origin/' + self.config['base_branch'], 'HEAD'], 'committed-diff-check', checkout)
        tracked = self.command([git, "diff", "--name-only", "origin/" + self.config["base_branch"], "HEAD"], "changed-tracked", checkout).stdout.splitlines()
        working = self.command([git, "diff", "--name-only", "HEAD"], "changed-working", checkout).stdout.splitlines()
        untracked = self.command([git, "ls-files", "--others", "--exclude-standard"], "changed-new", checkout).stdout.splitlines()
        if any(Path(path).parts and Path(path).parts[0].lower() in PROTECTED for path in tracked + working + untracked):
            raise ValueError("Coding task changed protected runtime paths")
        checks = []
        for index, arguments in enumerate(self.config["validation_commands"]):
            args = list(arguments)
            if args[0] == "python":
                args[0] = sys.executable
            self.command(args, f"validation-{index}", checkout)
            checks.append({"arguments": arguments, "status": "pass"})
        after = self.command([git, "diff", "HEAD", "--binary"], "after-tests", checkout).stdout
        new_after = self.command([git, 'ls-files', '--others', '--exclude-standard'], 'after-new', checkout).stdout.splitlines()
        if before != after or untracked != new_after or head != self.command([git, "rev-parse", "HEAD"], "after-head", checkout).stdout.strip():
            raise ValueError("Validation modified the submitted code; review and validate again")
        write_json(self.path / "validation.json", {"schemaVersion": 1, "taskId": self.task["id"],
            "status": "pass", "head": head, "checkout": str(checkout), "checks": checks, "completedAt": now().isoformat()})

    def github_validate(self, receipt):
        metadata = json.loads(self.command([self.tool("github"), "pr", "view", receipt["prUrl"], "--repo", self.config["repository"],
            "--json", "url,headRefOid,baseRefName,isCrossRepository,state"], "pr-metadata").stdout)
        if metadata.get("url") != receipt["prUrl"] or metadata.get("isCrossRepository") is not False or metadata.get("baseRefName") != self.config["base_branch"]:
            raise ValueError("PR repository/base mismatch; local checkout refused")
        sha = metadata.get("headRefOid", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid PR head SHA")
        checkout = self.clone(receipt)
        git = self.tool("git")
        number = pr_number(receipt["prUrl"], self.config["repository"])
        self.command([git, "fetch", "origin", f"refs/pull/{number}/head"], "fetch-pr", checkout)
        self.command([git, "checkout", "--detach", "FETCH_HEAD"], "checkout-pr", checkout)
        actual = self.command([git, "rev-parse", "HEAD"], "checkout-head", checkout).stdout.strip()
        if actual != sha:
            raise ValueError("PR changed while fetching; validate the new head explicitly")
        receipt.update(stage="local-validation", status="Running", validatedHead=sha)
        self.save(receipt)
        self.validate_checkout(checkout, receipt)
        receipt.update(status="AwaitingCodeReview", stage="code-review", resultPath=str(self.path / "validation.json"),
                       question="GitHub code was checked out and tested locally at the recorded SHA. Review the PR; no merge/deployment was performed.")

    def verify_review(self):
        receipt = read_json(self.receipt_path)
        if receipt.get('signature') != self.signature or receipt.get('status') != 'AwaitingCodeReview':
            raise ValueError('No current validated code result')
        metadata = json.loads(self.command([self.tool('github'), 'pr', 'view', receipt['prUrl'], '--repo', self.config['repository'], '--json', 'url,headRefOid,baseRefName,isCrossRepository,state'], 'review-head').stdout)
        if (metadata.get('url') != receipt['prUrl'] or metadata.get('headRefOid') != receipt.get('validatedHead')
                or metadata.get('baseRefName') != self.config['base_branch'] or metadata.get('isCrossRepository') is not False):
            raise ValueError('PR changed since validation; revalidate before approval')
        if metadata.get('state') != 'MERGED':
            raise ValueError('Merge the reviewed PR before completing this task and releasing dependent code tasks')
        return {'taskId': self.task['id'], 'status': 'Verified', 'validatedHead': receipt['validatedHead']}

    def advance(self, approved=False, revalidate=False, bind_session=None, bind_pr=None):
        if not approved:
            return {"taskId": self.task["id"], "status": "WaitingForApproval", "backend": self.task["backend"],
                    "question": "Enable specialist/code backends before dispatching this task."}
        self.directory.mkdir(parents=True, exist_ok=True)
        with task_lock(self.directory):
            self.path.mkdir(exist_ok=True)
            receipt = read_json(self.receipt_path) if self.receipt_path.exists() else None
            if receipt and receipt.get("signature") != self.signature:
                raise ValueError("Task inputs changed after dispatch; create a new task to preserve the original receipt")
            if revalidate or bind_session or bind_pr:
                if not receipt or self.task['backend'] not in {'copilot-local','copilot-github'}:
                    raise ValueError('No existing coding receipt to reconcile')
                if bind_pr:
                    pr_number(bind_pr, self.config['repository'])
                    receipt['prUrl'] = bind_pr
                if bind_session:
                    if self.task['backend'] != 'copilot-github' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}', bind_session):
                        raise ValueError('Invalid GitHub session id')
                    receipt['sessionId'] = bind_session
                if not receipt.get('prUrl'):
                    raise ValueError('Bind the existing PR before retrying; do not dispatch twice')
                receipt.update(error='', question='', status='WaitingForRemote', nextPollAt=now().isoformat())
                if revalidate:
                    try:
                        self.github_validate(receipt)
                    except Exception as error:
                        receipt.update(status='Failed', error=str(error))
                    self.save(receipt)
                    return self.result(receipt)
                self.save(receipt)
            if receipt and receipt["status"] in {"Prepared", "Dispatching", "Running"}:
                receipt.update(status="NeedsInput", error="Interrupted external execution; reconcile existing session/checkout before resubmitting")
                self.save(receipt)
                return self.result(receipt)
            if receipt and receipt["status"] != "WaitingForRemote":
                return self.result(receipt)
            if not receipt:
                receipt = {"schemaVersion": 1, "taskId": self.task["id"], "signature": self.signature,
                    "backend": self.task["backend"], "status": "Prepared", "createdAt": now().isoformat()}
                self.save(receipt)
            try:
                if receipt["status"] == "WaitingForRemote":
                    self.github_poll(receipt)
                elif self.task["backend"] == "ollama":
                    receipt.update(status="Running", stage="specialist")
                    self.save(receipt)
                    self.ollama(receipt)
                elif self.task["backend"] == "copilot-local":
                    self.local_copilot(receipt)
                else:
                    self.github_start(receipt)
            except Exception as error:
                ambiguous = receipt["status"] in {"Dispatching", "Running"} and receipt.get("stage") in {"github-dispatch", "copilot-local", "publishing"}
                receipt.update(status="NeedsInput" if ambiguous else "Failed", error=str(error),
                               question="Review the receipt and logs before retrying; no automatic redispatch occurs.")
            self.save(receipt)
            return self.result(receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", type=Path)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "orchestrator.json")
    parser.add_argument("--approve-dispatch", action="store_true")
    parser.add_argument('--revalidate', action='store_true')
    parser.add_argument('--bind-session')
    parser.add_argument('--bind-pr')
    parser.add_argument('--verify-review', action='store_true')
    parser.add_argument("--plan", action="store_true", help="Show backend/role without dispatch or filesystem writes")
    args = parser.parse_args()
    try:
        bridge = Bridge(read_json(args.task), read_json(args.config))
        result = {"taskId": bridge.task["id"], "backend": bridge.task["backend"], "role": bridge.role,
                  "directory": str(bridge.directory)} if args.plan else (bridge.verify_review() if args.verify_review else bridge.advance(args.approve_dispatch, args.revalidate, args.bind_session, args.bind_pr))
        print(json.dumps(result))
        return 0
    except Exception as error:
        print(json.dumps({"status": "Failed", "error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
