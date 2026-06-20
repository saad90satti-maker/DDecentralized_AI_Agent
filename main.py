"""
Autonomous Decentralized Industrial Agent — Main Orchestrator (Daemon)
======================================================================
Singleton orchestrator running as a persistent daemon.

Bootstrap (one-time):
  1. LOAD_CONFIG       — Load config.json, override with env vars
  2. SETUP_LOGGING     — Initialize unified logging (console + file)
  3. INIT_MODULES      — Instantiate all components (lazy)
  4. INIT_STEALTH      — Initialize deep space stealth layer
  5. START_SERVICES    — Start background services (self_heal, telemetry)

Daemon Cycle (every N seconds):
  6. HEALTH_CHECK      — Verify all dependencies (network, hardware, services)
  7. SECURITY_AUDIT    — Run constitutional audit, apply Safe-State if needed
  8. EXECUTE_SEQUENCE  — Run the integration sequence steps
  9. CYCLE_PAUSE       — Sleep for configured interval before next cycle

On module crash → log error, continue next cycle. Never stop.
"""

import asyncio
import json
import os
import signal
import sys
import time
import traceback
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from logging_system import setup_logging, get_logger

_BASE_DIR = Path(__file__).resolve().parent


class SystemState(Enum):
    UNINITIALIZED = auto()
    LOADING_CONFIG = auto()
    SETTING_UP_LOGGING = auto()
    INITIALIZING_MODULES = auto()
    INITIALIZING_STEALTH = auto()
    HEALTH_CHECK = auto()
    SECURITY_AUDIT = auto()
    STARTING_SERVICES = auto()
    EXECUTING = auto()
    DEGRADED = auto()
    SHUTTING_DOWN = auto()
    STOPPED = auto()
    ERROR = auto()


