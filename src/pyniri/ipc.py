# pyniri: Pythonic IPC bindings for the niri scroll-tiling compositor
# Copyright (C) 2026 Thiago <killown.matrix@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import socket
import json
import os
import typing
from typing import Any, List, Optional, Dict, Union

# --- Type Helpers & Enums ---


class NiriError(Exception):
    pass


class LayoutSwitchTarget:
    NEXT = "next"
    PREV = "prev"

    @staticmethod
    def index(idx: int) -> Dict[str, int]:
        return {"Index": idx}


class ColumnDisplay:
    NORMAL = "Normal"
    TABBED = "Tabbed"


class WorkspaceReference:
    """Helpers to generate WorkspaceReferenceArgs"""

    @staticmethod
    def id(ws_id: int) -> Dict[str, int]:
        return {"Id": ws_id}

    @staticmethod
    def index(idx: int) -> Dict[str, int]:
        return {"Index": idx}

    @staticmethod
    def name(name: str) -> Dict[str, str]:
        return {"Name": name}


class SizeChange:
    """Helpers for SizeChange variants"""

    @staticmethod
    def set_fixed(pixels: int) -> Dict[str, int]:
        return {"SetFixed": pixels}

    @staticmethod
    def set_proportion(percent: float) -> Dict[str, float]:
        return {"SetProportion": percent}

    @staticmethod
    def adjust_fixed(pixels: int) -> Dict[str, int]:
        return {"AdjustFixed": pixels}

    @staticmethod
    def adjust_proportion(percent: float) -> Dict[str, float]:
        return {"AdjustProportion": percent}


class PositionChange:
    """Helpers for PositionChange variants"""

    @staticmethod
    def set_fixed(pixels: float) -> Dict[str, float]:
        return {"SetFixed": pixels}

    @staticmethod
    def set_proportion(percent: float) -> Dict[str, float]:
        return {"SetProportion": percent}

    @staticmethod
    def adjust_fixed(pixels: float) -> Dict[str, float]:
        return {"AdjustFixed": pixels}

    @staticmethod
    def adjust_proportion(percent: float) -> Dict[str, float]:
        return {"AdjustProportion": percent}


class OutputAction:
    """Helpers for Request::Output actions"""

    OFF = "Off"
    ON = "On"

    @staticmethod
    def mode(width: int, height: int, refresh: float = None) -> Dict[str, Any]:  # pyright: ignore
        """Custom Mode Config"""
        mode_def = {"width": width, "height": height, "refresh": refresh}
        return {"CustomMode": {"mode": mode_def}}

    @staticmethod
    def scale(value: float) -> Dict[str, Dict[str, float]]:
        return {"Scale": {"scale": {"Specific": value}}}  # pyright: ignore

    @staticmethod
    def transform(rotation: str) -> Dict[str, Dict[str, str]]:
        """Valid: "Normal", "90", "180", "270", "Flipped", etc."""
        return {"Transform": {"transform": rotation}}

    @staticmethod
    def position(x: int, y: int) -> Dict[str, Dict[str, Dict[str, int]]]:
        return {"Position": {"position": {"Specific": {"x": x, "y": y}}}}  # pyright: ignore


# --- Main Class ---


