# System Workflow Graph

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           USER / DEVELOPER                               │
│                    (opencode CLI / VS Code / Browser)                    │
└───────────────────────────┬─────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          OPENCODE CLI / DESKTOP                          │
│                                                                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐  │
│  │  Subagent:      │  │  Subagent:      │  │  Provider:              │  │
│  │  Hermes AI      │  │  Ghost-Prime    │  │  opencode-zen           │  │
│  │  (Qwen3.7 Max)  │  │  (Qwen3.7 Max)  │  │  DeepSeek V4 Flash     │  │
│  └────────┬────────┘  └────────┬────────┘  │  Qwen3.7 Max            │  │
│           │                    │            └───────────┬─────────────┘  │
│           └────────┬───────────┘                        │                │
│                    │                                    │                │
│                    ▼                                    ▼                │
│           ┌────────────────┐              ┌──────────────────────┐      │
│           │ Hermes Bridge  │              │  opencode.ai API     │      │
│           │ (subprocess)   │              │  (cloud inference)   │      │
│           └────────┬───────┘              └──────────────────────┘      │
└────────────────────┼────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          HERMES AGENT                                     │
│           (C:\Users\zafar\AppData\Local\hermes\)                         │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     AIAgent (conversation_loop.py)                │   │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │   │
│  │  │Memory   │  │Context   │  │Tool      │  │Turn Finalizer    │  │   │
│  │  │Manager  │  │Engine    │  │Executor  │  │(retry/fallback)  │  │   │
│  │  └────┬────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │   │
│  └───────┼────────────┼─────────────┼──────────────────┼─────────────┘   │
│          │            │             │                  │                  │
│          ▼            ▼             ▼                  ▼                  │
│  ┌──────────┐ ┌────────────┐ ┌──────────┐ ┌──────────────────────┐      │
│  │ Memory   │ │ Context    │ │ Tool     │ │ Provider Adapters    │      │
│  │ Providers│ │ Compressor │ │ Registry │ │ (Gemini/GitHub/      │      │
│  │ (plugin) │ │            │ │ (90+     │ │  OpenRouter/Nous/    │      │
│  │          │ │            │ │  tools)  │ │  Bedrock/Codex)      │      │
│  └──────────┘ └────────────┘ └────┬─────┘ └──────────────────────┘      │
│                                    │                                      │
└────────────────────────────────────┼──────────────────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
        ▼                            ▼                            ▼
┌───────────────┐          ┌──────────────────┐          ┌──────────────┐
│ LLM PROVIDERS │          │ EXTERNAL TOOLS   │          │ GHOST ENGINE │
│               │          │                   │          │ (Workspace)  │
│ Gemini API    │          │ Browser (CDP)    │          │              │
│ (429 quota)   │          │ Discord          │          │ ModelRouter  │
│               │          │ GitHub           │          │ (4-tier      │
│ OpenRouter    │          │ Gmail            │          │  cascade)    │
│ (payment err) │          │ Slack/Feishu     │          │              │
│               │          │ File System      │          │ HFInference  │
│ GitHub Copilot│          │ Terminal         │          │ (local)      │
│ (PAT issue)   │          │ MCP Servers      │          │              │
│               │          │ Kanban           │          │ GhostSwarm   │
│ Nous (missing)│          │ Cron Jobs        │          │ (P2P mesh)   │
│               │          │ Image Gen        │          │              │
│ Bedrock       │          │ TTS/Video        │          │ BrowserAgent │
│ Codex         │          │ Home Assistant   │          │ (Playwright) │
│               │          │ Web Search       │          │              │
└───────────────┘          └──────────────────┘          │ SecurityEng  │
                                                          │ (Constitution)│
                                                          │              │
                                                          │ StealthLayer │
                                                          │ (satellite)  │
                                                          └──────────────┘

## Data Flow: User Request → Response

User Prompt
  │
  ▼
