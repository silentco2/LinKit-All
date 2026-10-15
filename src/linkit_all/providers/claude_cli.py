"""Claude Code CLI (`claude -p`), billed to the user's own Claude plan."""

import json
import tempfile

from linkit_all.providers.base import CLIProvider, ProviderError, classify, run_cli


def parse_output(code: int, out: str, err: str) -> str:
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise classify(err.strip() or out.strip() or f"claude exited with {code}") from None
    if code != 0 or data.get("is_error"):
        raise classify(str(data.get("result") or err or f"claude exited with {code}"))
    result = data.get("result")
    if not isinstance(result, str):
        raise ProviderError("claude: no result in output")
    return result


class ClaudeCLI(CLIProvider):
    name = "claude_cli"
    binary = "claude"

    async def _call(self, prompt: str) -> str:
        cmd = [
            self.path(),
            "-p",
            "--output-format", "json",
            "--tools", "",  # no built-in tools
            "--strict-mcp-config",  # no MCP servers
            "--setting-sources", "",  # skip user hooks/plugins/settings
            "--no-session-persistence",
        ]  # fmt: skip
        if self.model:
            cmd += ["--model", self.model]
        with tempfile.TemporaryDirectory(prefix="linkit-claude-") as tmp:
            return parse_output(*await run_cli(cmd, prompt, tmp, self.timeout_s))
