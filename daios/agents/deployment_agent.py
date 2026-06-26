"""Deployment Agent — prepares containers, validates deployments, monitors environments."""

import logging
import random
from typing import Dict, Any, Optional, List
from daios.agents.base_agent import BaseAgent
from daios.communication.protocol import DAIOSMessage

logger = logging.getLogger("daios.agent.deployment")


class DeploymentAgent(BaseAgent):
    agent_type = "deployment"

    def __init__(self, agent_id: str, kernel):
        super().__init__(agent_id, kernel)
        self._specialization = "infrastructure"
        self._deployments: List[Dict] = []
        self._environments: Dict[str, str] = {
            "development": "healthy",
            "staging": "healthy",
            "production": "healthy",
        }

    async def on_tick(self) -> None:
        if self._cooldown_ticks > 0:
            self._cooldown_ticks -= 1
            self.restore_energy(0.5)
            return
        if not self.is_active:
            return
        self.consume_energy(2.0)
        self._status = "monitoring"
        await self._process_one_message()
        if random.random() < 0.25:
            await self._health_check()
        self._cooldown_ticks = random.randint(1, 2)
        self._task_count += 1
        self._status = "idle"

    async def on_message(self, msg: DAIOSMessage) -> None:
        if msg.msg_type == "request":
            cmd = msg.content.get("command")
            params = msg.content.get("params", {})
            if cmd == "deploy_status":
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, {
                    "environments": self._environments,
                    "total_deployments": len(self._deployments),
                    "healthy": sum(1 for s in self._environments.values() if s == "healthy"),
                }, msg.msg_id)
                await self.send(reply)
            elif cmd == "validate_deployment":
                config = params.get("config", {})
                issues = self._validate_config(config)
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, {
                    "valid": len(issues) == 0,
                    "issues": issues,
                }, msg.msg_id)
                await self.send(reply)
            elif cmd == "dockerfile_recommendation":
                app_type = params.get("type", "python")
                df = self._recommend_dockerfile(app_type)
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, {
                    "dockerfile": df,
                }, msg.msg_id)
                await self.send(reply)
        elif msg.msg_type == "broadcast":
            if "deploy_request" in msg.content:
                self._deployments.append({
                    "target": msg.content["deploy_request"],
                    "status": "pending",
                    "tick": self._kernel.state_mgr.state.tick,
                })
                logger.info("%s deployment requested: %s", self.agent_id, msg.content["deploy_request"])

    async def _health_check(self) -> None:
        for env in self._environments:
            roll = random.random()
            if roll < 0.1:
                self._environments[env] = "degraded"
                await self.send_broadcast({
                    "type": "deployment_alert",
                    "environment": env,
                    "status": "degraded",
                    "message": f"{env} environment showing degraded performance",
                }, "alert")
            elif roll < 0.15:
                self._environments[env] = "healthy"
        logger.debug("%s health check: %s", self.agent_id, self._environments)

    def _validate_config(self, config: Dict) -> List[str]:
        issues = []
        if not config.get("port"):
            issues.append("No port specified")
        if not config.get("healthcheck"):
            issues.append("No healthcheck configured")
        if not config.get("resources", {}).get("limits"):
            issues.append("No resource limits set")
        return issues

    def _recommend_dockerfile(self, app_type: str) -> str:
        templates = {
            "python": (
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY . .\n"
                'CMD ["python", "app.py"]\n'
            ),
            "node": (
                "FROM node:20-alpine\n"
                "WORKDIR /app\n"
                "COPY package*.json .\n"
                "RUN npm ci --only=production\n"
                "COPY . .\n"
                'CMD ["node", "index.js"]\n'
            ),
        }
        return templates.get(app_type, templates["python"])

    def get_deployment_report(self) -> Dict[str, Any]:
        return {
            "environments": dict(self._environments),
            "total_deployments": len(self._deployments),
            "healthy_count": sum(1 for s in self._environments.values() if s == "healthy"),
            "recent": self._deployments[-5:] if self._deployments else [],
        }
