from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from ecosystem_agent import EcosystemAgent
from ecosystem_kernel import EcosystemKernel
from ecosystem_shared_memory import EcosystemMemory
from ecosystem_language import EILMessage

from research_engine.orchestrator import ResearchOrchestrator
from research_engine.models import ResearchReport, AnalysisResult

load_dotenv()
logger = logging.getLogger("ecosystem.agent.research_engine")


class ResearchEngineAgent(EcosystemAgent):
    """Research engine agent — conducts research, analyzes findings, generates reports."""

    agent_type = "research_engine"

    def __init__(self, kernel: EcosystemKernel,
                 memory: Optional[EcosystemMemory] = None,
                 agent_id: Optional[str] = None):
        super().__init__(kernel, memory, agent_id)
        self._orchestrator = ResearchOrchestrator(output_dir="reports")

    def _declare_capabilities(self) -> Dict[str, Any]:
        return {
            "tasks": [
                "research_topic", "batch_research", "deep_dive",
                "generate_report", "list_reports", "get_report",
                "export_knowledge_graph", "compare_topics",
            ],
            "description": "Research engine — collects, analyzes, and generates reports on topics",
            "version": "1.0.0",
        }

    async def execute_task(self, task: str,
                           params: Dict[str, Any]) -> Dict[str, Any]:
        task_lower = task.lower()

        if "research_topic" in task_lower or "research" in task_lower:
            return await self._research_topic(params)
        if "batch" in task_lower:
            return await self._batch_research(params)
        if "deep_dive" in task_lower or "deep" in task_lower:
            return await self._deep_dive(params)
        if "generate_report" in task_lower or "report" in task_lower:
            return await self._generate_report(params)
        if "list_reports" in task_lower or "list" in task_lower:
            return self._list_reports()
        if "get_report" in task_lower:
            return self._get_report(params)
        if "knowledge_graph" in task_lower or "graph" in task_lower:
            return self._export_graph(params)
        if "compare" in task_lower:
            return self._compare(params)

        return {"status": "unknown_task", "task": task,
                "hint": "Supported: research_topic, batch_research, deep_dive, generate_report, list_reports, get_report, export_knowledge_graph, compare_topics"}

    async def _research_topic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        topic = params.get("topic") or params.get("query", "")
        if not topic:
            return {"status": "failed", "error": "Provide 'topic' parameter"}

        result = await self._orchestrator.research_topic(
            topic_name=topic,
            description=params.get("description", ""),
            keywords=params.get("keywords"),
            max_sources=params.get("max_sources", 15),
            generate_report=True,
        )

        self.learn(f"research:{topic}", {
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, confidence=0.8, tags=["research", topic.lower().replace(" ", "-")])

        await self.broadcast(
            f"research_complete:{topic}",
            {"topic": topic, "findings": result.get("findings_count", 0),
             "report_id": result.get("report_id")},
        )
        return {"status": "done", **result}

    async def _batch_research(self, params: Dict[str, Any]) -> Dict[str, Any]:
        topics = params.get("topics", [])
        if not topics:
            return {"status": "failed", "error": "Provide 'topics' list"}
        result = await self._orchestrator.batch_research(
            topics, max_concurrent=params.get("max_concurrent", 3)
        )
        return {"status": "done", **result}

    async def _deep_dive(self, params: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url", "")
        if not url:
            return {"status": "failed", "error": "Provide 'url' parameter"}
        result = await self._orchestrator.deep_dive(
            url, topic_name=params.get("topic_name")
        )
        return {"status": "done", **result}

    async def _generate_report(self, params: Dict[str, Any]) -> Dict[str, Any]:
        analysis_id = params.get("analysis_id")
        if not analysis_id:
            return {"status": "failed",
                    "error": "Provide 'analysis_id' from a previous research_topic result"}

        analysis = self._orchestrator.get_analysis(analysis_id)
        if not analysis:
            return {"status": "failed", "error": f"Analysis '{analysis_id}' not found"}

        from research_engine.generator import ReportGenerator
        gen = ReportGenerator(output_dir="reports")
        report = gen.generate_report(
            analysis,
            title=params.get("title"),
            include_latex=params.get("include_latex", False),
        )
        return {
            "status": "done",
            "report_id": report.id,
            "title": report.title,
            "quality_score": report.quality_score,
            "word_count": report.word_count(),
        }

    def _list_reports(self) -> Dict[str, Any]:
        reports = self._orchestrator.list_reports()
        return {"status": "done", "reports": reports, "count": len(reports)}

    def _get_report(self, params: Dict[str, Any]) -> Dict[str, Any]:
        report_id = params.get("report_id", "")
        report = self._orchestrator.get_report(report_id)
        if not report:
            return {"status": "failed", "error": f"Report '{report_id}' not found"}

        fmt = params.get("format", "summary")
        if fmt == "markdown":
            return {"status": "done", "content": report.to_markdown(), "format": "markdown"}
        if fmt == "latex":
            return {"status": "done", "content": report.to_latex(), "format": "latex"}
        if fmt == "json":
            return {"status": "done", "content": report.model_dump(), "format": "json"}
        return {
            "status": "done",
            "id": report.id,
            "title": report.title,
            "topic": report.topic,
            "abstract": report.abstract,
            "sections": len(report.sections),
            "findings": len(report.findings),
            "sources": len(report.sources),
            "citations": len(report.citations),
            "quality_score": report.quality_score,
            "word_count": report.word_count(),
        }

    def _export_graph(self, params: Dict[str, Any]) -> Dict[str, Any]:
        analysis_id = params.get("analysis_id", "")
        graph = self._orchestrator.export_knowledge_graph(analysis_id)
        if "error" in graph:
            return {"status": "failed", "error": graph["error"]}
        return {"status": "done", "graph": graph}

    def _compare(self, params: Dict[str, Any]) -> Dict[str, Any]:
        analysis_ids = params.get("analysis_ids", [])
        if len(analysis_ids) < 2:
            return {"status": "failed",
                    "error": "Provide at least 2 'analysis_ids'"}
        analyses = []
        for aid in analysis_ids:
            a = self._orchestrator.get_analysis(aid)
            if a:
                analyses.append(a)
        if len(analyses) < 2:
            return {"status": "failed",
                    "error": "Could not find enough analyses"}

        from research_engine.analyzer import ResearchAnalyzer
        analyzer = ResearchAnalyzer()
        comparison = analyzer.compare_topics(analyses)
        return {"status": "done", "comparison": comparison,
                "topics": [a.topic for a in analyses]}

    async def handle_message(self, msg: EILMessage) -> None:
        if msg.type == "task" and any(
            w in msg.task.lower()
            for w in ["research", "report", "deep_dive", "batch"]
        ):
            task_ref = msg.ref or msg.id
            self._active_task = task_ref
            try:
                result = await self.execute_task(msg.task, msg.result)
                self._task_count += 1
                reply = EILMessage.response(
                    self.agent_id, msg.src, task_ref,
                    result, status="done", task=msg.task,
                )
                await self.send(reply)
            except Exception as e:
                self._error_count += 1
                reply = EILMessage.error(
                    self.agent_id, msg.src, msg.task, str(e), task_ref
                )
                await self.send(reply)
            finally:
                self._active_task = None
        else:
            await super().handle_message(msg)

    async def start(self):
        await super().start()
        logger.info("ResearchEngineAgent %s ready", self.agent_id)

    async def stop(self):
        await self._orchestrator.close()
        await super().stop()
        logger.info("ResearchEngineAgent %s stopped", self.agent_id)