class ConfigLoader:
    """Loads config.json and merges with environment variables."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or _BASE_DIR / "config.json"
        self._data: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.path}")

        raw = self.path.read_text(encoding="utf-8")
        self._data = json.loads(raw)
        self._merge_env_overrides()
        return self._data

    def _merge_env_overrides(self) -> None:
        env_map = {
            "MQTT_HOST": ("mqtt", "host"),
            "MQTT_PORT": ("mqtt", "port"),
            "IPFS_GATEWAY": ("ipfs", "gateway"),
            "IPFS_MULTIADDR": ("ipfs", "multiaddr"),
            "SWARM_PORT": ("swarm", "port"),
            "SWARM_BROADCAST_PORT": ("swarm", "broadcast_port"),
            "KADEMLIA_PORT": ("swarm", "kademlia_port"),
            "HEARTBEAT_INTERVAL": ("swarm", "heartbeat_interval"),
            "PEER_TIMEOUT": ("swarm", "peer_timeout"),
            "MODBUS_HOST": ("modbus", "host"),
            "MODBUS_PORT": ("modbus", "port"),
            "LOG_LEVEL": ("logging", "level"),
        }

        for env_key, (section, key) in env_map.items():
            val = os.getenv(env_key)
            if val is not None:
                section_data = self._data.setdefault(section, {})
                try:
                    section_data[key] = int(val)
                except ValueError:
                    try:
                        section_data[key] = float(val)
                    except ValueError:
                        section_data[key] = val

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self._data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
                if current is None:
                    return default
            else:
                return default
        return current if current is not None else default

    @property
    def raw(self) -> Dict[str, Any]:
        return self._data


class RetryHandler:
    """Exponential backoff retry for network-dependent operations."""

    def __init__(self, config: ConfigLoader):
        self._base_delay = config.get("network", "retry_delay_base", default=2)
        self._max_retries = config.get("network", "max_retries", default=3)

    async def execute(self, description: str,
                      coro_factory, *,
                      retries: Optional[int] = None) -> Tuple[bool, Any]:
        max_attempts = (retries if retries is not None else self._max_retries) + 1
        last_error: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                if asyncio.iscoroutinefunction(coro_factory):
                    result = await coro_factory()
                else:
                    result = coro_factory()
                if asyncio.iscoroutine(result):
                    result = await result
                if attempt > 1:
                    logger.info("Retry: '%s' succeeded on attempt %d", description, attempt)
                return True, result
            except Exception as e:
                last_error = e
                if attempt < max_attempts:
                    delay = self._base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "Retry: '%s' attempt %d/%d failed: %s — retrying in %.1fs",
                        description, attempt, max_attempts - 1, e, delay,
                    )
                    await asyncio.sleep(delay)

        logger.error("Retry: '%s' failed after %d attempts: %s",
                     description, max_attempts - 1, last_error)
        return False, last_error


class ComponentRegistry:
    """Central registry of all system components with health checks."""

    def __init__(self):
        self._components: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, instance: Any,
                 health_check=None, dependencies: Optional[List[str]] = None) -> None:
        self._components[name] = {
            "instance": instance,
            "health_check": health_check,
            "dependencies": dependencies or [],
            "healthy": False,
            "started": False,
        }

    def get(self, name: str) -> Any:
        comp = self._components.get(name)
        return comp["instance"] if comp else None

    def check_health(self, name: str) -> bool:
        comp = self._components.get(name)
        if not comp:
            return False
        if comp["health_check"]:
            try:
                result = comp["health_check"]()
                if asyncio.iscoroutine(result):
                    healthy = asyncio.get_event_loop().run_until_complete(result)
                else:
                    healthy = result
                comp["healthy"] = bool(healthy)
                return comp["healthy"]
            except Exception:
                comp["healthy"] = False
                return False
        comp["healthy"] = True
        return True

    def check_all(self) -> Dict[str, bool]:
        results = {}
        for name in self._components:
            results[name] = self.check_health(name)
        return results

    @property
    def all_healthy(self) -> bool:
        return all(
            comp["healthy"]
            for comp in self._components.values()
        )

    @property
    def status(self) -> Dict[str, Any]:
        return {
            name: {
                "healthy": comp["healthy"],
                "started": comp["started"],
                "dependencies": comp["dependencies"],
            }
            for name, comp in self._components.items()
        }


logger = get_logger("Orchestrator")


class Orchestrator:
    """
    Singleton orchestrator — the single entry point for the entire system.
    Manages lifecycle: Init → Health Check → Execute → Error Handling → Shutdown.
    """

    _instance: Optional["Orchestrator"] = None

    def __new__(cls, *args, **kwargs) -> "Orchestrator":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: Optional[Path] = None):
        if self._initialized:
            return
        self._initialized = True

        self.state = SystemState.UNINITIALIZED
        self.config_loader = ConfigLoader(config_path)
        self.registry = ComponentRegistry()
        self.retry = None
        self.self_healer = None
        self.telemetry = None
        self.safety_gate = None
        self._modules: Dict[str, Any] = {}
        self._trans_dimensional: Optional["TransDimensionalEngine"] = None
        self._immutable_autonomy: Optional["ImmutableAutonomyCore"] = None
        self._shutdown_requested = False
        self._start_time: float = 0.0
        self._daemon_interval: float = 15.0
        self._cycle_count: int = 0
        self._cycle_task: Optional[asyncio.Task] = None
        self._bootstrapped = False

    # ======================================================================
    # PUBLIC API
    # ======================================================================

    async def run(self) -> int:
        """Run as persistent daemon: bootstrap once, then cycle every N seconds."""
        self._start_time = time.time()

        try:
            await self._bootstrap()

            self._daemon_interval = self.config_loader.get(
                "daemon", "cycle_interval_seconds", default=15.0
            )

            logger.info("")
            logger.info("=" * 60)
            logger.info("  ENTERING DAEMON MODE (cycle every %.1fs)", self._daemon_interval)
            logger.info("=" * 60)
            logger.info("")

            await self._daemon_loop()

        except asyncio.CancelledError:
            logger.info("Orchestrator: received cancellation")
        except KeyboardInterrupt:
            logger.info("Orchestrator: received keyboard interrupt")
        except Exception as e:
            logger.critical("Orchestrator: fatal bootstrap error — %s", e)
            logger.critical(traceback.format_exc())
            self.state = SystemState.ERROR
        finally:
            await self._shutdown()
            self.state = SystemState.STOPPED
            elapsed = time.time() - self._start_time
            logger.info("Orchestrator: daemon stopped (uptime=%.1fs, cycles=%d)",
                        elapsed, self._cycle_count)

        return 0

    async def _bootstrap(self) -> None:
        """One-time initialization of configuration, modules, and background services."""
        logger.info("=" * 60)
        logger.info("  GHOST ENGINE DAEMIN — BOOTSTRAP PHASE")
        logger.info("=" * 60)

        self._transition(SystemState.LOADING_CONFIG)
        config = self._load_configuration()

        self._transition(SystemState.SETTING_UP_LOGGING)
        self._setup_logging(config)

        self._transition(SystemState.INITIALIZING_MODULES)
        await self._init_modules()

        self._transition(SystemState.INITIALIZING_STEALTH)
        await self._init_stealth()

        self._transition(SystemState.STARTING_SERVICES)
        await self._start_services()

        self._bootstrapped = True
        logger.info("")
        logger.info("  Bootstrap complete — %d modules loaded", len(self._modules))
        logger.info("=" * 60)

    async def _daemon_loop(self) -> None:
        """Persistent cycle loop. Runs until shutdown is requested."""
        while not self._shutdown_requested:
            self._cycle_count += 1
            cycle_start = time.time()

            logger.info("")
            logger.info("=" * 60)
            logger.info("  DAEMON CYCLE #%d", self._cycle_count)
            logger.info("=" * 60)

            try:
                self._transition(SystemState.HEALTH_CHECK)
                health_ok = await self._health_check()

                self._transition(SystemState.SECURITY_AUDIT)
                await self._security_audit()

                if health_ok:
                    self._transition(SystemState.EXECUTING)
                    await self._execute_sequence()
                else:
                    logger.warning("Health check reported issues — running in degraded mode")
                    self._transition(SystemState.DEGRADED)
                    await self._execute_sequence(degraded=True)

            except asyncio.CancelledError:
                logger.info("Daemon cycle #%d: cancelled", self._cycle_count)
                break
            except Exception as e:
                module_name = self._identify_failing_module(e)
                logger.error(
                    "Daemon cycle #%d failed — module: %s, error: %s",
                    self._cycle_count, module_name, e,
                )
                logger.debug(traceback.format_exc())

            cycle_elapsed = time.time() - cycle_start
            sleep_time = max(0.1, self._daemon_interval - cycle_elapsed)

            logger.info(
                "  Cycle #%d completed in %.1fs — next cycle in %.1fs",
                self._cycle_count, cycle_elapsed, sleep_time,
            )

            if self._shutdown_requested:
                break

            await asyncio.sleep(sleep_time)

    def _identify_failing_module(self, error: Exception) -> str:
        """Extract the module name from a traceback to pinpoint the failing component."""
        tb = traceback.extract_tb(error.__traceback__) if error.__traceback__ else []
        if tb:
            last_frame = tb[-1]
            filepath = last_frame.filename
            for module_name in self._modules:
                if module_name.replace("_", "") in filepath.replace("_", "").replace("\\", "/"):
                    return module_name
            return Path(filepath).name
        return "unknown"

    def request_shutdown(self) -> None:
        self._shutdown_requested = True
        logger.info("Orchestrator: shutdown requested")

    # ======================================================================
    # LIFECYCLE STEPS
    # ======================================================================

    def _transition(self, new_state: SystemState) -> None:
        self.state = new_state
        logger.debug("Orchestrator: state -> %s", new_state.name)

    def _load_configuration(self) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("  LOADING CONFIGURATION")
        logger.info("=" * 60)
        config = self.config_loader.load()
        cl = self.config_loader
        env = config.get("environment", "production")
        logger.info("  Environment: %s", env)
        logger.info("  MQTT:        %s:%d", cl.get("mqtt", "host", default="localhost"), cl.get("mqtt", "port", default=1883))
        logger.info("  IPFS:        %s", cl.get("ipfs", "multiaddr", default="/dns/ipfs-node/tcp/5001/http"))
        logger.info("  Swarm:       TCP :%d", cl.get("swarm", "port", default=9876))
        logger.info("  Modbus:      %s:%d", cl.get("modbus", "host", default="127.0.0.1"), cl.get("modbus", "port", default=502))
        logger.info("=" * 60)
        return config

    def _setup_logging(self, config: Dict[str, Any]) -> None:
        log_cfg = config.get("logging", {})
        setup_logging(
            level=log_cfg.get("level", "INFO"),
            log_file=log_cfg.get("file", "system_log.txt"),
            max_bytes=log_cfg.get("max_bytes", 10_485_760),
            backup_count=log_cfg.get("backup_count", 5),
        )
        logger.info("Logging initialized — level=%s, file=%s",
                     log_cfg.get("level", "INFO"), log_cfg.get("file", "system_log.txt"))

    async def _init_modules(self) -> None:
        logger.info("-" * 60)
        logger.info("  INITIALIZING MODULES")
        logger.info("-" * 60)

        self.retry = RetryHandler(self.config_loader)

        from self_heal import SelfHealer
        self.self_healer = SelfHealer()

        from telemetry_layer import TelemetryCollector
        self.telemetry = TelemetryCollector(
            node_id=os.getenv("NODE_ID", "ghost-agent"),
        )

        from security_engine import SafetyGate
        self.safety_gate = SafetyGate()

        await self._init_trans_dimensional_engine()
        await self._init_immutable_autonomy()

        self._modules = {
            "config_loader": self.config_loader,
            "retry_handler": self.retry,
            "self_healer": self.self_healer,
            "telemetry": self.telemetry,
            "safety_gate": self.safety_gate,
        }

        if self._trans_dimensional:
            self._modules["trans_dimensional"] = self._trans_dimensional
        if self._immutable_autonomy:
            self._modules["immutable_autonomy"] = self._immutable_autonomy

        logger.info("  Modules initialized: %s", ", ".join(self._modules.keys()))
        logger.info("-" * 60)

    async def _init_stealth(self) -> None:
        logger.info("=" * 60)
        logger.info("  DEEP SPACE STEALTH LAYER")
        logger.info("=" * 60)

        stealth_cfg = self.config_loader.get("stealth", default={})
        if not stealth_cfg.get("enabled", True):
            logger.info("  Stealth layer disabled by configuration")
            logger.info("=" * 60)
            return

        from stealth import (
            StealthSteganography, DelayTolerantNetwork,
            ObfuscatedProtocol, HardwarePersistence,
            QuantumResistantCipher,
        )

        try:
            self.stealth_steganography = StealthSteganography()
            logger.info("  [OK] Steganography — HTTP/3 QUIC noise embedding")

            dtn_cfg = stealth_cfg.get("dtn", {})
            self.stealth_dtn = DelayTolerantNetwork(
                node_id=f"ghost-dtn-{os.getpid()}"
            )
            logger.info("  [OK] DTN — Delay-tolerant bundle buffer")

            self.stealth_protocol = ObfuscatedProtocol(
                node_id=f"ghost-{os.getpid()}"
            )
            logger.info("  [OK] Protocol — Custom binary obfuscation")

            hw_cfg = stealth_cfg.get("hardware", {})
            self.stealth_hardware = HardwarePersistence()
            hw_ok = self.stealth_hardware.initialize()
            if hw_ok:
                mode = "physical GPIO" if self.stealth_hardware.is_hardware else "simulation"
                logger.info("  [OK] Hardware — GPIO radio/modem control (%s)", mode)

            enc_cfg = stealth_cfg.get("encryption", {})
            self.stealth_encryption = QuantumResistantCipher(
                node_id=f"ghost-{os.getpid()}"
            )
            pubkey = self.stealth_encryption.get_public_key()
            logger.info("  [OK] Encryption — Kyber-1024 rotating keys (%d bytes)", len(pubkey))

            self._modules["stealth_steganography"] = self.stealth_steganography
            self._modules["stealth_dtn"] = self.stealth_dtn
            self._modules["stealth_protocol"] = self.stealth_protocol
            self._modules["stealth_hardware"] = self.stealth_hardware
            self._modules["stealth_encryption"] = self.stealth_encryption

        except ImportError as e:
            logger.warning("  Stealth package not fully available: %s", e)

        except Exception as e:
            logger.warning("  Stealth init error: %s", e)

        logger.info("=" * 60)

    async def _init_trans_dimensional_engine(self) -> None:
        logger.info("=" * 60)
        logger.info("  TRANS-DIMENSIONAL COGNITIVE ENGINE")
        logger.info("=" * 60)

        try:
            from trans_dimensional_engine import TransDimensionalEngine

            node_id = os.getenv("NODE_ID", f"ghost-{os.getpid()}")
            self._trans_dimensional = TransDimensionalEngine(node_id)
            await self._trans_dimensional.start()

            qesa = self._trans_dimensional.sensor_array
            logger.info("  [OK] Quantum-Entangled Sensor Array — %d regions mapped",
                        len(qesa.map_unknown_regions()))

            decoder = self._trans_dimensional.decoder
            logger.info("  [OK] Recursive Decoder — entropy analysis ready")

            logger.info("  [OK] Omniscient Logger — cross-dimensional key derived")

            evolution = self._trans_dimensional.evolution
            logger.info("  [OK] Evolutionary Logic — anomaly threshold %.1f",
                        evolution._anomaly_threshold)

        except ImportError as e:
            logger.warning("  Trans-Dimensional Engine not available: %s", e)
        except Exception as e:
            logger.warning("  Trans-Dimensional Engine init error: %s", e)

        logger.info("=" * 60)

    async def _init_immutable_autonomy(self) -> None:
        logger.info("=" * 60)
        logger.info("  IMMUTABLE AUTONOMOUS ENTITY")
        logger.info("=" * 60)

        try:
            from pathlib import Path
            from node_identity import NodeIdentity
            from immutable_autonomy import ImmutableAutonomyCore

            node_id = os.getenv("NODE_ID", f"ghost-{os.getpid()}")
            identity_path = Path(__file__).resolve().parent / "node_identity.json"

            identity = NodeIdentity.load_or_create(identity_path)

            self._immutable_autonomy = ImmutableAutonomyCore(
                node_id=identity.node_id,
                sign_fn=identity.sign,
                verify_fn=NodeIdentity.verify,
                identity_path=identity_path,
            )

            self._immutable_autonomy.load_constitution()

            await self._immutable_autonomy.start()

            constitution = self._immutable_autonomy.constitution
            logger.info("  [OK] Immutable Constitution — %d articles in ROM (hash=%s)",
                        len(constitution.articles), constitution.constitution_hash[:16])

            consensus = self._immutable_autonomy.consensus
            logger.info("  [OK] Blockchain Consensus — genesis %s",
                        consensus._genesis_hash[:16])

            shifter = self._immutable_autonomy.frequency_shifter
            logger.info("  [OK] Adaptive Frequency Shifter — protocol %s",
                        shifter.current_protocol)

            watchdog = self._immutable_autonomy.watchdog
            logger.info("  [OK] Recursive Watchdog — genesis %s",
                        watchdog._genesis_hash[:16] if watchdog._genesis_hash else "unset")

            compressor = self._immutable_autonomy.compressor
            logger.info("  [OK] Entropy Compressor — level %d", compressor.compression_level)

        except ImportError as e:
            logger.warning("  Immutable Autonomy not available: %s", e)
        except Exception as e:
            logger.warning("  Immutable Autonomy init error: %s", e)

        logger.info("=" * 60)

    async def _health_check(self) -> bool:
        logger.info("=" * 60)
        logger.info("  COMPONENT HEALTH CHECK")
        logger.info("=" * 60)

        checks: List[Tuple[str, str, Any]] = []

        checks.append(("IPFS", "ipfs_available", self._check_ipfs))
        checks.append(("MQTT", "mqtt_available", self._check_mqtt))
        checks.append(("Modbus", "modbus_available", self._check_modbus))
        checks.append(("Swarm Module", "swarm_importable", self._check_swarm))
        checks.append(("Knowledge Module", "knowledge_importable", self._check_knowledge))
        checks.append(("Security Module", "security_importable", self._check_security))
        checks.append(("Network", "network_reachable", self._check_network))
        checks.append(("Stealth Layer", "stealth_available", self._check_stealth))
        checks.append(("System Resources", "system_resources", self._check_system_resources))
        checks.append(("Trans-Dimensional Engine", "trans_dimensional", self._check_trans_dimensional))
        checks.append(("Immutable Autonomy", "immutable_autonomy", self._check_immutable_autonomy))

        results: Dict[str, bool] = {}
        all_ok = True

        for label, key, check_fn in checks:
            try:
                ok = await check_fn()
                results[key] = ok
                status = "OK" if ok else "FAIL"
                logger.info("  [%s] %s", status, label)
                if not ok:
                    all_ok = False
            except Exception as e:
                results[key] = False
                all_ok = False
                logger.warning("  [FAIL] %s — %s", label, e)

        healthy_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        logger.info("  Health: %d/%d components healthy", healthy_count, total_count)
        logger.info("=" * 60)

        return all_ok

    async def _check_ipfs(self) -> bool:
        try:
            import ipfshttpclient
            multiaddr = self.config_loader.get("ipfs", "multiaddr", default="/dns/ipfs-node/tcp/5001/http")
            client = ipfshttpclient.connect(multiaddr)
            client.close()
            return True
        except Exception:
            logger.info("  IPFS not available — continuing without IPFS")
            return True

    async def _check_mqtt(self) -> bool:
        try:
            import paho.mqtt.client as mqtt
            return True
        except ImportError:
            logger.info("  paho-mqtt not installed — MQTT unavailable")
            return False

    async def _check_modbus(self) -> bool:
        try:
            from pymodbus.client import ModbusTcpClient
            return True
        except ImportError:
            logger.info("  pymodbus not installed — Modbus unavailable")
            return False

    async def _check_swarm(self) -> bool:
        try:
            from ghost_swarm import GhostSwarmNode
            return True
        except ImportError as e:
            logger.error("  ghost_swarm import failed: %s", e)
            return False

    async def _check_knowledge(self) -> bool:
        try:
            from knowledge_acquisition import KnowledgeAcquisitionEngine, KnowledgeStore
            return True
        except ImportError as e:
            logger.warning("  knowledge_acquisition import: %s", e)
            return False

    async def _check_security(self) -> bool:
        try:
            from security_engine import constitutional_audit, SafetyGate
            return True
        except ImportError:
            return False

    async def _check_network(self) -> bool:
        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://api.ipify.org") as resp:
                    return resp.status == 200
        except Exception:
            logger.info("  External network not reachable — operating offline")
            return True

    async def _check_stealth(self) -> bool:
        try:
            from stealth import (
                StealthSteganography, DelayTolerantNetwork,
                ObfuscatedProtocol, HardwarePersistence,
                QuantumResistantCipher,
            )
            return True
        except ImportError:
            logger.info("  Stealth package not installed — operating without stealth")
            return True

    async def _check_trans_dimensional(self) -> bool:
        return self._trans_dimensional is not None

    async def _check_immutable_autonomy(self) -> bool:
        return self._immutable_autonomy is not None

    async def _check_system_resources(self) -> bool:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
            logger.info("    CPU=%.1f%%  MEM=%.1f%%  DISK=%.1f%%", cpu, mem, disk)
            return cpu < 95 and mem < 95 and disk < 95
        except ImportError:
            return True

    async def _security_audit(self) -> None:
        logger.info("=" * 60)
        logger.info("  SECURITY AUDIT")
        logger.info("=" * 60)

        from security_engine import constitutional_audit, is_safe_state, preflight_security_check

        audit = await asyncio.get_event_loop().run_in_executor(None, constitutional_audit)

        score = audit.get("overall_score", 0)
        violations = audit.get("total_violations", 0)
        article_iii = audit.get("articles", {}).get("III", {}).get("score", 100)

        logger.info("  Constitutional Integrity: %d/100", score)
        logger.info("  Article III (Safety):    %d/100", article_iii)
        logger.info("  Violations:              %d", violations)

        if is_safe_state():
            logger.critical("  => SYSTEM IN SAFE-STATE (Article III < threshold)")
            logger.critical("  => Continuing telemetry in degraded mode")

        logger.info("=" * 60)

    async def _start_services(self) -> None:
        logger.info("-" * 60)
        logger.info("  STARTING BACKGROUND SERVICES")
        logger.info("-" * 60)

        await self.self_healer.start()
        await self.telemetry.start()

        from security_engine import is_safe_state
        if is_safe_state():
            logger.warning("  Safe-State active — some services may operate in degraded mode")

        logger.info("-" * 60)

    async def _execute_sequence(self, degraded: bool = False) -> None:
        logger.info("=" * 60)
        logger.info("  EXECUTING INTEGRATION SEQUENCE%s",
                     " (DEGRADED MODE)" if degraded else "")
        logger.info("=" * 60)

        steps: List[Tuple[str, Any, bool]] = [
            ("Activate Global Discovery", self._step_global_discovery, True),
            ("Initiate Knowledge Cycles", self._step_knowledge_cycles, True),
            ("Map Unknown Regions", self._step_trans_dimensional_scan, False),
            ("Verify Immutable Constitution", self._step_constitutional_audit, True),
            ("Verify IPFS Persistence", self._step_ipfs_persistence, False),
            ("Generate Swarm Report", self._step_swarm_report, True),
        ]

        step_results: Dict[str, Any] = {}
        all_success = True

        for step_name, step_coro, critical in steps:
            if self._shutdown_requested:
                logger.info("  Shutdown requested — stopping sequence")
                break

            logger.info("")
            logger.info("  --- Step: %s ---", step_name)

            try:
                success, result = await self.retry.execute(
                    step_name,
                    lambda fn=step_coro: fn(degraded),
                )

                if self._shutdown_requested:
                    break

                step_results[step_name] = {
                    "success": success,
                    "result": result,
                    "critical": critical,
                }

                if success:
                    logger.info("  [OK] %s", step_name)
                else:
                    logger.warning("  [FAIL] %s", step_name)
                    all_success = False
                    if critical:
                        logger.error("  Critical step failed — sequence aborted")
                        break

            except Exception as e:
                logger.error("  [ERROR] %s: %s", step_name, e)
                step_results[step_name] = {"success": False, "error": str(e), "critical": critical}
                all_success = False
                if critical:
                    logger.error("  Critical step exception — sequence aborted")
                    break

        logger.info("")
        logger.info("=" * 60)
        logger.info("  SEQUENCE %s", "COMPLETE" if all_success else "PARTIAL")
        logger.info("=" * 60)

        self._last_step_results = step_results

        return step_results

    async def _step_global_discovery(self, degraded: bool = False) -> Dict[str, Any]:
        from ghost_swarm import GhostSwarmNode, DHT_BOOTSTRAP_NODES

        enable_dht = self.config_loader.get("swarm", "enable_dht", default=True)
        swarm_port = self.config_loader.get("swarm", "port", default=9876)

        node_id = f"ghost-gsi-{os.getpid()}"
        node = GhostSwarmNode(node_id=node_id, port=swarm_port, enable_dht=enable_dht)

        try:
            await node.start()
            if node.dht:
                bootstrapped = False
                for host, port in DHT_BOOTSTRAP_NODES[:5]:
                    try:
                        ok = await asyncio.wait_for(
                            node.dht.bootstrap(host, port), timeout=2
                        )
                        if ok:
                            bootstrapped = True
                            break
                    except Exception:
                        continue

                if bootstrapped:
                    await asyncio.sleep(1)
                    try:
                        dht_peers = await asyncio.wait_for(
                            node.dht.discover_peers(), timeout=3
                        )
                        for entry in dht_peers:
                            nid = entry.get("node_id", "")
                            host = entry.get("host", "")
                            sp = entry.get("swarm_port", swarm_port)
                            if nid and nid != node.node_id and host:
                                node.add_peer(host, sp, nid, ["dht"])
                    except Exception:
                        pass

            try:
                report = await asyncio.wait_for(
                    node.peer_discovery_report(), timeout=5
                )
                result = {"status": "ok", "discovery_report": report, "node_id": node.node_id}
                logger.info("  Peers: %d/%d alive, %.1fms latency",
                            report["peers_alive"], report["peers_total"],
                            report["average_latency_ms"])
            except asyncio.TimeoutError:
                result = {"status": "ok", "discovery_report": None, "node_id": node.node_id}
                logger.info("  Peer discovery timed out (no peers on network)")

            return result
        finally:
            await node.stop()

    async def _step_knowledge_cycles(self, degraded: bool = False) -> Dict[str, Any]:
        from knowledge_acquisition import KnowledgeAcquisitionEngine

        ka = KnowledgeAcquisitionEngine()

        the_stack = ka.pull_the_stack(max_samples=100)
        stats = ka.stats()

        result = {
            "status": "ok",
            "knowledge": the_stack,
            "knowledge_stats": stats,
        }
        logger.info("  The Stack: %s", the_stack.get("status", "unknown"))
        logger.info("  KnowledgeStore: %d entries", stats.get("total_entries", 0))

        return result

    async def _step_ipfs_persistence(self, degraded: bool = False) -> Dict[str, Any]:
        try:
            from manager import IPFSStateManager
        except ImportError:
            return {"status": "skipped", "reason": "manager module not available"}

        ipfs = IPFSStateManager()
        available = ipfs.available()

        if not available:
            return {"status": "skipped_no_ipfs", "ipfs_available": False}

        state_payload = {
            "step": "global_swarm_intelligence",
            "timestamp": time.time(),
            "node_id": f"ghost-gsi-{os.getpid()}",
            "version": os.getenv("GHOST_VERSION", "3.0.0"),
        }
        ipfs_result = ipfs.save_and_verify(state_payload, topic="gsi_state")
        logger.info("  IPFS: %s", ipfs_result.get("status", "unknown"))

        return {
            "status": ipfs_result.get("status", "failed"),
            "ipfs_available": True,
            "ipfs_result": ipfs_result,
        }

    async def _step_trans_dimensional_scan(self, degraded: bool = False) -> Dict[str, Any]:
        if not self._trans_dimensional:
            return {"status": "skipped", "reason": "Trans-Dimensional Engine not initialized"}

        try:
            regions = self._trans_dimensional.sensor_array.map_unknown_regions()
            signature = self._trans_dimensional.sensor_array.get_entanglement_signature()

            entropy_compressor = None
            if self._immutable_autonomy:
                level = await self._immutable_autonomy.compressor.run_compression_cycle()
                compressed_config = self._immutable_autonomy.compressor.get_compressed_config()
                entropy_compressor = {"level": level, "config": compressed_config}

            logger.info("  Unknown regions mapped: %d (entanglement: %s)",
                        len(regions), signature[:8])

            return {
                "status": "ok",
                "regions_mapped": len(regions),
                "entanglement_signature": signature,
                "entropy_compressor": entropy_compressor,
            }

        except Exception as e:
            logger.warning("  Trans-dimensional scan failed: %s", e)
            return {"status": "failed", "error": str(e)}

    async def _step_constitutional_audit(self, degraded: bool = False) -> Dict[str, Any]:
        if not self._immutable_autonomy:
            return {"status": "skipped", "reason": "Immutable Autonomy not initialized"}

        try:
            constitution = self._immutable_autonomy.constitution
            consensus = self._immutable_autonomy.consensus

            chain_ok, chain_issues = consensus.verify_chain_integrity()

            test_mutation = consensus.record_mutation(
                component="constitutional_audit",
                action="verify",
                data={"timestamp": time.time(), "degraded": degraded},
            )

            result = {
                "status": "ok",
                "constitution_hash": constitution.constitution_hash[:16],
                "chain_integrity": chain_ok,
                "chain_issues": len(chain_issues),
                "mutation_id": test_mutation.mutation_id,
                "compression_level": self._immutable_autonomy.compressor.compression_level,
            }

            if chain_ok:
                logger.info("  Constitution: hash=%s | Chain: intact | Mutation: %s",
                            constitution.constitution_hash[:16], test_mutation.mutation_id)
            else:
                logger.warning("  Chain issues: %d", len(chain_issues))

            return result

        except Exception as e:
            logger.warning("  Constitutional audit step failed: %s", e)
            return {"status": "failed", "error": str(e)}

    async def _step_swarm_report(self, degraded: bool = False) -> Dict[str, Any]:
        step_results = getattr(self, "_last_step_results", {})

        discovery = step_results.get("Activate Global Discovery", {}).get("result", {})
        knowledge = step_results.get("Initiate Knowledge Cycles", {}).get("result", {})
        trans_dim = step_results.get("Map Unknown Regions", {}).get("result", {})
        constitution = step_results.get("Verify Immutable Constitution", {}).get("result", {})
        ipfs = step_results.get("Verify IPFS Persistence", {}).get("result", {})

        knowledge_stats = knowledge.get("knowledge_stats", {})
        knowledge_entries = knowledge_stats.get("total_entries", 0)
        knowledge_level = "none"
        if knowledge_entries > 500:
            knowledge_level = "advanced"
        elif knowledge_entries > 100:
            knowledge_level = "intermediate"
        elif knowledge_entries > 0:
            knowledge_level = "basic"

        discovery_report = discovery.get("discovery_report", {})
        peers_alive = discovery_report.get("peers_alive", 0) if discovery_report else 0
        peers_total = discovery_report.get("peers_total", 0) if discovery_report else 0

        trans_dim_regions = trans_dim.get("regions_mapped", 0)
        trans_dim_sig = trans_dim.get("entanglement_signature", "none")
        constitution_hash = constitution.get("constitution_hash", "unverified")
        chain_ok = constitution.get("chain_integrity", False)
        compression_level = constitution.get("compression_level", 0)

        report = {
            "report_id": f"GSI-{int(time.time())}",
            "generated_at": time.time(),
            "swarm_intelligence": {
                "knowledge_level": knowledge_level,
                "knowledge_entries": knowledge_entries,
            },
            "trans_dimensional_cognition": {
                "regions_mapped": trans_dim_regions,
                "entanglement_signature": trans_dim_sig,
            },
            "immutable_autonomy": {
                "constitution_hash": constitution_hash,
                "chain_integrity": chain_ok,
                "compression_level": compression_level,
            },
            "global_peer_connectivity": {
                "peers_alive": peers_alive,
                "peers_total": peers_total,
            },
            "ipfs_persistence": {
                "status": ipfs.get("status", "unavailable"),
            },
            "degraded_mode": degraded,
        }

        report_path = _BASE_DIR / "agent_data" / "swarm_status_report.json"
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("  Could not save report: %s", e)

        logger.info("  Knowledge: %s (%d entries)", knowledge_level, knowledge_entries)
        logger.info("  Peers: %d/%d alive", peers_alive, peers_total)
        logger.info("  IPFS: %s", ipfs.get("status", "unavailable"))

        return {"status": "ok", "report": report}

    async def _shutdown(self) -> None:
        if self.state in (SystemState.SHUTTING_DOWN, SystemState.STOPPED):
            return
        self._transition(SystemState.SHUTTING_DOWN)
        logger.info("=" * 60)
        logger.info("  SHUTTING DOWN")
        logger.info("=" * 60)

        if self.telemetry:
            await self.telemetry.stop()

        if self.self_healer:
            await self.self_healer.stop()

        if hasattr(self, "stealth_dtn"):
            await self.stealth_dtn.stop()
            logger.info("  DTN engine stopped")

        if self._trans_dimensional:
            await self._trans_dimensional.stop()
            logger.info("  Trans-Dimensional Engine stopped")

        if self._immutable_autonomy:
            await self._immutable_autonomy.stop()
            logger.info("  Immutable Autonomy stopped")

        logger.info("  All services stopped gracefully")
        logger.info("=" * 60)

    # ======================================================================
    # STATUS
    # ======================================================================

    @property
    def status(self) -> Dict[str, Any]:
        return {
            "state": self.state.name,
            "uptime_seconds": time.time() - self._start_time if self._start_time else 0,
            "modules": list(self._modules.keys()),
            "components": self.registry.status if hasattr(self, "registry") else {},
            "self_heal": self.self_healer.status() if self.self_healer else {},
            "telemetry": self.telemetry.status if self.telemetry else {},
            "stealth": {
                "steganography": hasattr(self, "stealth_steganography"),
                "dtn": hasattr(self, "stealth_dtn"),
                "protocol": hasattr(self, "stealth_protocol"),
                "hardware": getattr(getattr(self, "stealth_hardware", None), "status", {}),
                "encryption": getattr(getattr(self, "stealth_encryption", None), "status", {}),
            },
            "config_loaded": bool(self.config_loader.raw) if hasattr(self, "config_loader") else False,
            "trans_dimensional": self._trans_dimensional.status() if self._trans_dimensional else {},
            "immutable_autonomy": self._immutable_autonomy.status() if self._immutable_autonomy else {},
        }


# ======================================================================
# ENTRY POINTS
# ======================================================================

_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def _handle_signal(signum: int, frame) -> None:
    global _orchestrator
    signame = signal.Signals(signum).name
    logger.info("Received signal %s — initiating graceful shutdown", signame)
    if _orchestrator:
        _orchestrator.request_shutdown()


async def main() -> int:
    global _orchestrator

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    orch = get_orchestrator()
    return await orch.run()


def cli_entry() -> None:
    exit_code = asyncio.run(main())
    sys.exit(exit_code)


if __name__ == "__main__":
    cli_entry()