class NiriSocket:
    def __init__(self, socket_path: Optional[str] = None):
        if socket_path is None:
            socket_path = os.getenv("NIRI_SOCKET")

        if not socket_path:
            raise NiriError("NIRI_SOCKET not found. Ensure niri is running.")

        self.socket_path = socket_path
        self._timeout = 5.0
        self._event_sock = None

    def _send(self, payload: Any) -> Any:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self._timeout)
                client.connect(self.socket_path)

                # Ensure payload is serialized then suffixed with newline
                msg = json.dumps(payload)
                if isinstance(msg, bytes):
                    msg += b"\n"
                else:
                    msg += "\n"
                    msg = msg.encode("utf-8")

                client.sendall(msg)

                with client.makefile("r", encoding="utf-8") as f:
                    line = f.readline()
                    if not line:
                        raise NiriError("Empty response from compositor")
                    response = json.loads(line)

                if isinstance(response, dict):
                    if "Ok" in response:
                        return response["Ok"]
                    if "Err" in response:
                        raise NiriError(f"Niri: {response['Err']}")

                return response
        except (socket.error, json.JSONDecodeError) as e:
            raise NiriError(f"IPC failure: {e}")

    def _action(self, name: str, **kwargs) -> bool:
        """
        Niri uses Enum-style variants.
        Unit variants: {"Action": "ToggleOverview"}
        Struct variants: {"Action": {"FocusWindow": {"id": 123}}}
        """
        payload = {"Action": {name: kwargs}}
        try:
            res = self._send(payload)
            return res == "Handled" or res is None
        except NiriError:
            return False

    # =========================================================================
    # EVENT STREAMING (Watch)
    # =========================================================================

    def apply_event(self, event: Dict[str, Any]):
        """
        Applies a Niri event to the local state.
        Implements the logic from the Rust EventStreamStatePart.
        """
        # --- Workspace State ---
        if "WorkspacesChanged" in event:
            self.workspaces = {
                ws["id"]: ws for ws in event["WorkspacesChanged"]["workspaces"]
            }

        elif "WorkspaceActivated" in event:
            active_id = event["WorkspaceActivated"]["id"]
            focused = event["WorkspaceActivated"].get("focused", False)

            # Find the output of the activated workspace
            output = self.workspaces.get(active_id, {}).get("output")

            for ws in self.workspaces.values():
                if ws.get("output") == output:
                    ws["is_active"] = ws["id"] == active_id
                if focused:
                    ws["is_focused"] = ws["id"] == active_id

        # --- Window State ---
        elif "WindowsChanged" in event:
            self.windows = {
                win["id"]: win for win in event["WindowsChanged"]["windows"]
            }

        elif "WindowOpenedOrChanged" in event:
            win = event["WindowOpenedOrChanged"]["window"]
            self.windows[win["id"]] = win
            if win.get("is_focused"):
                for w in self.windows.values():
                    if w["id"] != win["id"]:
                        w["is_focused"] = False

        elif "WindowClosed" in event:
            self.windows.pop(event["WindowClosed"]["id"], None)

        elif "WindowFocusChanged" in event:
            focused_id = event["WindowFocusChanged"].get("id")
            for win in self.windows.values():
                win["is_focused"] = win["id"] == focused_id

        # --- Keyboard & UI State ---
        elif "KeyboardLayoutsChanged" in event:
            self.keyboard_layouts = event["KeyboardLayoutsChanged"]["keyboard_layouts"]

        elif "KeyboardLayoutSwitched" in event:
            if self.keyboard_layouts:
                self.keyboard_layouts["current_idx"] = event["KeyboardLayoutSwitched"][
                    "idx"
                ]

        elif "OverviewOpenedOrClosed" in event:
            self.is_overview_open = event["OverviewOpenedOrClosed"]["is_open"]

    # =========================================================================
    # EVENT STREAMING (Watch)
    # =========================================================================

    def watch(self) -> typing.Generator[Dict[str, Any], None, None]:
        """
        Yields raw events from the Niri EventStream.
        """
        try:
            self._event_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._event_sock.connect(self.socket_path)

            payload = json.dumps("EventStream") + "\n"
            self._event_sock.sendall(payload.encode("utf-8"))

            f = self._event_sock.makefile("r", encoding="utf-8", buffering=1)

            while True:
                line = f.readline()
                if not line:
                    break

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "Ok" in data:
                    yield {"status": "connected", "raw": data}
                elif "Handled" in data:
                    continue
                else:
                    yield data

        except socket.error as e:
            raise NiriError(f"EventStream failed: {e}")
        finally:
            self.stop_watching()

    def stop_watching(self):
        if self._event_sock:
            try:
                self._event_sock.close()
            except:
                pass
            self._event_sock = None

    # =========================================================================
    # REQUESTS (Information Retrieval)
    # =========================================================================

    def get_version(self) -> str:
        return self._send("Version")["Version"]

    def get_outputs(self) -> Dict[str, Any]:
        return self._send("Outputs")["Outputs"]

    def get_workspaces(self) -> List[Dict[str, Any]]:
        return self._send("Workspaces")["Workspaces"]

    def get_windows(self) -> List[Dict[str, Any]]:
        return self._send("Windows")["Windows"]

    def get_layers(self) -> List[Dict[str, Any]]:
        return self._send("Layers")["Layers"]

    def get_keyboard_layouts(self) -> Dict[str, Any]:
        return self._send("KeyboardLayouts")["KeyboardLayouts"]

    def get_focused_output(self) -> Optional[Dict[str, Any]]:
        return self._send("FocusedOutput")["FocusedOutput"]

    def get_focused_window(self) -> Optional[Dict[str, Any]]:
        return self._send("FocusedWindow")["FocusedWindow"]

    def pick_window(self) -> Optional[Dict[str, Any]]:
        return self._send("PickWindow")["PickedWindow"]

    def pick_color(self) -> Optional[Dict[str, float]]:
        return self._send("PickColor")["PickedColor"]

    def get_overview_state(self) -> Dict[str, bool]:
        return self._send("OverviewState")["OverviewState"]

    def get_casts(self) -> List[Dict[str, Any]]:
        return self._send("Casts")["Casts"]

    def configure_output(self, output_name: str, config: Dict[str, Any]) -> str:
        """
        Send a specific configuration to an output.
        Use OutputAction helpers to generate the config dict.
        """
        payload = {"Output": {"output": output_name, "action": config}}
        return self._send(payload)

    # =========================================================================
    # ACTIONS (Commands)
    # =========================================================================

    # --- System ---
    def quit(self, skip_confirmation: bool = False):
        return self._action("Quit", skip_confirmation=skip_confirmation)

    def power_off_monitors(self):
        return self._action("PowerOffMonitors")

    def power_on_monitors(self):
        return self._action("PowerOnMonitors")

    # --- System ---

    def spawn(self, command: Union[List[str], str]) -> bool:
        """
        Spawns a process directly.
        Safeguard: Automatically converts string input to the required List[str].
        """
        if isinstance(command, str):
            command = command.split()

        return self._action("Spawn", command=command)

    def spawn_sh(self, command: Union[List[str], str]) -> bool:
        """
        Spawns a process through the shell (sh -c).
        Safeguard: Automatically converts list input to the required String.
        """
        if isinstance(command, list):
            command = " ".join(command)

        return self._action("SpawnSh", command=command)

    def do_screen_transition(self, delay_ms: Optional[int] = None):
        return self._action("DoScreenTransition", delay_ms=delay_ms)

    def load_config_file(self, path: Optional[str] = None):
        return self._action("LoadConfigFile", path=path)

    # --- Screenshots ---
    def screenshot(self, path: Optional[str] = None, show_pointer: bool = True):
        return self._action("Screenshot", path=path, show_pointer=show_pointer)

    def screenshot_screen(
        self,
        path: Optional[str] = None,
        write_to_disk: bool = True,
        show_pointer: bool = True,
    ):
        return self._action(
            "ScreenshotScreen",
            path=path,
            write_to_disk=write_to_disk,
            show_pointer=show_pointer,
        )

    def screenshot_window(
        self,
        id: Optional[int] = None,
        path: Optional[str] = None,
        write_to_disk: bool = True,
        show_pointer: bool = False,
    ):
        return self._action(
            "ScreenshotWindow",
            id=id,
            path=path,
            write_to_disk=write_to_disk,
            show_pointer=show_pointer,
        )

    # --- Window Management ---
    def close_window(self, id: Optional[int] = None):
        return self._action("CloseWindow", id=id)

    def fullscreen_window(self, id: Optional[int] = None):
        return self._action("FullscreenWindow", id=id)

    def toggle_windowed_fullscreen(self, id: Optional[int] = None):
        return self._action("ToggleWindowedFullscreen", id=id)

    def toggle_window_floating(self, id: Optional[int] = None):
        return self._action("ToggleWindowFloating", id=id)

    def move_window_to_floating(self, id: Optional[int] = None):
        return self._action("MoveWindowToFloating", id=id)

    def move_window_to_tiling(self, id: Optional[int] = None):
        return self._action("MoveWindowToTiling", id=id)

    def move_floating_window(self, x: Dict, y: Dict, id: Optional[int] = None):
        """Use PositionChange helpers for x/y"""
        return self._action("MoveFloatingWindow", id=id, x=x, y=y)

    def toggle_window_rule_opacity(self, id: Optional[int] = None):
        return self._action("ToggleWindowRuleOpacity", id=id)

    def toggle_window_urgent(self, id: int):
        return self._action("ToggleWindowUrgent", id=id)

    def set_window_urgent(self, id: int):
        return self._action("SetWindowUrgent", id=id)

    def unset_window_urgent(self, id: int):
        return self._action("UnsetWindowUrgent", id=id)

    def toggle_keyboard_shortcuts_inhibit(self):
        return self._action("ToggleKeyboardShortcutsInhibit")

    # --- Focus (Windows) ---
    def focus_window(self, id: int):
        return self._action("FocusWindow", id=id)

    def focus_window_in_column(self, index: int):
        return self._action("FocusWindowInColumn", index=index)

    def focus_window_previous(self):
        return self._action("FocusWindowPrevious")

    def focus_window_top(self):
        return self._action("FocusWindowTop")

    def focus_window_bottom(self):
        return self._action("FocusWindowBottom")

    def focus_window_up(self):
        return self._action("FocusWindowUp")

    def focus_window_down(self):
        return self._action("FocusWindowDown")

    def focus_window_down_or_top(self):
        return self._action("FocusWindowDownOrTop")

    def focus_window_up_or_bottom(self):
        return self._action("FocusWindowUpOrBottom")

    def focus_window_or_monitor_up(self):
        return self._action("FocusWindowOrMonitorUp")

    def focus_window_or_monitor_down(self):
        return self._action("FocusWindowOrMonitorDown")

    def focus_window_or_workspace_up(self):
        return self._action("FocusWindowOrWorkspaceUp")

    def focus_window_or_workspace_down(self):
        return self._action("FocusWindowOrWorkspaceDown")

    # --- Focus (Columns) ---
    def focus_column(self, index: int):
        return self._action("FocusColumn", index=index)

    def focus_column_left(self):
        return self._action("FocusColumnLeft")

    def focus_column_right(self):
        return self._action("FocusColumnRight")

    def focus_column_first(self):
        return self._action("FocusColumnFirst")

    def focus_column_last(self):
        return self._action("FocusColumnLast")

    def focus_column_right_or_first(self):
        return self._action("FocusColumnRightOrFirst")

    def focus_column_left_or_last(self):
        return self._action("FocusColumnLeftOrLast")

    def focus_column_or_monitor_left(self):
        return self._action("FocusColumnOrMonitorLeft")

    def focus_column_or_monitor_right(self):
        return self._action("FocusColumnOrMonitorRight")

    # --- Focus (Workspace) ---
    def focus_workspace(self, reference: Union[Dict, int, str]):
        """
        Use WorkspaceReference helper or pass raw dict/int/str.
        If int/str passed, tries to infer Index/Name.
        """
        ref = self._resolve_workspace_ref(reference)
        return self._action("FocusWorkspace", reference=ref)

    def focus_workspace_down(self):
        return self._action("FocusWorkspaceDown")

    def focus_workspace_up(self):
        return self._action("FocusWorkspaceUp")

    def focus_workspace_previous(self):
        return self._action("FocusWorkspacePrevious")

    # --- Focus (Monitor) ---
    def focus_monitor(self, output: str):
        return self._action("FocusMonitor", output=output)

    def focus_monitor_left(self):
        return self._action("FocusMonitorLeft")

    def focus_monitor_right(self):
        return self._action("FocusMonitorRight")

    def focus_monitor_down(self):
        return self._action("FocusMonitorDown")

    def focus_monitor_up(self):
        return self._action("FocusMonitorUp")

    def focus_monitor_previous(self):
        return self._action("FocusMonitorPrevious")

    def focus_monitor_next(self):
        return self._action("FocusMonitorNext")

    # --- Layout & Tiling ---
    def switch_layout(self, layout: Union[str, Dict]):
        return self._action("SwitchLayout", layout=layout)

    def toggle_column_tabbed_display(self):
        return self._action("ToggleColumnTabbedDisplay")

    def set_column_display(self, display: str):
        return self._action("SetColumnDisplay", display=display)

    def focus_floating(self):
        return self._action("FocusFloating")

    def focus_tiling(self):
        return self._action("FocusTiling")

    def switch_focus_between_floating_and_tiling(self):
        return self._action("SwitchFocusBetweenFloatingAndTiling")

    # --- Movement (Window) ---
    def move_window_up(self):
        return self._action("MoveWindowUp")

    def move_window_down(self):
        return self._action("MoveWindowDown")

    def move_window_down_or_to_workspace_down(self):
        return self._action("MoveWindowDownOrToWorkspaceDown")

    def move_window_up_or_to_workspace_up(self):
        return self._action("MoveWindowUpOrToWorkspaceUp")

    def move_window_to_workspace(
        self,
        reference: Union[Dict, int, str],
        window_id: Optional[int] = None,
        focus: bool = True,
    ):
        ref = self._resolve_workspace_ref(reference)
        return self._action(
            "MoveWindowToWorkspace", reference=ref, window_id=window_id, focus=focus
        )

    def move_window_to_workspace_down(self, focus: bool = True):
        return self._action("MoveWindowToWorkspaceDown", focus=focus)

    def move_window_to_workspace_up(self, focus: bool = True):
        return self._action("MoveWindowToWorkspaceUp", focus=focus)

    def move_window_to_monitor(self, output: str, id: Optional[int] = None):
        return self._action("MoveWindowToMonitor", output=output, id=id)

    def move_window_to_monitor_left(self):
        return self._action("MoveWindowToMonitorLeft")

    def move_window_to_monitor_right(self):
        return self._action("MoveWindowToMonitorRight")

    def move_window_to_monitor_up(self):
        return self._action("MoveWindowToMonitorUp")

    def move_window_to_monitor_down(self):
        return self._action("MoveWindowToMonitorDown")

    def move_window_to_monitor_previous(self):
        return self._action("MoveWindowToMonitorPrevious")

    def move_window_to_monitor_next(self):
        return self._action("MoveWindowToMonitorNext")

    def consume_or_expel_window_left(self, id: Optional[int] = None):
        return self._action("ConsumeOrExpelWindowLeft", id=id)

    def consume_or_expel_window_right(self, id: Optional[int] = None):
        return self._action("ConsumeOrExpelWindowRight", id=id)

    def consume_window_into_column(self):
        return self._action("ConsumeWindowIntoColumn")

    def expel_window_from_column(self):
        return self._action("ExpelWindowFromColumn")

    def swap_window_left(self):
        return self._action("SwapWindowLeft")

    def swap_window_right(self):
        return self._action("SwapWindowRight")

    def center_window(self, id: Optional[int] = None):
        return self._action("CenterWindow", id=id)

    # --- Movement (Column) ---
    def move_column_left(self):
        return self._action("MoveColumnLeft")

    def move_column_right(self):
        return self._action("MoveColumnRight")

    def move_column_to_first(self):
        return self._action("MoveColumnToFirst")

    def move_column_to_last(self):
        return self._action("MoveColumnToLast")

    def move_column_to_index(self, index: int):
        return self._action("MoveColumnToIndex", index=index)

    def move_column_left_or_to_monitor_left(self):
        return self._action("MoveColumnLeftOrToMonitorLeft")

    def move_column_right_or_to_monitor_right(self):
        return self._action("MoveColumnRightOrToMonitorRight")

    def move_column_to_workspace(
        self, reference: Union[Dict, int, str], focus: bool = True
    ):
        ref = self._resolve_workspace_ref(reference)
        return self._action("MoveColumnToWorkspace", reference=ref, focus=focus)

    def move_column_to_workspace_down(self, focus: bool = True):
        return self._action("MoveColumnToWorkspaceDown", focus=focus)

    def move_column_to_workspace_up(self, focus: bool = True):
        return self._action("MoveColumnToWorkspaceUp", focus=focus)

    def move_column_to_monitor(self, output: str):
        return self._action("MoveColumnToMonitor", output=output)

    def move_column_to_monitor_left(self):
        return self._action("MoveColumnToMonitorLeft")

    def move_column_to_monitor_right(self):
        return self._action("MoveColumnToMonitorRight")

    def move_column_to_monitor_up(self):
        return self._action("MoveColumnToMonitorUp")

    def move_column_to_monitor_down(self):
        return self._action("MoveColumnToMonitorDown")

    def move_column_to_monitor_previous(self):
        return self._action("MoveColumnToMonitorPrevious")

    def move_column_to_monitor_next(self):
        return self._action("MoveColumnToMonitorNext")

    def center_column(self):
        return self._action("CenterColumn")

    def center_visible_columns(self):
        return self._action("CenterVisibleColumns")

    # --- Movement (Workspace) ---
    def move_workspace_down(self):
        return self._action("MoveWorkspaceDown")

    def move_workspace_up(self):
        return self._action("MoveWorkspaceUp")

    def move_workspace_to_index(self, index: int, reference: Optional[Dict] = None):
        return self._action("MoveWorkspaceToIndex", index=index, reference=reference)

    def move_workspace_to_monitor(self, output: str, reference: Optional[Dict] = None):
        return self._action(
            "MoveWorkspaceToMonitor", output=output, reference=reference
        )

    def move_workspace_to_monitor_left(self):
        return self._action("MoveWorkspaceToMonitorLeft")

    def move_workspace_to_monitor_right(self):
        return self._action("MoveWorkspaceToMonitorRight")

    def move_workspace_to_monitor_up(self):
        return self._action("MoveWorkspaceToMonitorUp")

    def move_workspace_to_monitor_down(self):
        return self._action("MoveWorkspaceToMonitorDown")

    def move_workspace_to_monitor_previous(self):
        return self._action("MoveWorkspaceToMonitorPrevious")

    def move_workspace_to_monitor_next(self):
        return self._action("MoveWorkspaceToMonitorNext")

    def set_workspace_name(self, name: str, workspace: Optional[Dict] = None):
        return self._action("SetWorkspaceName", name=name, workspace=workspace)  # pyright: ignore

    def unset_workspace_name(self, reference: Optional[Dict] = None):
        return self._action("UnsetWorkspaceName", reference=reference)

    # --- Resizing ---
    def set_window_width(self, change: Dict, id: Optional[int] = None):
        return self._action("SetWindowWidth", change=change, id=id)

    def set_window_height(self, change: Dict, id: Optional[int] = None):
        return self._action("SetWindowHeight", change=change, id=id)

    def reset_window_height(self, id: Optional[int] = None):
        return self._action("ResetWindowHeight", id=id)

    def switch_preset_column_width(self):
        return self._action("SwitchPresetColumnWidth")

    def switch_preset_column_width_back(self):
        return self._action("SwitchPresetColumnWidthBack")

    def switch_preset_window_width(self, id: Optional[int] = None):
        return self._action("SwitchPresetWindowWidth", id=id)

    def switch_preset_window_width_back(self, id: Optional[int] = None):
        return self._action("SwitchPresetWindowWidthBack", id=id)

    def switch_preset_window_height(self, id: Optional[int] = None):
        return self._action("SwitchPresetWindowHeight", id=id)

    def switch_preset_window_height_back(self, id: Optional[int] = None):
        return self._action("SwitchPresetWindowHeightBack", id=id)

    # --- Maximization Actions ---

    def maximize_column(self, id: Optional[int] = None):
        """
        Toggles the maximized state of a column.
        If id is None, uses the focused column.
        """
        return self._action("MaximizeColumn", id=id)

    def maximize_window_to_edges(self, id: Optional[int] = None):
        """
        Toggles the maximized-to-edges state of a window.
        If id is None, uses the focused window.
        """
        return self._action("MaximizeWindowToEdges", id=id)

    # ---------------------------------------------

    def set_column_width(self, change: Dict):
        return self._action("SetColumnWidth", change=change)

    def expand_column_to_available_width(self):
        return self._action("ExpandColumnToAvailableWidth")

    # --- Debug / Extras ---
    def show_hotkey_overlay(self):
        return self._action("ShowHotkeyOverlay")

    def toggle_debug_tint(self):
        return self._action("ToggleDebugTint")

    def debug_toggle_opaque_regions(self):
        return self._action("DebugToggleOpaqueRegions")

    def debug_toggle_damage(self):
        return self._action("DebugToggleDamage")

    # --- Screencast ---
    def set_dynamic_cast_window(self, id: Optional[int] = None):
        return self._action("SetDynamicCastWindow", id=id)

    def set_dynamic_cast_monitor(self, output: Optional[str] = None):
        return self._action("SetDynamicCastMonitor", output=output)

    def clear_dynamic_cast_target(self):
        return self._action("ClearDynamicCastTarget")

    def stop_cast(self, session_id: int):
        return self._action("StopCast", session_id=session_id)

    # --- Overview ---
    def toggle_overview(self) -> bool:
        """
        Toggle the Niri overview mode.
        """
        try:
            return self._send({"Action": {"ToggleOverview": {}}}) == "Handled"
        except NiriError:
            return False

    def open_overview(self) -> bool:
        try:
            return self._send({"Action": {"OpenOverview": {}}}) == "Handled"
        except NiriError:
            return False

    def close_overview(self) -> bool:
        try:
            return self._send({"Action": {"CloseOverview": {}}}) == "Handled"
        except NiriError:
            return False

    # --- Helpers ---

    def _resolve_workspace_ref(
        self, ref: Union[Dict, int, str, None]
    ) -> Optional[Dict]:
        """Resolves int to Index and str to Name automatically."""
        if ref is None:
            return None
        if isinstance(ref, dict):
            return ref
        if isinstance(ref, int):
            return WorkspaceReference.index(ref)
        if isinstance(ref, str):
            return WorkspaceReference.name(ref)

    def get_cursor_position(self) -> Dict[str, float]:
        """
        Returns the current cursor position in absolute coordinates.
        """
        return self._send("CursorPosition")["CursorPosition"]

    def move_cursor(self, x: float, y: float) -> bool:
        """
        Moves the cursor to absolute coordinates.
        """
        try:
            return self._send({"MoveCursor": {"x": x, "y": y}}) == "Handled"
        except NiriError:
            return False
