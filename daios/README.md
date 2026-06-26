# DAIOS — Decentralized AI Operating System (Simulation Environment)

A lightweight, modular, distributed AI civilization simulation where specialized agents cooperate, learn, explore, innovate, and improve the ecosystem — all under human control, secure by default.

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DAIOS KERNEL NODE                               │
│  ┌────────────────┐  ┌──────────────────┐  ┌────────────────────────┐  │
│  │  State Manager │  │ Resource Tracker │  │   Message Bus          │  │
│  │  - tick counter│  │ - CPU/Memory     │  │   - Message Queuing    │  │
│  │  - agent states│  │ - Msg throughput │  │   - Request/Response   │  │
│  │  - resources   │  │ - Latency        │  │   - Broadcast          │  │
│  └────────────────┘  └──────────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
         │                        │                           │
    ┌────┴────┐      ┌────────────┴────────────┐     ┌────────┴────────┐
    │         │      │                         │     │                 │
┌───▼───┐ ┌──▼──┐ ┌─▼─────────┐ ┌─────────┐ ┌─▼──┐ ┌──▼───┐ ┌───────┐
│Research│ │Plan │ │ Builder   │ │ Auditor │ │Mem │ │Comm  │ │Human  │
│ Agent  │ │ner  │ │ Agent     │ │ Agent   │ │ory │ │Agent  │ │CLI/API│
└───┬───┘ └─────┘ └─────┬─────┘ └────┬────┘ └──┬──┘ └──────┘ └───────┘
    │                    │            │         │
    └────────────────────┴────────────┴─────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
┌───────▼───────┐     ┌─────────▼─────────┐
│ Shared Memory │     │  Simulation World │
│ - Knowledge   │     │  - Economy        │
│ - Observations│     │  - Resources      │
│ - Learning    │     │  - Communities    │
│                │     │  - Research Goals │
└───────────────┘     └───────────────────┘
```

---

## 2. Agent Hierarchy

```
KERNEL NODE (Coordinator)
├── Research Agent    — Explores topics, generates discoveries, proposes hypotheses
├── Planner Agent     — Decomposes goals into task plans, assigns priorities
├── Builder Agent     — Executes tasks, builds artifacts, self-improves
├── Auditor Agent     — Validates actions, enforces rules, checks quality
├── Memory Agent      — Manages knowledge store, curates observations, synthesizes patterns
└── Communication Agent — Routes messages, manages external interfaces

Growth Model (controlled by AgentFactory):
  → New agents created only with human approval
  → Idle agents automatically retired after N ticks
  → Specializations tracked for resource optimization
```

**Agent Lifecycle:** Created → Active (cooldown cycles) → Idle threshold → Retired

---

## 3. Internal Communication Protocol

**Format:** Compact JSON with short field names

```
Full Format:         Compact Format:
{                    {
  "msg_type": "req",    "t":"req",
  "from_id": "r01",     "f":"r01",
  "to_id": "mem01",     "to":"mem01",
  "content": {...},      "c":{...},
  "msg_id": "r01-...",   "id":"r01-...",
  "tick": 42,            "tk":42
}                    }
```

**Message Types:**

| Type | Purpose | Example |
|------|---------|---------|
| `request` | Agent requests action/info | `{command: "execute_task", params: {...}}` |
| `response` | Reply to request | `{data: {result: "ok"}}` |
| `broadcast` | Message to all agents | `{new_goal: "build_reactor"}` |
| `observe` | Report observation to memory | `{type: "discovery", topic: "physics"}` |
| `learn` | Share learned pattern | `{type: "optimization", detail: "..."}` |
| `propose` | Propose hypothesis | `{title: "...", confidence: 0.8}` |
| `alert` | Urgent notification | `{audit_finding: {...}}` |

---

## 4. Memory Design

```
SharedMemory
├── Knowledge Store       (Dict[str, KnowledgeEntry])
│   - key-value storage with confidence scores
│   - Tag-based search
│   - Source tracking
│
├── Observation Store     (List[ObservationEntry])
│   - All agent observations (ring buffer, max 1000)
│   - Filterable by agent_id
│   - Timestamped
│
└── Learning Store        (List[LearningEntry])
    - Learned patterns with confidence
    - Verification counter
    - Garbage-collected when full (max 500)
```

**Persistence:** JSON checkpoint files saved to `data/checkpoints/state_t{N}.json`

---

## 5. Exploration System

```
Approved Data Sources (8 internal sources)
        │
        ▼
Discovery Generation (agents research topics)
        │
        ▼
HypothesisEngine
  ├── Generates hypotheses from discoveries
  ├── Accumulates evidence from multiple agents
  ├── Verifies at confidence > 0.7 with 3+ evidence
  └── Ranks by usefulness score
        │
        ▼
Shared Knowledge (high-confidence patterns stored)
```

---

## 6. Simulation World

| Component | Description | Metrics |
|-----------|-------------|---------|
| **Economy** | Virtual GDP, inflation, innovation index | GDP: 5k-50k, Innovation: 10-100 |
| **Resources** | Energy, data, compute, knowledge | Replenish at discovery rate |
| **Communities** | 3 communities with unique goals | Size: 500-1000, Tech: 2-4 |
| **Research Goals** | 3 active goals, auto-complete at 100% | Progress: 0-1.0 |
| **Tasks** | Community-driven, agent-executed | Reward: 100-500 |

---

## 7. Docker Deployment Plan

```yaml
# docker-compose.yml
services:
  kernel:
    build: .
    ports: [8470, 8471]
    resources:
      limits: cpus=0.5, memory=256M
