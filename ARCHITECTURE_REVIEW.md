# Decentralized AI Agent — Architecture Review

## 1. System Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│                    Ghost Engine (Python)                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ FastAPI  │  │  Model   │  │   HF     │  │  Swarm   │  │
│  │ Dashboard│  │  Router  │  │Inference │  │   Node   │  │
│  │ :8000    │  │(Cascade) │  │ (local)  │  │ :9876    │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │              │             │              │        │
│  ┌────▼──────────────▼─────────────▼──────────────▼─────┐  │
│  │              ServiceConnector + TaskManager           │  │
│  │           ExecutionEngine + RecoveryModule             │  │
│  └───────────────────────────────────────────────────────┘  │
├────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Groq    │  │  Gemini  │  │ Ollama   │  │  IPFS    │  │
│  │  API     │  │  API     │  │ (local)  │  │  Node    │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└────────────────────────────────────────────────────────────┘

                    ▼ (multi-container deployment)
┌────────────────────────────────────────────────────────────┐
│                    Akash Network (SDL)                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Ghost    │  │  IPFS    │  │  Redis   │  │  Ollama  │  │
│  │ Engine   │  │  Node    │  │  Cache   │  │  (opt)   │  │
│  │ x3 reps  │  │          │  │          │  │          │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | File | Role |
|---|---|---|
| **FastAPI Dashboard** | `manager.py:1034` | REST API + static file server + Web UI |
| **Model Router** | `model_router.py:34` | 4-tier LLM cascade: Groq → Gemini → HF → Ollama |
| **HF Inference** | `hf_inference.py:54` | Local transformer inference with disk cache |
| **Swarm Node** | `ghost_swarm.py:463` | P2P TCP/UDP node with Kademlia DHT discovery |
| **Task Manager** | `manager.py:486` | Persistent JSON task queue with background worker |
| **Execution Engine** | `manager.py:283` | Shell command runner (sync/parallel) |
| **Service Connector** | `manager.py:183` | External API health checks (GitHub, Discord, Cloudflare) |
| **Recovery Module** | `manager.py:118` | Auto-fix detection + failure logging |
| **Global Ignition** | `global_ignition.py` | Scheduled self-healing cycle → Akash redeploy |
| **Autonomous Swarm** | `autonomous_swarm.py` | P2P task orchestration + peer discovery |

### Data Flow: Request → Response

```
User/Peer ──► FastAPI ──► ModelRouter.route()
                            │
                    ┌───────┴────────┐
                    ▼                ▼
              Groq API ◄── Quota? ── Gemini API
                    │                │
                    ▼                ▼
              HF Inference (local)   │
                    │                │
                    ▼                ▼
              Ollama (local)     Return
```

---

## 2. Local Python Agent <-> Akash Network Integration

### Current Integration Points

| Layer | Mechanism | Latency |
|---|---|---|
| **Deployment** | `deploy.yaml` — Akash SDL v2.2, 3 replicas | N/A |
| **Self-Healing** | `global_ignition.py` detects failures → triggers redeploy | ~5-30s |
| **State** | IPFS sidecar for decentralized config state | ~100-500ms |
| **Config** | Config CID resolution via IPFS during bootstrap | ~1-5s |
| **P2P** | libp2p-style TCP + UDP broadcast + Kademlia DHT | ~10-50ms LAN, ~100-500ms WAN |
| **Task Dispatch** | Swarm sends `task` messages to peers | ~5-20ms LAN, ~50-200ms WAN |

### What Works Well

1. **Failover cascade** in ModelRouter — if Groq 429s, it drops to Gemini, then local HF, then Ollama. The `_is_quota_or_timeout` heuristic correctly catches rate limits.
2. **Self-healing bootstrap** (`ghost_swarm.py:665`) — IPFS config CID → DHT discovery → rendezvous → quantum handshake → redeploy trigger.
3. **Port fallback** in `autonomous_swarm.py:356` — TCP port collision handling with random fallback is robust.

### Gap: No Graceful Degradation on Akash

When deployed on Akash, all 3 replicas run identical code. If one replica's local HF model consumes 8GB VRAM, it can OOM the entire pod since Akash SDL specifies 4Gi RAM per replica. The system needs:
- **Resource-aware routing** — skip `hf` tier if `/proc/meminfo` shows < 6GB free
- **Replica cooldown** — if a replica OOMs, Akash restarts it, but the ignition loop should back off exponentially

