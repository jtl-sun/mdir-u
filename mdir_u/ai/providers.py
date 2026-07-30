from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


ANSI_ESCAPE_RE = re.compile(
    r"(?:\x1b\][^\x07]*(?:\x07|\x1b\\))"
    r"|(?:\x1bP.*?\x1b\\)"
    r"|(?:\x1b\[[0-?]*[ -/]*[@-~])"
    r"|(?:\x1b[@-_])",
    re.DOTALL,
)
OLLAMA_SPINNER_RE = re.compile(r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]\s*")


def sanitize_terminal_output(text: str) -> str:
    """Convert cursor-oriented CLI output into plain text for the AI log."""
    text = ANSI_ESCAPE_RE.sub("", text)
    rendered: list[str] = []
    line_start = 0

    for character in text:
        if character == "\r":
            del rendered[line_start:]
        elif character == "\n":
            rendered.append(character)
            line_start = len(rendered)
        elif character == "\b":
            if len(rendered) > line_start:
                rendered.pop()
        elif character == "\t" or ord(character) >= 32:
            rendered.append(character)

    return "".join(rendered)


@dataclass(frozen=True)
class AIEvent:
    kind: str
    text: str = ""
    session_id: Optional[str] = None


class AIProvider:
    """Base class for safe argv-based AI CLI adapters."""

    name = "AI"
    executable = ""

    @property
    def path_environment_variable(self) -> str:
        return f"MDIR_{self.name.upper()}_PATH"

    def resolve_executable(self) -> Optional[str]:
        """Resolve a provider CLI without assuming that it is on Python's PATH."""
        configured = os.environ.get(self.path_environment_variable, "").strip()
        if configured:
            configured_path = Path(configured).expanduser()
            if configured_path.is_file():
                return str(configured_path)

        found = shutil.which(self.executable) or shutil.which(
            f"{self.executable}.exe"
        )
        return found

    def available(self) -> bool:
        return self.resolve_executable() is not None

    def command_executable(self) -> str:
        return self.resolve_executable() or self.executable

    def connection_status(self) -> tuple[bool, str]:
        executable = self.resolve_executable()
        if executable is None:
            return False, f"{self.name} CLI was not found."
        return True, f"{self.name} CLI is ready: {executable}"

    def login_command(self) -> Optional[list[str]]:
        return None

    def build_command(
        self, prompt: str, cwd: Path, session_id: Optional[str]
    ) -> list[str]:
        raise NotImplementedError

    def parse_line(self, line: str) -> Iterable[AIEvent]:
        if line.strip():
            yield AIEvent("message", line.rstrip())


