from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

from .inputs import ThinCursorInput as Input


INVALID_WINDOWS_CHARS = set('<>:"/\\|?*')
TOKEN_PATTERN = re.compile(r"\[(N|E|C|YMD|hms)\]")
RANGE_TOKEN_PATTERN = re.compile(r"\[(N|E)(\d+)-(\d+)\]")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class RenamePair:
    source: Path
    target: Path


@dataclass(frozen=True)
class BatchRenameOptions:
    name_pattern: str = "[N]"
    extension_pattern: str = "[E]"
    find_text: str = ""
    replace_text: str = ""
    start: int = 1
    step: int = 1
    digits: int = 1
    regex: bool = False
    delete_found_text: bool = False
    append_counter: bool = False
    counter_separator: str = "_"


def _split_name(path: Path) -> tuple[str, str]:
    if path.is_dir() or not path.suffix:
        return path.name, ""
    return path.stem, path.suffix.lstrip(".")


def _replace_tokens(pattern: str, values: dict[str, str]) -> str:
    def range_value(match: re.Match[str]) -> str:
        value = values[match.group(1)]
        start = max(0, int(match.group(2)) - 1)
        end = max(start, int(match.group(3)))
        return value[start:end]

    ranged = RANGE_TOKEN_PATTERN.sub(range_value, pattern)
    return TOKEN_PATTERN.sub(lambda match: values[match.group(1)], ranged)


def build_rename_pairs(
    items: Sequence[Path], options: BatchRenameOptions
) -> tuple[list[RenamePair], list[str]]:
    pairs: list[RenamePair] = []
    errors: list[str] = []
    source_keys = {str(path).casefold() for path in items}
    target_keys: set[str] = set()

    if not options.name_pattern:
        return [], ["The name pattern cannot be empty."]
    uses_counter = "[C]" in options.name_pattern or options.append_counter
    if uses_counter and (options.digits < 1 or options.digits > 12):
        return [], ["Choose counter digits between 1 and 12."]

    for index, source in enumerate(items):
        stem, extension = _split_name(source)
        try:
            stamp = datetime.fromtimestamp(source.stat().st_mtime)
        except OSError:
            stamp = datetime.now()
        counter = options.start + (index * options.step)
        values = {
            "N": stem,
            "E": extension,
            "C": f"{counter:0{max(1, options.digits)}d}",
            "YMD": stamp.strftime("%Y%m%d"),
            "hms": stamp.strftime("%H%M%S"),
        }
        new_stem = _replace_tokens(options.name_pattern, values)
        new_extension = "" if source.is_dir() else _replace_tokens(
            options.extension_pattern, values
        ).lstrip(".")

        if options.find_text:
            replacement = "" if options.delete_found_text else options.replace_text
            try:
                if options.regex:
                    new_stem = re.sub(
                        options.find_text, replacement, new_stem
                    )
                    new_extension = re.sub(
                        options.find_text, replacement, new_extension
                    )
                else:
                    new_stem = new_stem.replace(
                        options.find_text, replacement
                    )
                    new_extension = new_extension.replace(
                        options.find_text, replacement
                    )
            except re.error as exc:
                return [], [f"Invalid regular expression: {exc}"]

        if options.append_counter and "[C]" not in options.name_pattern:
            new_stem += options.counter_separator + values["C"]

        new_name = new_stem + (f".{new_extension}" if new_extension else "")
        if not new_stem or new_name in {".", ".."}:
            errors.append(f"{source.name}: the new name is empty or invalid")
            continue
        invalid_chars = (
            INVALID_WINDOWS_CHARS if os.name == "nt" else {'/', '\\'}
        )
        if any(
            character in invalid_chars or ord(character) < 32
            for character in new_name
        ):
            errors.append(f"{source.name}: the new name contains a forbidden character")
            continue
        if os.name == "nt" and new_name.endswith((" ", ".")):
            errors.append(f"{source.name}: the new name cannot end with a space or dot")
            continue
        if (
            os.name == "nt"
            and new_stem.rstrip(" .").upper() in WINDOWS_RESERVED_NAMES
        ):
            errors.append(f"{source.name}: '{new_stem}' is a reserved Windows name")
            continue

        target = source.with_name(new_name)
        target_key = str(target).casefold()
        if target_key in target_keys:
            errors.append(f"Duplicate target name: {new_name}")
            continue
        target_keys.add(target_key)
        if target.exists() and target_key not in source_keys:
            errors.append(f"Already exists: {new_name}")
            continue
        pairs.append(RenamePair(source, target))

    return pairs, errors