OpenCode CLI
  │  (selects subagent or direct)
  ├──→ DeepSeek V4 Flash Free (opencode-zen cloud)
  │      │
  │      ├──→ Tool call: read files, grep, bash, etc.
  │      └──→ Response back to user
  │
  └──→ Hermes Subagent (via opencode-zen cloud)
         │
         ▼
     Hermes Bridge (subprocess)
         │
         ▼
     Hermes AIAgent conversation_loop.py
         │
         ├──→ MemoryManager.prefetch_all()
         ├──→ ContextEngine.build_turn_context()
         ├──→ Model call (via provider adapter)
         │      ├──→ Gemini API (429 quota errors seen)
         │      ├──→ GitHub Copilot (PAT type mismatch)
         │      ├──→ OpenRouter (payment errors seen)
         │      └──→ Nous (auth missing)
         ├──→ ToolExecutor.execute() (90+ tools)
         │      ├──→ Browser (CDP/Playwright)
         │      ├──→ File operations
         │      ├──→ Code execution
         │      ├──→ Discord/Gmail/GitHub
         │      └──→ Delegate to Ghost Engine bridge
         ├──→ TurnRetryState (jittered backoff on failure)
         └──→ MemoryManager.sync_all()

## Ghost Engine Internal Data Flow

Manager (FastAPI :8000)
  │
  ├── ModelRouter.route()
  │     ├── Groq API (Tier 1)
  │     ├── Gemini API (Tier 2)
  │     ├── HF Inference local (Tier 3)
  │     └── Ollama local (Tier 4)
  │
  ├── ToolRegistry (auto-patching)
  │     ├── PerformanceAnalyzer (post-exec hooks)
  │     ├── HealthEngine (self-healing)
  │     └── SwarmSecurity (encrypted P2P)
  │
  ├── GhostSwarmNode (P2P mesh)
  │     ├── TCP peer mesh
  │     ├── UDP LAN discovery
  │     ├── Kademlia DHT
  │     └── IPFS config resolution
  │
  ├── BrowserAgent (Playwright)
  │     ├── MetaMask automation
  │     ├── Social media posting
  │     └── Web scraping
  │
  ├── Stealth Layer (satellite)
  │     ├── DVB-S2 NULL-packet modulation
  │     ├── Thermal-noise echo mode
  │     └── Seed reassembly protocol
  │
  └── SecurityEngine (constitutional audit)
        ├── Article I-VI scoring
        ├── Key exposure detection
        └── Safe-State activation

## Memory Flow

User Query
  │
  ▼
MemoryManager.prefetch_all()
  │
  ├── Plugin Memory Provider (external, singleton)
  │     └── Retrieve relevant context from vector store
  │
  └── Return context blocks
        │
        ▼
  Conversation Loop (build_turn_context)
        │
        ▼
  Model generates response
        │
        ▼
  MemoryManager.sync_all()
        │
        └── Store in memory provider (async)

## Error Flow

API Error (429, 401, 500)
  │
  ▼
ErrorClassifier.classify_api_error()
  │
  ├── 429 (Rate Limit) → TurnRetryState (exponential backoff, max 3 retries)
  │     └── If all retries fail → ModelRouter fallback to next tier
  │
  ├── 401 (Auth) → log error, skip provider, try next
  │
  ├── 500 (Server) → jittered backoff, max 2 retries
  │
  └── Timeout → reduce context, retry with smaller window

## Security Flow

File Write / Config Change
  │
  ▼
SecurityEngine.constitutional_audit()
  │
  ├── Scan all .py for dangerous patterns
  │     ├── "rm -rf" → Article III.1 violation
  │     ├── "private_key" → Article III.2 violation
  │     └── "eval(" → Article III.4 violation
  │
  ├── Calculate Article scores (I-VI)
  │
  ├── Article III score < 70?
  │     ├── YES → Activate Safe-State mode
  │     │        └── Degraded operation, human review required
  │     └── NO  → Normal operation continues
  │
  └── Log violations to constitutional_violations.log
```
