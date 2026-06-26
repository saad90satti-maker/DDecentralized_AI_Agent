"""GitHub Agent — manages repository structure, documentation, and project tracking."""

import logging
import random
from typing import Dict, Any, Optional, List
from daios.agents.base_agent import BaseAgent
from daios.communication.protocol import DAIOSMessage

logger = logging.getLogger("daios.agent.github")


class GitHubAgent(BaseAgent):
    agent_type = "github"

    def __init__(self, agent_id: str, kernel):
        super().__init__(agent_id, kernel)
        self._specialization = "repository_management"
        self._repos_managed: List[str] = []
        self._docs_generated: int = 0
        self._commits_recommended: int = 0

    async def on_tick(self) -> None:
        if self._cooldown_ticks > 0:
            self._cooldown_ticks -= 1
            self.restore_energy(0.5)
            return
        if not self.is_active:
            return
        self.consume_energy(1.5)
        self._status = "organizing"
        await self._process_one_message()
        if random.random() < 0.3:
            await self._generate_doc_recommendation()
        self._cooldown_ticks = random.randint(1, 3)
        self._task_count += 1
        self._status = "idle"

    async def on_message(self, msg: DAIOSMessage) -> None:
        if msg.msg_type == "request":
            cmd = msg.content.get("command")
            params = msg.content.get("params", {})
            if cmd == "repo_status":
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, {
                    "managed_repos": len(self._repos_managed),
                    "docs_generated": self._docs_generated,
                    "commits": self._commits_recommended,
                }, msg.msg_id)
                await self.send(reply)
            elif cmd == "suggest_structure":
                project_type = params.get("type", "python")
                structure = self._suggest_repo_structure(project_type)
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, {
                    "structure": structure,
                    "recommendation": f"Standard {project_type} project layout",
                }, msg.msg_id)
                await self.send(reply)
        elif msg.msg_type == "broadcast":
            if "new_project" in msg.content:
                self._repos_managed.append(msg.content["new_project"])

    async def _generate_doc_recommendation(self) -> None:
        doc_types = [
            "API reference documentation",
            "Architecture overview update",
            "README enhancement with usage examples",
            "Contributing guide",
            "Deployment instructions update",
        ]
        doc = random.choice(doc_types)
        await self.send_observe({
            "type": "doc_recommendation",
            "recommendation": doc,
            "priority": random.choice(["low", "medium", "high"]),
        })
        self._docs_generated += 1
        logger.info("%s doc recommendation: %s", self.agent_id, doc)

    def _suggest_repo_structure(self, project_type: str) -> Dict[str, Any]:
        structures = {
            "python": {
                "root": ["README.md", "setup.py", "requirements.txt", ".gitignore"],
                "src": ["__init__.py", "core.py", "utils.py"],
                "tests": ["__init__.py", "test_core.py"],
                "docs": ["index.md", "api.md"],
            },
            "node": {
                "root": ["README.md", "package.json", ".gitignore"],
                "src": ["index.js", "routes/"],
                "tests": ["test.js"],
                "docs": ["README.md"],
            },
            "docker": {
                "root": ["README.md", "Dockerfile", "docker-compose.yml", ".dockerignore"],
                "src": ["app.py"],
                "config": ["nginx.conf", "env.example"],
            },
        }
        return structures.get(project_type, structures["python"])

    def get_github_report(self) -> Dict[str, Any]:
        return {
            "repos_managed": len(self._repos_managed),
            "docs_generated": self._docs_generated,
            "commits_recommended": self._commits_recommended,
        }