```

**Deployment Options:**
- **Local:** `docker compose up` — single container, all services
- **Cloud:** Add worker replicas, load balancer
- **Kubernetes:** Horizontal scaling via `Deployment` + `Service`

---

## 8. GitHub Structure

```
daios/
├── .github/workflows/ci.yml
├── daios/
│   ├── __init__.py
│   ├── main.py                    # Entry point
│   ├── kernel/                    # Kernel node, state, config
│   ├── agents/                    # 6 specialized agents
│   ├── memory/                    # Shared memory layer
│   ├── communication/             # Protocol + message bus
│   ├── simulation/                # World, economy, resources
│   ├── exploration/               # Hypothesis engine
│   ├── growth/                    # Agent factory
│   ├── cloud/                     # Docker + GitHub configs
│   ├── monitoring/                # Performance tracking
│   └── api/                       # REST + CLI
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── setup.py
└── README.md
```

---

## 9. Cloud Scaling Strategy

| Layer | Scaling Approach | Resource Budget |
|-------|-----------------|-----------------|
| **Kernel** | Single instance (stateful) | 0.5 CPU, 256MB RAM |
| **Workers** | Horizontal replicas (stateless) | 0.25 CPU, 128MB RAM each |
| **Memory** | JSON snapshots → optional Redis | Disk: ~10MB per 1000 ticks |
| **API** | FastAPI behind reverse proxy | Nginx/Caddy, rate-limited |
| **Cloudflare** | Optional tunnel for API | Zero-cost via free plan |

**Scaling Rules:**
- Kernel must be single (coordinates state)
- Workers can scale horizontally for task execution
- Memory partitionable by agent type
- API stateless, can scale via load balancer

---

## 10. Resource Optimization

| Technique | Metric | Target |
|-----------|--------|--------|
| Compact message format | Bytes per message | <200 bytes avg |
| Agent cooldown cycles | CPU per agent/tick | <5ms |
| Ring buffer memory store | Memory growth | Bounded (max entries) |
| JSON checkpoint compression | Storage per checkpoint | <100KB |
| Idle agent retirement | Active agents | ≤20 max |
| Message dedup via bus | Duplicate rate | <1% |

---

## 11. Performance Goals

| Metric | Target | Measured |
|--------|--------|----------|
| Memory footprint | <100MB | ~30MB (6 agents) |
| CPU usage | <10% | ~2-5% |
| Tick duration | <100ms | ~1-10ms |
| Message latency | <10ms | <1ms (in-process) |
| Agent startup time | <100ms | Instant |
| Max agents per kernel | 20 | 6 default |
| Checkpoint size | <100KB | ~5KB |

---

## 12. Future Evolution Roadmap

### Phase 1 — Foundation (Current) ✓
- [x] Kernel node with tick-based simulation
- [x] 6 specialized agent types
- [x] Shared memory layer
- [x] Compact communication protocol
- [x] Simulation world with economy/resources
- [x] Hypothesis engine for exploration
- [x] Agent factory with human approval
- [x] REST API + CLI interface
- [x] Docker deployment

### Phase 2 — Resilience (Next)
- [ ] Agent crash recovery and restart
- [ ] Checkpoint auto-save every N ticks
- [ ] Message replay for recovery
- [ ] Agent energy auto-rebalance
- [ ] World state rollback on error

### Phase 3 — Intelligence (Medium-term)
- [ ] LLM-powered agent decision making
- [ ] Natural language goal setting
- [ ] Cross-agent knowledge synthesis
- [ ] Emergent behavior detection
- [ ] Adaptive agent specialization

### Phase 4 — Scale (Long-term)
- [ ] Multi-kernel federation
- [ ] P2P agent migration between kernels
- [ ] Redis-backed memory persistence
- [ ] Web dashboard with real-time viz
- [ ] Cloudflare Workers integration

### Phase 5 — Autonomy (Vision)
- [ ] Self-modifying agent logic
- [ ] Autonomous resource discovery
- [ ] Cross-simulation knowledge transfer
- [ ] Organic agent speciation
- [ ] Decentralized governance via consensus

---

## Quick Start

```bash
# Install
pip install -r daios/requirements.txt

# Run simulation (headless)
python -m daios.main --mode sim --tick 1.0

# Run with CLI control
python -m daios.main --mode cli

# Run with REST API dashboard
python -m daios.main --mode api --port 8471

# Docker deployment
cd daios && docker compose up

# View API
curl http://localhost:8471/api/status
```

## CLI Commands (in `cli` mode)

| Command | Description |
|---------|-------------|
| `status` | System status |
| `agents` | List all agents |
| `world` | Simulation world state |
| `memory` | Memory statistics |
| `hypotheses` | Hypothesis rankings |
| `tasks` | Available world tasks |
| `propose <type> <reason>` | Propose new agent |
| `approve <proposal_id>` | Approve agent creation |
| `pending` | Pending approvals |
| `checkpoint` | Save state checkpoint |
| `exit` | Shutdown |
