"""OpenAI Codex CLI (`codex exec`), billed to the user's own ChatGPT plan."""

import json
import tempfile
from pathlib import Path

from linkit_all.providers.base import CLIProvider, classify, run_cli


def parse_output(code: int, out: str, err: str, last_message: str) -> str:
    if code == 0 and last_message.strip():
        return last_message
    errors = []
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "error":
            errors.append(str(event.get("message", "")))
        elif event.get("type") == "turn.failed":
            errors.append(str((event.get("error") or {}).get("message", "")))
    raise classify("; ".join(filter(None, errors)) or err.strip() or f"codex exited with {code}")


class CodexCLI(CLIProvider):
    name = "codex_cli"
    binary = "codex"

    async def _call(self, prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="linkit-codex-") as tmp:
            last = Path(tmp) / "last_message.txt"
            cmd = [
                self.path(),
                "exec",
                "--json",
                "--sandbox", "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",  # no user MCP servers; auth still works
                "--ignore-rules",
                "--color", "never",
                "-C", tmp,
                "-o", str(last),
            ]  # fmt: skip
            if self.model:
                cmd += ["-m", self.model]
            cmd.append("-")  # prompt from stdin
            code, out, err = await run_cli(cmd, prompt, tmp, self.timeout_s)
            text = last.read_text("utf-8") if last.exists() else ""
        return parse_output(code, out, err, text)