class CodexProvider(AIProvider):
    name = "Codex"
    executable = "codex"

    def exec_options(self) -> list[str]:
        """Return provider-specific options for `codex exec`."""
        return []

    def resolve_executable(self) -> Optional[str]:
        configured = os.environ.get(self.path_environment_variable, "").strip()
        if configured:
            configured_path = Path(configured).expanduser()
            if configured_path.is_file():
                return str(configured_path)

        found = shutil.which(self.executable) or shutil.which("codex.exe")
        if os.name != "nt":
            return found
        if found and "windowsapps" not in found.lower():
            return found

        # The Codex Windows app ships the CLI outside the normal Python PATH.
        # Prefer the per-user runtime copy because WindowsApps may have ACLs
        # that prevent a child process from launching the package executable.
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            runtime_root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
            try:
                candidates = list(runtime_root.glob("*/codex.exe"))
                if candidates:
                    return str(
                        max(candidates, key=lambda path: path.stat().st_mtime)
                    )
            except OSError:
                pass

        if found:
            return found

        # PowerShell can resolve Microsoft Store/App Execution Alias commands
        # even when shutil.which() cannot see them.
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if powershell:
            try:
                result = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        (
                            "$c=Get-Command codex -ErrorAction SilentlyContinue; "
                            "if($c){$c.Source}"
                        ),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                resolved = result.stdout.strip().splitlines()
                if resolved and Path(resolved[-1]).is_file():
                    return resolved[-1]
            except (OSError, subprocess.SubprocessError):
                pass

        return None

    def build_command(
        self, prompt: str, cwd: Path, session_id: Optional[str]
    ) -> list[str]:
        executable = self.command_executable()
        exec_options = self.exec_options()
        if session_id:
            # `codex exec resume` has its own, smaller option set. In
            # particular it does not accept the new-session-only --sandbox or
            # --cd options; the resumed session retains those settings.
            return [
                executable,
                "exec",
                *exec_options,
                "resume",
                "--json",
                "--skip-git-repo-check",
                session_id,
                prompt,
            ]

        return [
            executable,
            "exec",
            *exec_options,
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(cwd),
            prompt,
        ]

    def connection_status(self) -> tuple[bool, str]:
        executable = self.resolve_executable()
        if executable is None:
            return False, "Codex CLI was not found."
        try:
            result = subprocess.run(
                [executable, "login", "status"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"Could not check Codex login: {exc}"

        output = (result.stdout or result.stderr).strip()
        if result.returncode == 0:
            return True, output or "Codex is signed in."
        return False, output or "Codex is not signed in."

    def login_command(self) -> Optional[list[str]]:
        executable = self.resolve_executable()
        return [executable, "login"] if executable else None

    def parse_line(self, line: str) -> Iterable[AIEvent]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if line.strip():
                yield AIEvent("status", line.rstrip())
            return

        event_type = str(event.get("type", ""))
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            if thread_id:
                yield AIEvent("session", session_id=str(thread_id))
            yield AIEvent("progress", "Connected to Codex")
            return

        if event_type == "turn.started":
            yield AIEvent("progress", "Thinking")
            return

        item = event.get("item")
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type == "agent_message" and item.get("text"):
                yield AIEvent("progress", "Receiving answer")
                yield AIEvent("message", str(item["text"]))
            elif item_type == "reasoning":
                yield AIEvent("progress", "Reasoning")
            elif item_type == "command_execution":
                command = item.get("command", "")
                status = item.get("status", "")
                if command:
                    yield AIEvent("progress", "Running command")
                    yield AIEvent("tool", f"$ {command}  [{status}]")
            elif item_type == "file_change":
                yield AIEvent("progress", "Applying file changes")
                yield AIEvent("tool", "Files changed by Codex.")
            return

        if event_type in {"turn.failed", "error"}:
            message = event.get("message") or event.get("error") or line
            yield AIEvent("error", str(message))


class PowerShellProvider(AIProvider):
    """Direct local PowerShell runner that does not use the Codex sandbox."""

    name = "PowerShell"
    executable = "powershell"

    def resolve_executable(self) -> Optional[str]:
        configured = os.environ.get(self.path_environment_variable, "").strip()
        if configured:
            configured_path = Path(configured).expanduser()
            if configured_path.is_file():
                return str(configured_path)

        if os.name == "nt":
            found = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
            if found:
                return found
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            bundled = (
                Path(system_root)
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            )
            return str(bundled) if bundled.is_file() else None

        return shutil.which("pwsh") or shutil.which("powershell")

    def build_command(
        self, prompt: str, cwd: Path, session_id: Optional[str]
    ) -> list[str]:
        # Force UTF-8 on redirected output so Korean and other Unicode text
        # reaches the Textual log without the active console code page. Refresh
        # PATH from the registry so a newly installed CLI is visible without
        # restarting MDIR.
        script = (
            "$__mdirMachinePath="
            "[Environment]::GetEnvironmentVariable('Path','Machine');"
            "$__mdirUserPath="
            "[Environment]::GetEnvironmentVariable('Path','User');"
            "$env:Path=(@($env:Path,$__mdirMachinePath,$__mdirUserPath)"
            "|Where-Object{$_}) -join ';';"
            "[Console]::OutputEncoding="
            "[System.Text.UTF8Encoding]::new($false);"
            "$OutputEncoding=[Console]::OutputEncoding;"
            + prompt
        )
        return [
            self.command_executable(),
            "-NoLogo",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]

    def connection_status(self) -> tuple[bool, str]:
        executable = self.resolve_executable()
        if executable is None:
            return False, "PowerShell executable was not found."
        try:
            result = subprocess.run(
                [
                    executable,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "$PSVersionTable.PSVersion.ToString()",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"Could not start PowerShell: {exc}"

        version = result.stdout.strip()
        if result.returncode == 0:
            return True, (
                f"Local PowerShell {version or '(unknown version)'} is ready. "
                "Commands run directly, outside the Codex sandbox."
            )
        return False, (result.stderr or "PowerShell failed to start.").strip()

    def parse_line(self, line: str) -> Iterable[AIEvent]:
        # Child CLIs such as Ollama may emit terminal cursor controls through
        # PowerShell. Render them as plain text before writing to the MDIR log.
        text = sanitize_terminal_output(line)
        text = OLLAMA_SPINNER_RE.sub("", text).rstrip("\r\n")
        if text.strip():
            yield AIEvent("output", text)
            if "GGML_SCHED_MAX_SPLIT_INPUTS" in text:
                yield AIEvent(
                    "error",
                    "Gemma 4 GPU/CPU split scheduling crashed. "
                    "Select 'Ollama CPU' in the provider menu and try again.",
                )
            elif "need to be signed in to Ollama" in text:
                yield AIEvent(
                    "error",
                    "Ollama Cloud authentication is required. "
                    "Select 'Ollama Cloud' and press Connect.",
                )


class ShellProvider(AIProvider):
    """Run commands directly in the user's Ubuntu shell."""

    name = "Shell"
    executable = "bash"

    def resolve_executable(self) -> Optional[str]:
        configured = os.environ.get(self.path_environment_variable, "").strip()
        if configured and Path(configured).expanduser().is_file():
            return str(Path(configured).expanduser())
        login_shell = os.environ.get("SHELL", "").strip()
        if login_shell and Path(login_shell).is_file():
            return login_shell
        return (
            shutil.which("bash")
            or shutil.which("zsh")
            or shutil.which("sh")
        )

    def build_command(
        self, prompt: str, cwd: Path, session_id: Optional[str]
    ) -> list[str]:
        return [self.command_executable(), "-lc", prompt]

    def connection_status(self) -> tuple[bool, str]:
        executable = self.resolve_executable()
        if executable is None:
            return False, "No local POSIX shell was found."
        return True, (
            f"Local shell is ready: {executable}. "
            "Commands run directly on this computer, outside the Codex sandbox."
        )

    def parse_line(self, line: str) -> Iterable[AIEvent]:
        text = sanitize_terminal_output(line).rstrip("\r\n")
        if text.strip():
            yield AIEvent("output", text)


class CodexLocalProvider(CodexProvider):
    """Opt-in Codex mode with direct local command execution."""

    name = "Codex Local"

    @property
    def path_environment_variable(self) -> str:
        return "MDIR_CODEX_PATH"

    def build_command(
        self, prompt: str, cwd: Path, session_id: Optional[str]
    ) -> list[str]:
        executable = self.command_executable()
        unrestricted = "--dangerously-bypass-approvals-and-sandbox"
        if session_id:
            return [
                executable,
                "exec",
                "resume",
                "--json",
                "--skip-git-repo-check",
                unrestricted,
                session_id,
                prompt,
            ]

        return [
            executable,
            "exec",
            "--json",
            "--skip-git-repo-check",
            unrestricted,
            "--cd",
            str(cwd),
            prompt,
        ]


class CodexQuickProvider(CodexProvider):
    """Lower-reasoning Codex mode for faster, well-scoped questions."""

    name = "Codex Quick"

    @property
    def path_environment_variable(self) -> str:
        return "MDIR_CODEX_PATH"

    def exec_options(self) -> list[str]:
        effort = os.environ.get(
            "MDIR_CODEX_QUICK_REASONING",
            "low",
        ).strip().lower()
        if effort not in {
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        }:
            effort = "low"
        return ["-c", f'model_reasoning_effort="{effort}"']

    def connection_status(self) -> tuple[bool, str]:
        connected, message = super().connection_status()
        if connected:
            return True, (
                "Codex Quick is ready with low reasoning for faster replies. "
                "Use regular Codex when a task needs deeper analysis."
            )
        return connected, message


class ClaudeProvider(AIProvider):
    name = "Claude"
    executable = "claude"

    def build_command(
        self, prompt: str, cwd: Path, session_id: Optional[str]
    ) -> list[str]:
        return [self.command_executable(), "-p", prompt]


class GeminiProvider(AIProvider):
    name = "Gemini"
    executable = "gemini"

    def build_command(
        self, prompt: str, cwd: Path, session_id: Optional[str]
    ) -> list[str]:
        return [self.command_executable(), "-p", prompt]


class OllamaProvider(AIProvider):
    name = "Ollama"
    executable = "ollama"

    def resolve_executable(self) -> Optional[str]:
        """Find Ollama even before its installer PATH change reaches MDIR."""
        resolved = super().resolve_executable()
        if resolved:
            return resolved

        candidates: list[Path] = []
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(
                Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
            )
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            candidates.append(Path(program_files) / "Ollama" / "ollama.exe")

        for candidate in candidates:
            try:
                if candidate.is_file():
                    return str(candidate)
            except OSError:
                continue
        return None

    def build_command(
        self, prompt: str, cwd: Path, session_id: Optional[str]
    ) -> list[str]:
        model = os.environ.get("MDIR_OLLAMA_MODEL", "qwen3-coder")
        return [self.command_executable(), "run", model, prompt]

    def connection_status(self) -> tuple[bool, str]:
        executable = self.resolve_executable()
        if executable is None:
            return False, "Ollama CLI was not found."
        try:
            result = subprocess.run(
                [executable, "list"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"Could not contact Ollama: {exc}"
        if result.returncode == 0:
            model = os.environ.get("MDIR_OLLAMA_MODEL", "qwen3-coder")
            return True, f"Ollama is running. Selected model: {model}"
        return False, (result.stderr or "Ollama service is not responding.").strip()

    def parse_line(self, line: str) -> Iterable[AIEvent]:
        """Remove Ollama spinner and cursor sequences from streamed text."""
        text = sanitize_terminal_output(line)
        text = OLLAMA_SPINNER_RE.sub("", text).rstrip("\r\n")
        if text.strip():
            yield AIEvent("message", text)


class OllamaCPUProvider(OllamaProvider):
    """Run Gemma 4 through an isolated CPU-only Ollama server."""

    name = "Ollama CPU"

    @property
    def path_environment_variable(self) -> str:
        return "MDIR_OLLAMA_PATH"

    def build_command(
        self, prompt: str, cwd: Path, session_id: Optional[str]
    ) -> list[str]:
        powershell = (
            shutil.which("powershell.exe")
            or shutil.which("pwsh.exe")
            or "powershell.exe"
        )
        executable = self.command_executable()
        model = os.environ.get("MDIR_OLLAMA_CPU_MODEL", "gemma4:e4b")
        encoded_prompt = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
        ps_quote = lambda value: "'" + value.replace("'", "''") + "'"

        # Port 11435 keeps the CPU fallback isolated from the normal Ollama
        # application on port 11434. The temporary server is stopped after
        # every answer unless it was already running before this request.
        script = (
            "$ErrorActionPreference='Stop';"
            "$__mdirOllama=" + ps_quote(executable) + ";"
            "$__mdirModel=" + ps_quote(model) + ";"
            "$__mdirPrompt=[Text.Encoding]::UTF8.GetString("
            "[Convert]::FromBase64String(" + ps_quote(encoded_prompt) + "));"
            "$env:OLLAMA_HOST='127.0.0.1:11435';"
            "$env:CUDA_VISIBLE_DEVICES='-1';"
            "$env:GGML_VK_VISIBLE_DEVICES='-1';"
            "$env:OLLAMA_LLM_LIBRARY='cpu_avx2';"
            "$env:OLLAMA_VULKAN='0';"
            "$__mdirStarted=$false;"
            "$__mdirServer=$null;"
            "try{"
            "try{"
            "Invoke-RestMethod -Uri 'http://127.0.0.1:11435/api/version' "
            "-TimeoutSec 1|Out-Null"
            "}catch{"
            "$__mdirServer=Start-Process -FilePath $__mdirOllama "
            "-ArgumentList 'serve' -WindowStyle Hidden -PassThru;"
            "$__mdirStarted=$true;"
            "$__mdirReady=$false;"
            "for($__mdirTry=0;$__mdirTry -lt 60;$__mdirTry++){"
            "Start-Sleep -Milliseconds 250;"
            "try{"
            "Invoke-RestMethod -Uri 'http://127.0.0.1:11435/api/version' "
            "-TimeoutSec 1|Out-Null;"
            "$__mdirReady=$true;break"
            "}catch{}"
            "};"
            "if(-not $__mdirReady){throw 'Ollama CPU server did not start.'}"
            "};"
            "& $__mdirOllama run $__mdirModel $__mdirPrompt;"
            "$__mdirExit=$LASTEXITCODE"
            "}finally{"
            "if($__mdirStarted -and $__mdirServer){"
            "Stop-Process -Id $__mdirServer.Id -Force -ErrorAction SilentlyContinue"
            "}"
            "};"
            "exit $__mdirExit"
        )
        return [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]

    def connection_status(self) -> tuple[bool, str]:
        executable = self.resolve_executable()
        if executable is None:
            return False, "Ollama CLI was not found."
        model = os.environ.get("MDIR_OLLAMA_CPU_MODEL", "gemma4:e4b")
        return True, (
            f"CPU-only Ollama is ready. Selected model: {model}. "
            "A temporary local server will be used for each answer."
        )


class OllamaCloudProvider(OllamaProvider):
    """Ollama cloud chat with an explicit interactive sign-in action."""

    name = "Ollama Cloud"
    signin_verified = False

    @property
    def path_environment_variable(self) -> str:
        return "MDIR_OLLAMA_PATH"

    def build_command(
        self, prompt: str, cwd: Path, session_id: Optional[str]
    ) -> list[str]:
        model = os.environ.get(
            "MDIR_OLLAMA_CLOUD_MODEL",
            "gemma4:31b-cloud",
        )
        return [self.command_executable(), "run", model, prompt]

    def login_command(self) -> Optional[list[str]]:
        executable = self.resolve_executable()
        return [executable, "signin"] if executable else None

    def connection_status(self) -> tuple[bool, str]:
        executable = self.resolve_executable()
        if executable is None:
            return False, "Ollama CLI was not found."
        model = os.environ.get(
            "MDIR_OLLAMA_CLOUD_MODEL",
            "gemma4:31b-cloud",
        )
        if self.signin_verified:
            return True, (
                f"Ollama Cloud sign-in is verified. Cloud model: {model}."
            )
        return False, (
            f"Cloud authentication has not been verified for {model}. "
            "Press Connect to open sign-in and display its URL."
        )

    def parse_line(self, line: str) -> Iterable[AIEvent]:
        """Turn a cloud authorization response into a sign-in request."""
        text = sanitize_terminal_output(line)
        text = OLLAMA_SPINNER_RE.sub("", text).rstrip("\r\n")
        if not text.strip():
            return
        if "need to be signed in to Ollama" in text:
            self.signin_verified = False
            yield AIEvent(
                "auth_required",
                "Ollama Cloud requires sign-in. Opening authentication now.",
            )
        else:
            yield AIEvent("message", text)


PROVIDERS: dict[str, AIProvider] = {
    provider.name.lower(): provider
    for provider in (
        CodexProvider(),
        CodexQuickProvider(),
        CodexLocalProvider(),
        ShellProvider(),
        ClaudeProvider(),
        GeminiProvider(),
        OllamaProvider(),
        OllamaCloudProvider(),
        OllamaCPUProvider(),
    )
}


def provider_choices() -> list[tuple[str, str]]:
    return [
        (
            provider.name + ("" if provider.available() else " (not found)"),
            key,
        )
        for key, provider in PROVIDERS.items()
    ]
