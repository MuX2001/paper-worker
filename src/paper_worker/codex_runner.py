import json
import os
import shlex
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

from .config import Config
from .schemas import PaperAnalysis


def extract_analysis(text: str) -> PaperAnalysis:
    decoder = json.JSONDecoder()
    errors = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
            return PaperAnalysis.model_validate_json(json.dumps(obj))
        except (ValueError, TypeError) as exc:
            errors.append(str(exc))
    raise ValueError(
        "No valid PaperAnalysis JSON found: " + (errors[0][:3000] if errors else "no JSON object")
    )


def command_args(command: str) -> list[str]:
    args = shlex.split(command, posix=os.name != "nt")
    args = [arg.strip('"') for arg in args]
    if not args:
        raise ValueError("Codex command is empty")
    # Prefer native Windows executable: npm .cmd shims need a shell and break quoting.
    if os.name == "nt" and Path(args[0]).stem.lower() == "codex":
        shim = shutil.which("codex.cmd")
        if shim:
            native = list(
                (Path(shim).parent / "node_modules/@openai/codex/node_modules").glob(
                    "@openai/codex-win32-*/vendor/*/bin/codex.exe"
                )
            )
            if native:
                args[0] = str(native[0])
    return args


def run_codex(
    config: Config, workspace: Path, pdf: Path, repo: Path | None, log=print
) -> PaperAnalysis:
    args = command_args(config.codex_command)
    # Current CLI replaces --full-auto. Preserve compatibility with older installs.
    if "--full-auto" in args:
        help_result = subprocess.run(
            [args[0], "exec", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if help_result.returncode == 0 and "--full-auto" not in help_result.stdout:
            args.remove("--full-auto")
            args.extend(["--sandbox", "read-only"])
    schema_path = workspace / "analysis.schema.json"
    schema = PaperAnalysis.model_json_schema()

    # Structured output requires all properties required, including optional-null values.
    def strict_schema(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
            node.pop("default", None)
            for value in node.values():
                strict_schema(value)
        elif isinstance(node, list):
            for value in node:
                strict_schema(value)

    strict_schema(schema)
    schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
    output = workspace / "codex-result.json"
    prompt = files("paper_worker").joinpath("prompts/audit_prompt.txt").read_text(encoding="utf-8")
    prompt += f"\nPDF: {pdf}\nExtracted full text: {workspace / 'paper.txt'}\nRepository context: {repo or 'No repository link found'}\nSchema: {schema_path}\n"
    invocation = args + [
        "--skip-git-repo-check",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output),
        "-",
    ]
    for attempt in range(2):
        output.unlink(missing_ok=True)
        log(f"Codex analysis ({attempt + 1}/2)")
        result = subprocess.run(
            invocation,
            input=prompt,
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.codex_timeout,
        )
        if result.returncode:
            raise RuntimeError(f"Codex exited with {result.returncode}: {result.stderr[-2000:]}")
        text = output.read_text(encoding="utf-8") if output.exists() else result.stdout
        try:
            return extract_analysis(text)
        except ValueError as exc:
            if attempt:
                raise
            prompt += f"\nPrevious output failed validation. Correct it: {exc}\n"
    raise RuntimeError("Unreachable")
