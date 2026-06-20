"""
Tor Controller — Stem-based anonymous routing with IP rotation.
Routes all outbound traffic through Tor SOCKS5 proxy.
Includes Shadow Mode: global Tor routing + memory-only logging.
"""

import io
import logging
import os
import random
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests
import socks  # PySocks

logger = logging.getLogger("TorController")

TOR_SOCKS_PORT = 9050
TOR_CONTROL_PORT = 9051
TOR_PASSWORD = "ghost_engine_tor"


@dataclass
class TorIdentity:
    ip: str
    country: str
    circuit_id: str = ""


class TorController:
    def __init__(self, auto_install: bool = True):
        self.socks_port = TOR_SOCKS_PORT
        self.control_port = TOR_CONTROL_PORT
        self.password = TOR_PASSWORD
        self._tor_process = None
        self._stem = None
        self._controller = None
        self._available = False

        if auto_install:
            self._ensure_tor_binary()
        self._probe()

    def _ensure_tor_binary(self) -> None:
        if sys.platform != "win32":
            return
        tor_exe = Path("C:\\Users\\zafar\\scoop\\shims\\tor.exe")
        if tor_exe.exists():
            return
        # Check common paths
        candidates = [
            Path("C:\\Tor\\tor.exe"),
            Path("C:\\Program Files\\Tor\\tor.exe"),
            Path.home() / "scoop" / "apps" / "tor" / "current" / "tor.exe",
            Path.home() / "AppData" / "Local" / "Programs" / "Tor" / "tor.exe",
        ]
        for c in candidates:
            if c.exists():
                return

    def _probe(self) -> None:
        try:
            import stem
            self._stem = stem
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            result = s.connect_ex(("127.0.0.1", self.control_port))
            s.close()
            if result == 0:
                self._controller = stem.control.Controller.from_port(port=self.control_port)
                self._controller.authenticate(password=self.password)
                self._available = True
                logger.info("Tor controller connected on port %d", self.control_port)
                return
        except ImportError:
            logger.debug("stem library not available")
        except Exception as e:
            logger.debug("Tor control probe: %s", e)

        # Fallback: check if SOCKS port is open
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            result = s.connect_ex(("127.0.0.1", self.socks_port))
            s.close()
            if result == 0:
                self._available = True
                logger.info("Tor SOCKS proxy detected on port %d", self.socks_port)
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return self._available

    def new_identity(self) -> Optional[TorIdentity]:
        if self._controller:
            try:
                self._controller.signal("NEWNYM")
                time.sleep(2)
                ident = self.current_identity()
                logger.info("Tor new identity: %s", ident.ip if ident else "?")
                return ident
            except Exception as e:
                logger.warning("Tor new identity failed: %s", e)
        return None

    def current_identity(self) -> Optional[TorIdentity]:
        try:
            proxies = {"http": f"socks5://127.0.0.1:{self.socks_port}",
                       "https": f"socks5://127.0.0.1:{self.socks_port}"}
            r = requests.get("https://ipinfo.io/json", proxies=proxies, timeout=10)
            if r.ok:
                data = r.json()
                return TorIdentity(
                    ip=data.get("ip", "unknown"),
                    country=data.get("country", "unknown"),
                )
        except Exception as e:
            logger.debug("Tor identity check: %s", e)
        return None

    def enable_global_tor(self) -> bool:
        if not self._available:
            logger.warning("Tor not available — cannot enable global routing")
            return False
        socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", self.socks_port)
        socket.socket = socks.socksocket
        logger.info("Global Tor routing ENABLED (SOCKS5 :%d)", self.socks_port)

        # Also set environment variables for requests/urllib3
        os.environ["HTTP_PROXY"] = f"socks5://127.0.0.1:{self.socks_port}"
        os.environ["HTTPS_PROXY"] = f"socks5://127.0.0.1:{self.socks_port}"
        os.environ["REQUESTS_CA_BUNDLE"] = ""
        return True

    def disable_global_tor(self) -> None:
        socket.socket = socket._socketobject if hasattr(socket, '_socketobject') else socket.socket
        for k in ["HTTP_PROXY", "HTTPS_PROXY", "REQUESTS_CA_BUNDLE"]:
            os.environ.pop(k, None)
        logger.info("Global Tor routing DISABLED")

    def get_session(self) -> requests.Session:
        session = requests.Session()
        if self._available:
            session.proxies = {
                "http": f"socks5://127.0.0.1:{self.socks_port}",
                "https": f"socks5://127.0.0.1:{self.socks_port}",
            }
        return session

    def start_tor_daemon(self, force_stem: bool = True) -> bool:
        if self._available:
            return True

        data_dir = Path(__file__).resolve().parent / "agent_data" / "tor_data"
        data_dir.mkdir(parents=True, exist_ok=True)

        if force_stem:
            try:
                import stem.process as stem_proc
                self._tor_process = stem_proc.launch_tor_with_config(
                    config={
                        "ControlPort": str(self.control_port),
                        "SocksPort": str(self.socks_port),
                        "DataDirectory": str(data_dir),
                        "Log": ["NOTICE stdout"],
                        "ExitNodes": "{any}",
                        "GeoIPFile": "",
                        "GeoIPv6File": "",
                    },
                    take_ownership=True,
                    timeout=60,
                )
                time.sleep(2)
                self._probe()
                if self._available:
                    logger.info("Tor launched via stem.process on :%d", self.socks_port)
                    return True
            except Exception as e:
                logger.warning("stem.process launch failed: %s", e)

        try:
            import shutil
            tor_exe = shutil.which("tor") or "tor.exe"
            self._tor_process = subprocess.Popen(
                [tor_exe, f"--ControlPort={self.control_port}",
                 f"--SocksPort={self.socks_port}",
                 f"--DataDirectory={data_dir}",
                 "--quiet"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(3)
            self._probe()
            return self._available
        except Exception as e:
            logger.warning("Tor binary fallback failed: %s", e)
            return False

    def enter_shadow_mode(self) -> bool:
        """Full stealth: Tor global proxy + memory-only logging (no disk writes)."""
        if not self.enable_global_tor():
            logger.warning("Shadow mode: Tor routing failed")
            return False

        # Replace all file handlers with a RAM buffer
        root = logging.getLogger()
        self._shadow_buffer = io.StringIO()
        self._shadow_handler = logging.StreamHandler(self._shadow_buffer)
        self._shadow_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(message)s")
        )

        removed = 0
        for h in list(root.handlers):
            if isinstance(h, logging.FileHandler) or hasattr(h, "baseFilename"):
                root.removeHandler(h)
                removed += 1
        root.addHandler(self._shadow_handler)

        # Also silence our own log file path
        logger.info("SHADOW MODE ACTIVE — Tor routing + RAM-only logs (%d file handlers removed)", removed)
        print("Ghost Engine entered Shadow Mode. Stealth: 100%")
        return True

    def disable_shadow_mode(self) -> None:
        """Restore file logging and optionally disable Tor proxy."""
        self.disable_global_tor()
        root = logging.getLogger()
        if hasattr(self, "_shadow_handler") and self._shadow_handler in root.handlers:
            root.removeHandler(self._shadow_handler)
        logger.info("Shadow mode deactivated")

    def get_shadow_log(self) -> str:
        """Return buffered RAM log contents (if in shadow mode)."""
        if hasattr(self, "_shadow_buffer"):
            return self._shadow_buffer.getvalue()
        return ""

    @property
    def is_shadow(self) -> bool:
        return hasattr(self, "_shadow_handler") and self._shadow_handler in logging.getLogger().handlers