---

## 3. Containerized Deployment Bottlenecks

### 3a. Model Loading Memory (Critical)

```
Bottleneck: HFInferenceEngine.load_model() loads full transformer
            into RAM/VRAM. With Phi-3-mini (2.7B params @ FP16 ≈ 5.4GB),
            this exceeds Akash SDL limit of 4Gi RAM.

Impact:     OOM kill → container restart → infinite crash loop
```

**Fix:** Add memory-aware loading:
- Check `psutil.virtual_memory().available` before `load_model()`
- If < 6GB available, load in 8-bit (`load_in_8bit=True`)
- If < 3GB, skip HF tier entirely and return error to cascade

### 3b. All Replicas Poll External APIs Simultaneously (High)

```
Bottleneck: 3 Akash replicas all call check_services() every 4s.
            check_github(), check_discord(), check_cloudflare()
            each do HTTP requests to external APIs.

Impact:     3 × 3 external API calls every 4s = 2,700 calls/min
            Rate limits hit fast. Discord blocks at 50 calls/min.
```

**Fix:** Add distributed rate limiting via Redis (already in docker-compose):
- Each external check acquires a Redis lock before calling
- Or: only replica-0 (elected via DHT leadership) performs external checks,
  others read from shared Redis

### 3c. IPFS Latency on Every Bootstrap (Medium)

```
Bottleneck: bootstrap_sequence() resolves config CID via IPFS every
            restart. IPFS gateways take 1-5s per resolution.

Impact:     Container restarts (from OOM or updates) → 5-10s startup delay
```

**Fix:** 
- Cache resolved CID + content in Redis with TTL
- Only re-resolve on cache miss or explicit trigger

### 3d. uvloop Not Used on Windows/Linux (Low)

```
Bottleneck: FastAPI uses asyncio event loop, but the codebase never
            calls `uvloop.install()`. On Linux containers, uvloop
            provides 2x throughput for async I/O.

Impact:    ~200-400µs overhead per API call vs uvloop
```

**Fix:** Add `uvloop.install()` in `on_startup()` (Linux only).

### 3e. JSON Task Queue is Single-Node Only (Medium)

```
Bottleneck: TaskManager._read_queue() / _write_queue() reads and
            writes agent_data/task_queue.json. In 3-replica Akash
            deployment, each replica has its own filesystem — tasks
            are NOT shared across replicas.

Impact:    Tasks queued on replica A never execute on replicas B/C.
            Lost on replica restart.
```

**Fix:** Migrate task queue to Redis (already in docker-compose):
- `RPUSH task_queue <json>` for enqueue
- `BLPOP task_queue 0` for blocking claim
- All replicas share the same Redis queue

### 3f. Port Binding Conflicts (Medium)

```
Bottleneck: manager.py hardcodes port 8000, swarm hardcodes 9876.
            In Akash SDL only one container maps these ports.
            Second replica on same host gets EADDRINUSE.

Impact:    Replica fails to start, Akash reschedules (slow)
```

**Fix:** Already partially done in `autonomous_swarm.py:356` — need same
pattern for FastAPI (try port 8000, fallback 8001-8010).

---

## 4. Optimization Strategies for Low-Latency Swarm Communication

### 4a. Connection Pool Reuse (Current: Opens new TCP per message)

**Problem:** `GhostSwarmNode.broadcast()` creates a new `asyncio.open_connection()` for each peer per message. TCP handshake (SYN/SYN-ACK/ACK) adds 1-3 RTT before any data.

**Strategy: Persistent Connection Pool**
```python
self._connections: Dict[str, asyncio.StreamWriter] = {}

async def _get_connection(self, host, port):
    key = f"{host}:{port}"
    if key in self._connections and not self._connections[key].is_closing():
        return self._connections[key]
    _, writer = await asyncio.open_connection(host, port)
    self._connections[key] = writer
    return writer
```

**Expected gain:** Eliminates TCP handshake overhead per message. For WAN peers (50ms RTT), drops latency from ~55ms to ~2ms per message.

### 4b. Nagle's Algorithm Disable (Current: Default on)

**Problem:** TCP Nagle algorithm buffers small packets, adding 40ms delay per message.

**Strategy:** `transport.set_write_buffer_limits(0)` or set `TCP_NODELAY` on writer sockets.

**Expected gain:** Eliminates Nagle-induced 40ms delay for small control messages (ping, task_ack).