def apply_rename_pairs(pairs: Sequence[RenamePair]) -> None:
    """Rename safely in two phases and roll back if any operation fails."""
    changed = [pair for pair in pairs if pair.source != pair.target]
    staged: list[tuple[Path, Path, Path]] = []
    committed: list[tuple[Path, Path, Path]] = []
    try:
        for pair in changed:
            temporary = pair.source.with_name(
                f".mdir-rename-{uuid.uuid4().hex}.tmp"
            )
            pair.source.rename(temporary)
            staged.append((pair.source, temporary, pair.target))
        for source, temporary, target in staged:
            temporary.rename(target)
            committed.append((source, temporary, target))
    except Exception:
        for source, _temporary, target in reversed(committed):
            if target.exists() and not source.exists():
                target.rename(source)
        for source, temporary, _target in reversed(staged):
            if temporary.exists() and not source.exists():
                temporary.rename(source)
        raise


class BatchRenameScreen(ModalScreen[list[RenamePair] | None]):
    """Preview and validate a multi-file rename before changing disk names."""

    CSS = """
    BatchRenameScreen { align: center middle; background: #00000088; }
    #batch_dialog {
        width: 96%; height: 92%; border: solid $primary;
        background: $surface; padding: 0 1;
    }
    #batch_title { height: 1; color: $accent; text-style: bold; }
    .field_row { height: 3; }
    .field_label { width: 14; height: 3; content-align: left middle; }
    .field_input { width: 1fr; height: 3; }
    .small_input { width: 12; height: 3; }
    .small_label { width: 9; height: 3; content-align: left middle; }
    #frequent_row { height: 3; }
    #frequent_row .frequent_label { width: 14; height: 3; content-align: left middle; }
    #frequent_row Button { min-width: 20; width: auto; height: 3; margin-right: 1; }
    #counter_separator { width: 8; height: 3; }
    #separator_label { width: 11; height: 3; content-align: left middle; }
    #token_row { height: 3; }
    #token_row Button { min-width: 10; width: auto; height: 3; margin-right: 1; }
    #rename_preview { height: 1fr; min-height: 8; margin-top: 1; }
    #rename_status { height: 1; color: $warning; }
    #rename_actions { height: 3; align-horizontal: right; }
    #rename_actions Button { min-width: 12; height: 3; margin-left: 1; }
    """

    def __init__(self, items: Sequence[Path]) -> None:
        super().__init__()
        self.items = list(items)
        self.regex_enabled = False
        self.delete_found_text = False
        self.append_counter = False

    def compose(self) -> ComposeResult:
        with Vertical(id="batch_dialog"):
            yield Label(
                f"Batch Rename — {len(self.items)} selected item(s)",
                id="batch_title",
            )
            with Horizontal(classes="field_row"):
                yield Label("Name pattern:", classes="field_label")
                yield Input(value="[N]", id="name_pattern", classes="field_input")
            with Horizontal(id="token_row"):
                yield Button("[N] Name", id="token_name")
                yield Button("[C] Counter", id="token_counter")
                yield Button("[YMD] Date", id="token_date")
                yield Button("[hms] Time", id="token_time")
            with Horizontal(classes="field_row"):
                yield Label("Extension:", classes="field_label")
                yield Input(value="[E]", id="extension_pattern", classes="field_input")
            with Horizontal(classes="field_row"):
                yield Label("Find:", classes="field_label")
                yield Input(id="find_text", classes="field_input")
                yield Label("Replace:", classes="field_label")
                yield Input(placeholder="Disabled while Delete is ON", id="replace_text", classes="field_input")
            with Horizontal(id="frequent_row"):
                yield Label("Quick options:", classes="frequent_label")
                yield Button("Delete found text: OFF", id="delete_text_toggle")
                yield Button("End number: OFF", id="append_counter_toggle")
                yield Label("Separator:", id="separator_label")
                yield Input(value="_", id="counter_separator")
            with Horizontal(classes="field_row"):
                yield Label("Start:", classes="small_label")
                yield Input(value="1", id="counter_start", classes="small_input")
                yield Label("Step:", classes="small_label")
                yield Input(value="1", id="counter_step", classes="small_input")
                yield Label("Digits:", classes="small_label")
                yield Input(value="1", id="counter_digits", classes="small_input")
                yield Button("Regex: OFF", id="regex_toggle")
            yield DataTable(id="rename_preview", zebra_stripes=True)
            yield Static("", id="rename_status")
            with Horizontal(id="rename_actions"):
                yield Button("Start Rename", id="rename_start", variant="primary")
                yield Button("Cancel", id="rename_cancel")

    def on_mount(self) -> None:
        table = self.query_one("#rename_preview", DataTable)
        table.add_columns("Current name", "New name", "Location")
        self._refresh_preview()
        self.query_one("#name_pattern", Input).focus()

    def _options(self) -> BatchRenameOptions:
        def number(selector: str, fallback: int) -> int:
            try:
                return int(self.query_one(selector, Input).value)
            except ValueError:
                return fallback

        return BatchRenameOptions(
            name_pattern=self.query_one("#name_pattern", Input).value,
            extension_pattern=self.query_one("#extension_pattern", Input).value,
            find_text=self.query_one("#find_text", Input).value,
            replace_text=self.query_one("#replace_text", Input).value,
            start=number("#counter_start", 1),
            step=number("#counter_step", 1),
            digits=number("#counter_digits", 1),
            regex=self.regex_enabled,
            delete_found_text=self.delete_found_text,
            append_counter=self.append_counter,
            counter_separator=self.query_one("#counter_separator", Input).value,
        )

    def _refresh_preview(self) -> None:
        pairs, errors = build_rename_pairs(self.items, self._options())
        table = self.query_one("#rename_preview", DataTable)
        table.clear()
        for pair in pairs:
            table.add_row(pair.source.name, pair.target.name, str(pair.source.parent))
        status = self.query_one("#rename_status", Static)
        if errors:
            status.update(f"Cannot start: {errors[0]}" + (
                f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
            ))
        else:
            changed = sum(pair.source != pair.target for pair in pairs)
            status.update(f"Ready: {changed} item(s) will be renamed.")

    @on(Input.Changed)
    def input_changed(self, _event: Input.Changed) -> None:
        self._refresh_preview()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        tokens = {
            "token_name": "[N]",
            "token_counter": "[C]",
            "token_date": "[YMD]",
            "token_time": "[hms]",
        }
        if button_id in tokens:
            field = self.query_one("#name_pattern", Input)
            field.value += tokens[button_id]
            field.focus()
            return
        if button_id == "regex_toggle":
            self.regex_enabled = not self.regex_enabled
            event.button.label = f"Regex: {'ON' if self.regex_enabled else 'OFF'}"
            self._refresh_preview()
            return
        if button_id == "delete_text_toggle":
            self.delete_found_text = not self.delete_found_text
            event.button.label = f"Delete found text: {'ON' if self.delete_found_text else 'OFF'}"
            self.query_one("#replace_text", Input).disabled = self.delete_found_text
            self._refresh_preview()
            return
        if button_id == "append_counter_toggle":
            self.append_counter = not self.append_counter
            event.button.label = f"End number: {'ON' if self.append_counter else 'OFF'}"
            self._refresh_preview()
            return
        if button_id == "rename_cancel":
            self.dismiss(None)
            return
        if button_id == "rename_start":
            pairs, errors = build_rename_pairs(self.items, self._options())
            if errors:
                self.app.notify(errors[0], title="Batch rename blocked")
                return
            self.dismiss(pairs)

    def key_escape(self) -> None:
        self.dismiss(None)
