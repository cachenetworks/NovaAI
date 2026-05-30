"""Minecraft driver via a Node/Mineflayer bridge.

Mineflayer is a Node.js library, so the actual bot lives in a small Node process
(``node/minecraft-bridge/bridge.js``) that exposes a local HTTP API. This Python
driver launches that process and talks to it over HTTP, keeping the LLM brain in
``GameAgent`` and only the low-level execution in Node.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import requests

from ..config import Config
from ..paths import ROOT_DIR
from .base import GameCommand, GameObservation

BRIDGE_DIR = ROOT_DIR / "node" / "minecraft-bridge"

_VERBS = [
    "follow", "come", "bring", "find_in_chests", "withdraw", "store", "drop",
    "find_ores", "mine", "collect", "craft", "place", "place_at",
    "attack", "punch", "defend", "equip", "equip_armor", "eat",
    "goto", "look", "sleep", "wake", "say", "wait", "stop",
]


class MinecraftDriver:
    name = "Minecraft"

    def __init__(self, config: Config, on_log: Callable[[str], None] | None = None) -> None:
        self.config = config
        self.bridge_port = config.mc_bridge_port
        self.base_url = f"http://127.0.0.1:{self.bridge_port}"
        self.on_log = on_log or (lambda _msg: None)
        self._proc: subprocess.Popen | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        node = self.config.node_path or shutil.which("node")
        if not node:
            raise RuntimeError(
                "Node.js was not found. Install Node 18+ and/or set NODE_PATH in .env."
            )
        bridge_js = BRIDGE_DIR / "bridge.js"
        if not bridge_js.exists():
            raise RuntimeError(f"Minecraft bridge not found at {bridge_js}.")
        if not (BRIDGE_DIR / "node_modules").exists():
            raise RuntimeError(
                "Minecraft bridge dependencies are not installed. Run "
                f"'npm install' in {BRIDGE_DIR}."
            )

        env_args = [
            node,
            str(bridge_js),
            "--host", str(self.config.mc_host),
            "--port", str(self.config.mc_port),
            "--username", str(self.config.mc_username),
            "--bridge-port", str(self.bridge_port),
            "--auth", str(self.config.mc_auth),
            "--owner", str(self.config.mc_owner_username or ""),
        ]
        if self.config.mc_profiles_folder:
            env_args += ["--profiles-folder", str(self.config.mc_profiles_folder)]
        if self.config.mc_version:
            env_args += ["--version", str(self.config.mc_version)]
        env_args += [
            "--viewer-port", str(self.config.mc_viewer_port),
            "--viewer-first-person", "true" if self.config.mc_viewer_first_person else "false",
        ]

        # Capture stdout so we can surface bridge logs (esp. the Microsoft
        # device-code login prompt) to the UI.
        self._proc = subprocess.Popen(
            env_args,
            cwd=str(BRIDGE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._pump_logs, daemon=True).start()
        # Microsoft auth (device-code flow) can take a while; allow more time.
        deadline = time.time() + (180 if self.config.mc_auth == "microsoft" else 30)
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError("The Minecraft bridge process exited during startup.")
            try:
                resp = requests.get(self.base_url + "/health", timeout=2)
                if resp.ok:
                    return
            except requests.RequestException:
                pass
            time.sleep(1.0)
        raise RuntimeError("Timed out waiting for the Minecraft bridge to connect.")

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            except Exception:
                pass
        self._proc = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _pump_logs(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    self.on_log(line)
        except Exception:
            pass

    # ── observe / act ───────────────────────────────────────────────────────────

    def observe(self) -> GameObservation:
        try:
            resp = requests.get(self.base_url + "/observe", timeout=5)
            raw = resp.json() if resp.ok else {}
        except requests.RequestException:
            raw = {}
        return GameObservation(raw=raw, text=self._format(raw))

    def describe_state(self) -> str:
        return self.observe().text

    def act(self, command: GameCommand) -> dict[str, Any]:
        try:
            resp = requests.post(
                self.base_url + "/act",
                json={"verb": command.verb, "args": command.args},
                timeout=self.config.game_tick_seconds + 20,
            )
            if resp.ok:
                return resp.json()
            return {"ok": False, "message": f"bridge HTTP {resp.status_code}"}
        except requests.RequestException as exc:
            return {"ok": False, "message": f"bridge unreachable: {exc}"}

    def available_verbs(self) -> list[str]:
        return list(_VERBS)

    def verbs_help(self) -> str:
        return (
            "How to use verbs (args go in 'args'):\n"
            "- find_ores {name?, exposed?}: returns visible ore coords. PREFER this, "
            "then mine {x,y,z} the result — legit, no x-ray (only ores you can see).\n"
            "- mine/collect {name} OR {x,y,z}; place {name} (under you); "
            "place_at {name,x,y,z} (build on a surface).\n"
            "- attack {target:'<player/mob>'} or {} for nearest hostile; "
            "punch {target:'<player>'} = one fist hit (use for 'smack <name>'); "
            "defend {seconds}.\n"
            "- equip {name,where?}; equip_armor {}; eat {}.\n"
            "- follow/come {player?} (defaults to owner); bring {name,count?}; "
            "find_in_chests {name}; withdraw {name,count?}; store {name,count?}; drop {name,count?}.\n"
            "- goto {x,z,y?}; sleep {}; wake {}; say {text}; wait {}; stop {}."
        )

    def viewer_url(self) -> str:
        return f"http://127.0.0.1:{self.config.mc_viewer_port}"

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _format(raw: dict[str, Any]) -> str:
        if not raw or not raw.get("connected", True):
            return "No world data yet (bridge connecting)."
        pos = raw.get("position", {})
        inv = raw.get("inventory", [])
        nearby = raw.get("nearbyBlocks", [])
        players = raw.get("players", [])
        hostiles = raw.get("nearbyHostiles", [])
        inv_text = ", ".join(f"{i.get('name')} x{i.get('count')}" for i in inv[:12]) or "empty"
        players_text = (
            ", ".join(f"{p.get('name')} ({p.get('distance')}m)" for p in players[:8]) or "none"
        )
        hostiles_text = (
            ", ".join(f"{h.get('name')} ({h.get('distance')}m)" for h in hostiles[:8]) or "none"
        )
        owner = raw.get("owner")
        if owner:
            visible = raw.get("ownerVisible")
            dist = raw.get("ownerDistance")
            owner_line = (
                f"Owner: {owner} — {'nearby at ' + str(dist) + 'm' if visible else 'not visible'}. "
                "Honor your owner's commands (follow/come/bring/find) and defend them from hostiles."
            )
        else:
            owner_line = "Owner: (none set)."
        lines = [
            owner_line,
            f"Health: {raw.get('health', '?')}/20, Food: {raw.get('food', '?')}/20",
            f"Position: x={pos.get('x','?')} y={pos.get('y','?')} z={pos.get('z','?')}",
            f"Time: {raw.get('timeOfDay', '?')}",
            f"Inventory: {inv_text}",
            f"Nearby blocks: {', '.join(nearby[:12]) or 'none'}",
            f"Players: {players_text}",
            f"Nearby hostiles: {hostiles_text}",
        ]
        return "\n".join(lines)