### 4c. UDP Fallback for Heartbeats (Current: TCP only)

**Problem:** `heartbeat_loop` (15s interval) sends TCP pings to all peers. On 100 peers, that's 100 TCP connections per cycle.

**Strategy:** Use UDP datagrams for heartbeats (already have UDP broadcast port 9877). Extend to direct UDP pings.

```
if peer in self._connections:  # TCP if connected
    await self._send_tcp(peer, ping_msg)
else:                          # UDP probe for liveness
    await self._send_udp(peer, ping_msg)
```

**Expected gain:** Heartbeat traffic goes from 100 TCP connections to 100 UDP datagrams per cycle. Zero connection overhead.

### 4d. Message Batching (Current: One message per send)

**Problem:** Swarm tasks are dispatched one-at-a-time. If 10 tasks queue up, 10 separate TCP sends happen.

**Strategy:** Batch messages in a short-lived buffer (5ms window):
```python
_batch_buffer: Dict[str, List[SwarmMessage]] = {}

async def _flush_batch(self, peer_key):
    if peer_key not in self._batch_buffer: return
    batch = self._batch_buffer.pop(peer_key)
    combined = SwarmMessage(
        msg_type="batch",
        payload=[m.to_dict() for m in batch],
        ...
    )
    await self._send_direct(peer_key, combined)
```

**Expected gain:** 5-10x reduction in TCP send calls under load.

### 4e. DTN (Delay-Tolerant Networking) Routing (Already Partially Implemented)

`ghost_swarm.py` already has `dtn_route` and `dtn_route_ack` message types. However, DTN is not actively used.

**Strategy:** Activate DTN for WAN peer segments:
- If direct TCP to peer fails → store message in DTN buffer → forward to intermediate peer → intermediate forwards to target
- DTN buffer uses SQLite or Redis for crash survival

### 4f. Predictable Latency: Active Queue Management

**Problem:** No backpressure — if a peer is slow, the sender keeps queuing.

**Strategy:** Per-peer send window with ACK tracking:
```python
self._send_window: Dict[str, asyncio.Semaphore] = {}
# Max 5 unACKed messages per peer
```
When window is full, new sends block until ACK received. Prevents sender from overwhelming slow peers.

### 4g. Shared State via Redis Pub/Sub (Complement to P2P)

**Problem:** P2P mesh is eventual-consistency. Status updates take 15s heartbeat cycles.

**Strategy:** For colocated replicas (same Akash deployment), use Redis Pub/Sub for real-time state sync:
- Channel `swarm:status` — replicas publish status every 1s
- Channel `swarm:tasks` — task assignments broadcast instantly
- P2P mesh remains for cross-cluster communication

---

## 5. Summary of Recommended Changes

| # | Issue | Priority | Effort | Fix |
|---|---|---|---|---|
| 1 | OOM on model load | **Critical** | Small | Memory-aware loading + 8-bit fallback |
| 2 | Redis task queue | **High** | Medium | Replace JSON file with Redis for multi-replica |
| 3 | Port fallback for FastAPI | **High** | Small | Try range 8000-8010 |
| 4 | Rate limit external checks | **High** | Medium | Redis lock for external API calls |
| 5 | Persistent TCP connections | **Medium** | Medium | Connection pool for swarm peers |
| 6 | UDP heartbeats | **Medium** | Small | Reduce TCP overhead for pings |
| 7 | Nagle disable | **Medium** | Small | TCP_NODELAY on swarm sockets |
| 8 | Message batching | **Low** | Medium | 5ms batch window for tasks |
| 9 | Active DTN routing | **Low** | Large | Activate existing DTN code paths |
| 10 | uvloop install | **Low** | Tiny | uvloop.install() in on_startup |

---

## 6. Latency Budget

```
Layer                  Current      Optimized     Gain
─────────────────────────────────────────────────────
Model Cascade (avg)    2-8s         1-4s          2x
Local HF Inference     500-2000ms   300-1000ms    1.6x  (8-bit quant)
Swarm Broadcast (LAN)  15-50ms      2-10ms        5x    (conn pool)
Swarm Broadcast (WAN)  100-500ms    20-100ms      5x    (conn pool)
Heartbeat Cycle        15s          5s            3x    (UDP)
Task Dispatch          50-200ms     10-50ms       5x    (batch + pool)
Status Poll (API)      200-500ms    50-100ms      4x    (Redis cache)
```
