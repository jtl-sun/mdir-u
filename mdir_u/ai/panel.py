from __future__ import annotations

import os
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from rich.cells import cell_len
from rich.markup import escape
from rich.segment import Segment
from rich.style import Style
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Paste
from textual.message import Message
from textual.selection import Selection
from textual.strip import Strip
from textual.widgets import Button, RichLog, Select, Static, TextArea

from .providers import (
    AIEvent,
    PROVIDERS,
    provider_choices,
    sanitize_terminal_output,
)
from ..ui.dialogs import CompactConfirmScreen


class AICommandEditor(TextArea):
    """Scrollable multi-line AI prompt editor."""

    BINDINGS = TextArea.BINDINGS + [
        # Windows Terminal may encode Ctrl+Enter as LF, which Textual reports
        # as Ctrl+J. Supporting both names keeps the shortcut portable.
        Binding(
            "ctrl+enter,ctrl+j",
            "submit_prompt",
            "Send prompt",
            show=False,
        ),
    ]

    @dataclass
    class Submitted(Message):
        editor: "AICommandEditor"
        text: str

        @property
        def control(self) -> "AICommandEditor":
            return self.editor

    def action_submit_prompt(self) -> None:
        self.post_message(self.Submitted(self, self.text))

    async def _on_key(self, event) -> None:
        # This fallback handles terminals that bypass the binding table but
        # still report the modified Enter key as Ctrl+J.
        if event.key in {"ctrl+enter", "ctrl+j"}:
            event.stop()
            event.prevent_default()
            self.action_submit_prompt()
            return
        await super()._on_key(event)


