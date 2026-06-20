import asyncio
import logging
import os
import signal
from typing import Optional

from dashboard_instrumentation import MetricsStore
from email_agent import EmailResponder
from execution_core import ExecutionCoordinator

logger = logging.getLogger("AgentRunner")


class AgentRuntime:
    def __init__(self):
        self.metrics = MetricsStore()
        self.email_responder = EmailResponder(metrics=self.metrics)
        self.coordinator = ExecutionCoordinator(metrics=self.metrics, email_responder=self.email_responder)
        self.shutdown_event = asyncio.Event()

    async def start(self) -> None:
        await self.coordinator.start()
        await self.email_responder.start()
        await self._publish_startup_event()
        self._install_signal_handlers()
        await self.shutdown_event.wait()
        await self.stop()

    async def stop(self) -> None:
        self.email_responder.stop()
        await self.coordinator.stop()
        self.metrics.record_system_event("agent_shutdown", {})
        logger.info("Agent runtime stopped")

    async def _publish_startup_event(self) -> None:
        self.metrics.record_system_event("agent_startup", {"public_webhook": bool(os.getenv("PUBLIC_WEBHOOK_URL"))})

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for signame in ("SIGINT", "SIGTERM"):
            if hasattr(signal, signame):
                loop.add_signal_handler(getattr(signal, signame), lambda: self.shutdown_event.set())


async def main(runtime: Optional[AgentRuntime] = None) -> None:
    if runtime is None:
        runtime = AgentRuntime()
    await runtime.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    asyncio.run(main())