class ConversationLog(RichLog):
    """Selectable AI transcript with explicit clipboard shortcuts."""

    ALLOW_SELECT = True
    BINDINGS = RichLog.BINDINGS + [
        Binding("ctrl+c", "copy_selection", "Copy conversation", show=False),
        Binding("ctrl+v", "paste_to_prompt", "Paste to prompt", show=False),
    ]
    SELECTION_HIGHLIGHT = Style(
        color="#ffffff",
        bgcolor="#2563eb",
        bold=True,
    )

    def write(self, content, *args, **kwargs):
        """Write content and attach source offsets required for mouse selection."""
        first_new_line = len(self.lines)
        result = super().write(content, *args, **kwargs)

        # Deferred writes call this override again after the widget is sized.
        if len(self.lines) > first_new_line:
            for line_index in range(first_new_line, len(self.lines)):
                strip = self.lines[line_index]
                character_offset = 0
                segments: list[Segment] = []
                for segment in strip:
                    offset_style = Style(
                        meta={"offset": (character_offset, line_index)}
                    )
                    style = (
                        segment.style + offset_style
                        if segment.style is not None
                        else offset_style
                    )
                    segments.append(
                        Segment(segment.text, style, segment.control)
                    )
                    character_offset += len(segment.text)
                self.lines[line_index] = Strip(
                    segments,
                    cell_length=strip.cell_length,
                )
            self._line_cache.clear()
            self.refresh()

        return result

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Extract the plain transcript text under a mouse selection."""
        transcript = "\n".join(line.text.rstrip() for line in self.lines)
        return selection.extract(transcript), "\n"

    def render_line(self, y: int) -> Strip:
        """Render an unmistakable blue highlight over selected transcript text."""
        rendered = super().render_line(y)
        selection = self.text_selection
        if selection is None:
            return rendered

        scroll_x, scroll_y = self.scroll_offset
        line_index = int(scroll_y) + y
        if not (0 <= line_index < len(self.lines)):
            return rendered

        span = selection.get_span(line_index)
        if span is None:
            return rendered

        start_character, end_character = span
        line_text = self.lines[line_index].text
        start_cell = cell_len(line_text[:start_character])
        end_cell = (
            cell_len(line_text)
            if end_character < 0
            else cell_len(line_text[:end_character])
        )
        visible_start = max(0, start_cell - int(scroll_x))
        visible_end = min(rendered.cell_length, end_cell - int(scroll_x))
        if visible_end <= visible_start:
            return rendered

        selected = rendered.crop(visible_start, visible_end)
        selected = Strip(
            (
                Segment(
                    segment.text,
                    (
                        segment.style + self.SELECTION_HIGHLIGHT
                        if segment.style is not None
                        else self.SELECTION_HIGHLIGHT
                    ),
                    segment.control,
                )
                for segment in selected
            ),
            cell_length=selected.cell_length,
        )
        return Strip.join(
            (
                rendered.crop(0, visible_start),
                selected,
                rendered.crop(visible_end, rendered.cell_length),
            )
        )

    def _ai_panel(self) -> Optional["AIPanel"]:
        node = self.parent
        while node is not None and not isinstance(node, AIPanel):
            node = node.parent
        return node if isinstance(node, AIPanel) else None

    def action_copy_selection(self) -> None:
        selected = self.screen.get_selected_text()
        if not selected:
            self.app.notify(
                "Drag over conversation text before pressing Ctrl+C.",
                title="Nothing selected",
            )
            return
        self.app.copy_to_clipboard(selected)
        self.app.notify("Selected conversation text copied.", title="Ctrl+C")

    def action_paste_to_prompt(self) -> None:
        panel = self._ai_panel()
        if panel is not None:
            panel.paste_into_prompt(self.app.clipboard)


class AIPanel(Vertical):
    """Conversation-oriented CLI bridge that does not embed a second TUI."""

    DEFAULT_CSS = """
    AIPanel {
        width: 1fr;
        height: 1fr;
        background: $background;
        border-left: solid $surface-lighten-2;
    }
    AIPanel .ai-toolbar {
        height: 3;
        padding: 0 1;
        background: $surface;
    }
    AIPanel Select { width: 18; }
    AIPanel Button { min-width: 8; width: auto; margin-left: 1; }
    AIPanel #ai_context {
        height: 2;
        padding: 0 1;
        color: $foreground;
        background: $panel;
    }
    AIPanel #ai_activity {
        height: 1;
        padding: 0 1;
        color: $warning;
        background: $panel;
        text-style: bold;
    }
    AIPanel #ai_log {
        height: 1fr;
        padding: 1;
        background: $background;
        color: $foreground;
    }
    AIPanel #ai_prompt_row {
        dock: bottom;
        height: 7;
        min-height: 7;
        max-height: 12;
        align-vertical: middle;
    }
    AIPanel #ai_prompt {
        width: 1fr;
        height: 7;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }
    AIPanel #ai_send {
        width: 10;
        min-width: 10;
        height: 7;
        margin: 0 0 0 1;
    }
    AIPanel #ai_prompt .text-area--cursor {
        background: #f4f4f5;
        color: #111827;
        text-style: bold;
    }
    AIPanel #ai_prompt .text-area--selection {
        background: $primary;
        color: $text-primary;
        text-style: bold;
    }
    """

    def __init__(self, cwd_getter: Callable[[], Path]) -> None:
        super().__init__(id="ai_panel")
        self.cwd_getter = cwd_getter
        self.sessions: dict[str, str] = {}
        self.process: Optional[subprocess.Popen[str]] = None
        self.codex_local_confirmed = False
        self.activity_running = False
        self.activity_provider = ""
        self.activity_started_at: Optional[float] = None
        self.activity_frame = 0
        self.activity_phase = ""
        self.stop_requested = False
        self.response_heading_shown = False
        self.auth_required_for_task = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="ai-toolbar"):
            yield Select(
                provider_choices(),
                value="codex quick",
                allow_blank=False,
                id="ai_provider",
            )
            yield Button("Connect", id="ai_connect", variant="primary")
            yield Button("New chat", id="ai_new")
            yield Button("Stop", id="ai_stop", variant="error")
        yield Static("", id="ai_context")
        yield Static("Status: Ready", id="ai_activity")
        yield ConversationLog(
            id="ai_log",
            wrap=True,
            markup=True,
            highlight=True,
        )
        with Horizontal(id="ai_prompt_row"):
            yield AICommandEditor(
                placeholder=(
                    "Ask AI here. Enter: new line / "
                    "Ctrl+Enter: send / F12: file pane"
                ),
                soft_wrap=True,
                show_line_numbers=False,
                id="ai_prompt",
            )
            yield Button("Send", id="ai_send", variant="success")

    def on_mount(self) -> None:
        prompt = self.query_one("#ai_prompt", AICommandEditor)
        # A steady cursor remains visible while moving through Korean text.
        prompt.cursor_blink = False
        prompt._cursor_visible = True
        self.set_interval(0.25, self._refresh_activity)
        self.refresh_context()
        self._append(
            "[bold cyan]MDIR-U AI Terminal[/]\n"
            "Codex Quick is the default provider for faster everyday replies.\n"
            "Select regular Codex when a task needs deeper reasoning.\n"
            "Commands run in the directory shown above.\n"
            "The default Codex sandbox is [bold]workspace-write[/].\n"
            "Select [bold]Codex Local[/] for an AI agent with full PC access.\n"
            "Select [bold]Shell[/] to run local commands outside the Codex sandbox.\n"
            "Select [bold]Ollama Cloud[/] and press Connect for cloud models.\n"
            "Select [bold]Ollama CPU[/] for Gemma 4 on low-VRAM systems.\n"
            "If auto-detection fails, set [bold]MDIR_CODEX_PATH[/] to codex.exe."
        )
        self.check_connection(self.provider_key)

    @property
    def provider_key(self) -> str:
        value = self.query_one("#ai_provider", Select).value
        return str(value) if value is not Select.BLANK else "codex"

    def refresh_context(self) -> None:
        cwd = self.cwd_getter()
        key = self.provider_key
        session = self.sessions.get(key, "")
        if key == "shell":
            suffix = " - local shell - no Codex sandbox"
        elif key == "codex quick":
            suffix = " - low reasoning - faster response"
        elif key == "codex local":
            suffix = " - local AI agent - full PC access"
        elif key == "ollama cloud":
            suffix = " - cloud model - Ollama account"
        else:
            suffix = (
                f" - session {session[:8]}" if session else " - new session"
            )
        self.query_one("#ai_context", Static).update(
            f"Workspace: {cwd}{suffix}"
        )

    def update_editor_mode(self) -> None:
        """Update prompt hints and the action button for the selected provider."""
        editor = self.query_one("#ai_prompt", AICommandEditor)
        send = self.query_one("#ai_send", Button)
        if self.provider_key == "shell":
            editor.placeholder = (
                "Run shell commands here. Enter: new line / "
                "Ctrl+Enter: run / F12: file pane"
            )
            send.label = "Run"
        elif self.provider_key == "codex local":
            editor.placeholder = (
                "Ask Codex Local. Enter: new line / "
                "Ctrl+Enter: run with full PC access"
            )
            send.label = "Run AI"
        elif self.provider_key == "codex quick":
            editor.placeholder = (
                "Ask Codex Quick. Enter: new line / "
                "Ctrl+Enter: send / F12: file pane"
            )
            send.label = "Send"
        elif self.provider_key == "ollama cloud":
            editor.placeholder = (
                "Ask Ollama Cloud. Enter: new line / "
                "Ctrl+Enter: send / Connect: sign in"
            )
            send.label = "Send"
        else:
            editor.placeholder = (
                "Ask AI here. Enter: new line / "
                "Ctrl+Enter: send / F12: file pane"
            )
            send.label = "Send"

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        """Format elapsed execution time without depending on locale settings."""
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _start_activity(self, provider_name: str) -> None:
        """Show an immediate running indicator before the worker starts."""
        self.activity_running = True
        self.activity_provider = provider_name
        self.activity_started_at = time.monotonic()
        self.activity_frame = 0
        self.activity_phase = "Starting CLI"
        self.stop_requested = False
        self._refresh_activity()

    def _refresh_activity(self) -> None:
        """Animate the running state and update its elapsed time."""
        if not self.activity_running or self.activity_started_at is None:
            return
        frames = ("|", "/", "-", "\\")
        marker = frames[self.activity_frame % len(frames)]
        self.activity_frame += 1
        elapsed = self._format_elapsed(
            time.monotonic() - self.activity_started_at
        )
        state = "Stopping" if self.stop_requested else "Running"
        phase = (
            "Stopping process"
            if self.stop_requested
            else self.activity_phase
        )
        self.query_one("#ai_activity", Static).update(
            f"[bold yellow]{marker} {state}: "
            f"{self.activity_provider} - {phase} - {elapsed}[/]"
        )

    def _set_activity_phase(self, phase: str) -> None:
        """Show the latest provider stage without adding transcript noise."""
        if not self.activity_running:
            return
        self.activity_phase = phase
        self._refresh_activity()

    def _finish_activity(self, outcome: str, failed: bool = False) -> None:
        """Replace the animation with a persistent completion result."""
        if self.activity_started_at is None:
            elapsed = "00:00"
        else:
            elapsed = self._format_elapsed(
                time.monotonic() - self.activity_started_at
            )
        color = "red" if failed else "green"
        self.query_one("#ai_activity", Static).update(
            f"[bold {color}]Status: {outcome} - "
            f"{self.activity_provider} - {elapsed}[/]"
        )
        self.activity_running = False
        self.activity_started_at = None
        self.activity_phase = ""
        self.stop_requested = False

    def focus_prompt(self) -> None:
        # A provider may finish after the user has already returned to the
        # file pane. Never let a hidden/disabled AI input steal focus back.
        if not self.display or self.disabled:
            return
        self.refresh_context()
        self.query_one("#ai_prompt", AICommandEditor).focus()

    def paste_into_prompt(self, text: str) -> None:
        """Insert clipboard text even when the conversation log has focus."""
        if not text:
            self.app.notify("The clipboard is empty.", title="Ctrl+V")
            return
        prompt = self.query_one("#ai_prompt", AICommandEditor)
        start, end = prompt.selection
        prompt.replace(text, start, end, maintain_selection_offset=False)
        prompt.focus()

    @on(Paste)
    def paste_received(self, event: Paste) -> None:
        """Route Windows Terminal paste events from the log to the prompt."""
        # The editor already handled the bubbling Paste event itself.
        if isinstance(self.app.focused, AICommandEditor):
            return
        self.paste_into_prompt(event.text)
        event.stop()

    def _append(self, text: str) -> None:
        self.query_one("#ai_log", RichLog).write(text)

    @on(Select.Changed, "#ai_provider")
    def provider_changed(self, event: Select.Changed) -> None:
        self.refresh_context()
        self.update_editor_mode()
        provider = PROVIDERS[self.provider_key]
        state = "ready" if provider.available() else "CLI not found on PATH"
        self._append(f"[bold cyan]{provider.name}[/]: {state}")
        if self.provider_key == "shell":
            self._append(
                "[yellow]Local mode: commands run directly on this PC, "
                "outside the Codex sandbox.[/]"
            )
        elif self.provider_key == "codex local":
            self._append(
                "[bold yellow]Warning: Codex Local can install software and "
                "modify or delete files anywhere this Linux account can access.[/]"
            )
        elif self.provider_key == "codex quick":
            self._append(
                "[cyan]Quick mode uses low reasoning for faster replies. "
                "Select regular Codex for complex or high-risk work.[/]"
            )
        elif self.provider_key == "ollama cloud":
            self._append(
                "[yellow]Cloud mode: prompts are processed by Ollama's "
                "online service. Press Connect to sign in.[/]"
            )
        self.check_connection(self.provider_key)

    @on(Button.Pressed, "#ai_connect")
    def connect_clicked(self) -> None:
        if self.process and self.process.poll() is None:
            self._append("[yellow]Stop the current AI task before connecting.[/]")
            return
        self.connect_provider(self.provider_key, self.cwd_getter())

    @on(Button.Pressed, "#ai_send")
    def send_clicked(self) -> None:
        self.query_one("#ai_prompt", AICommandEditor).action_submit_prompt()

    @on(Button.Pressed, "#ai_new")
    def new_chat(self) -> None:
        self.sessions.pop(self.provider_key, None)
        self.refresh_context()
        self._append("[dim]Started a new conversation.[/]")
        self.focus_prompt()

    @on(Button.Pressed, "#ai_stop")
    def stop_clicked(self) -> None:
        if self.process and self.process.poll() is None:
            self.stop_requested = True
            self._refresh_activity()
            self.process.terminate()
            self._append("[yellow]Stop requested.[/]")
        elif self.activity_running:
            self.stop_requested = True
            self._refresh_activity()
            self._append("[yellow]The task is starting; Stop was requested.[/]")
        else:
            self._append("[dim]No AI task is running.[/]")

    @on(AICommandEditor.Submitted, "#ai_prompt")
    def prompt_submitted(self, event: AICommandEditor.Submitted) -> None:
        # Windows IMEs may deliver decomposed Jamo while composition settles.
        # Store and send canonical Korean syllables without adding spaces.
        prompt = unicodedata.normalize("NFC", event.text).strip()
        if not prompt:
            return
        if self.activity_running or (
            self.process and self.process.poll() is None
        ):
            self._append("[yellow]Wait for the current task or press Stop.[/]")
            return
        key = self.provider_key
        editor = event.editor

        if key == "codex local" and not self.codex_local_confirmed:
            def local_access_confirmed(allowed: bool) -> None:
                if not allowed:
                    self._append("[yellow]Codex Local access was cancelled.[/]")
                    editor.focus()
                    return
                self.codex_local_confirmed = True
                self._append(
                    "[bold yellow]Codex Local full access is enabled for "
                    "this MDIR session.[/]"
                )
                self._dispatch_prompt(prompt, key, editor)

            self.app.push_screen(
                CompactConfirmScreen(
                    "Codex Local will run AI-generated commands directly on this PC.\n"
                    "It can install or remove software and modify or delete files.\n"
                    "Allow full local access for this MDIR session?",
                    title="Enable Codex Local",
                ),
                local_access_confirmed,
            )
            return

        self._dispatch_prompt(prompt, key, editor)

    def _dispatch_prompt(
        self,
        prompt: str,
        key: str,
        editor: AICommandEditor,
    ) -> None:
        """Clear the editor and start a confirmed provider request."""
        editor.text = ""
        editor.focus()
        if key == "shell":
            self._append(f"\n[bold magenta]$[/]\n{escape(prompt)}")
        else:
            self._append(f"\n[bold green]You[/]\n{escape(prompt)}")
        self.response_heading_shown = False
        self.auth_required_for_task = False
        self._start_activity(PROVIDERS[key].name)
        self.run_prompt(
            prompt,
            key,
            self.cwd_getter(),
            self.sessions.get(key),
        )

    def _post_event(self, event: AIEvent) -> None:
        if event.session_id:
            self.sessions[self.provider_key] = event.session_id
            self.refresh_context()
        elif event.kind == "message":
            if not self.response_heading_shown:
                self._append(f"\n[bold cyan]AI[/]\n{escape(event.text)}")
                self.response_heading_shown = True
            else:
                self._append(escape(event.text))
        elif event.kind == "output":
            self._append(escape(event.text))
        elif event.kind == "progress":
            self._set_activity_phase(event.text)
        elif event.kind == "tool":
            self._append(f"[dim]{escape(event.text)}[/]")
        elif event.kind == "error":
            self._append(f"[bold red]{escape(event.text)}[/]")
        elif event.kind == "auth_required":
            self.auth_required_for_task = True
            self._append(f"[bold yellow]{escape(event.text)}[/]")
            self.connect_provider("ollama cloud", self.cwd_getter())
        elif event.text:
            self._append(f"[dim]{escape(event.text)}[/]")

    def _show_connection_status(
        self, provider_name: str, connected: bool, message: str
    ) -> None:
        color = "green" if connected else "yellow"
        label = "Connected" if connected else "Attention"
        self._append(
            f"[bold {color}]{provider_name}: {label}[/]\n{escape(message)}"
        )

    @work(thread=True, exclusive=True, group="ai-connection-check")
    def check_connection(self, key: str) -> None:
        provider = PROVIDERS[key]
        connected, message = provider.connection_status()
        self.app.call_from_thread(
            self._show_connection_status,
            provider.name,
            connected,
            message,
        )

    @work(thread=True, exclusive=True, group="ai-connect")
    def connect_provider(self, key: str, cwd: Path) -> None:
        provider = PROVIDERS[key]
        connected, message = provider.connection_status()
        self.app.call_from_thread(
            self._show_connection_status,
            provider.name,
            connected,
            message,
        )
        if connected:
            return

        command = provider.login_command()
        if command is None:
            hint = (
                f"Install and authenticate the {provider.name} CLI in your shell, "
                "then press Connect again."
            )
            if provider.name == "Ollama":
                hint = "Start the Ollama service, then press Connect again."
            self.app.call_from_thread(self._append, f"[yellow]{escape(hint)}[/]")
            return

        if key == "ollama cloud":
            self.app.call_from_thread(
                self._append,
                "[cyan]Starting Ollama sign-in. The browser should open; "
                "the same secure URL will also appear below.[/]",
            )
            try:
                result = subprocess.run(
                    command,
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    ),
                )
                output = sanitize_terminal_output(
                    (result.stdout or "") + (result.stderr or "")
                ).strip()
                if output:
                    self.app.call_from_thread(
                        self._append,
                        f"[cyan]{escape(output)}[/]",
                    )
                output_lower = output.lower()
                if "already signed in" in output_lower:
                    provider.signin_verified = True
                    self.app.call_from_thread(
                        self._show_connection_status,
                        provider.name,
                        True,
                        "Ollama Cloud sign-in is verified.",
                    )
                elif "navigate to" in output_lower:
                    self.app.call_from_thread(
                        self._show_connection_status,
                        provider.name,
                        False,
                        (
                            "Browser sign-in has started. Complete it, then "
                            "press Connect again to verify."
                        ),
                    )
                elif result.returncode:
                    self.app.call_from_thread(
                        self._show_connection_status,
                        provider.name,
                        False,
                        f"Ollama signin exited with code {result.returncode}.",
                    )
                else:
                    self.app.call_from_thread(
                        self._show_connection_status,
                        provider.name,
                        False,
                        "Sign-in started. Complete it and press Connect again.",
                    )
            except Exception as exc:
                self.app.call_from_thread(
                    self._append,
                    f"[bold red]Could not start Ollama sign-in: "
                    f"{escape(str(exc))}[/]",
                )
            return

        self.app.call_from_thread(
            self._append,
            f"[cyan]Opening the {escape(provider.name)} sign-in window. "
            "Complete the browser login.[/]",
        )
        try:
            creationflags = (
                subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
            )
            login_process = subprocess.Popen(
                command,
                cwd=str(cwd),
                creationflags=creationflags,
            )
            return_code = login_process.wait()
            if return_code != 0:
                self.app.call_from_thread(
                    self._append,
                    f"[bold red]Codex login exited with code {return_code}.[/]",
                )
                return
            connected, message = provider.connection_status()
            self.app.call_from_thread(
                self._show_connection_status,
                provider.name,
                connected,
                message,
            )
        except Exception as exc:
            self.app.call_from_thread(
                self._append,
                f"[bold red]Could not start login: {escape(str(exc))}[/]",
            )

    @work(thread=True, exclusive=True, group="ai-provider")
    def run_prompt(
        self,
        prompt: str,
        key: str,
        cwd: Path,
        session_id: Optional[str],
    ) -> None:
        provider = PROVIDERS[key]

        if not provider.available():
            self.app.call_from_thread(
                self._append,
                (
                    f"[bold red]{provider.name} CLI was not found.[/]\n"
                    f"Set {provider.path_environment_variable} to its executable path."
                ),
            )
            self.app.call_from_thread(
                self._finish_activity,
                "Failed: CLI not found",
                True,
            )
            return

        command = provider.build_command(prompt, cwd, session_id)
        creationflags = (
            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        if self.stop_requested:
            self.app.call_from_thread(
                self._finish_activity,
                "Stopped before start",
                False,
            )
            return
        try:
            self.app.call_from_thread(
                self._set_activity_phase,
                "Launching process",
            )
            self.process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            if self.stop_requested:
                self.process.terminate()
            self.app.call_from_thread(
                self._set_activity_phase,
                "Waiting for provider",
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                for parsed in provider.parse_line(line):
                    self.app.call_from_thread(self._post_event, parsed)
            return_code = self.process.wait()
            if return_code:
                self.app.call_from_thread(
                    self._append,
                    f"[bold red]{provider.name} exited with code {return_code}.[/]",
                )
                outcome = (
                    "Stopped"
                    if self.stop_requested
                    else f"Failed: exit code {return_code}"
                )
                self.app.call_from_thread(
                    self._finish_activity,
                    outcome,
                    not self.stop_requested,
                )
            elif self.auth_required_for_task:
                self.app.call_from_thread(
                    self._finish_activity,
                    "Authentication required",
                    True,
                )
            elif self.stop_requested:
                self.app.call_from_thread(
                    self._finish_activity,
                    "Stopped",
                    False,
                )
            else:
                self.app.call_from_thread(
                    self._finish_activity,
                    "Completed",
                    False,
                )
        except Exception as exc:
            self.app.call_from_thread(
                self._append, f"[bold red]AI launch failed: {escape(str(exc))}[/]"
            )
            self.app.call_from_thread(
                self._finish_activity,
                "Failed to start",
                True,
            )
        finally:
            self.process = None
            self.app.call_from_thread(self.focus_prompt)
