# Helper Agent Specifications

## Agent 1: Security Sentinel
**Purpose:** Continuous secret scanning, constitutional auditing, Safe-State enforcement

**Specification:**
```yaml
name: security-sentinel
model: opencode-zen/qwen3.7-max
mode: subagent
description: >
  Scans all .py files for API key exposure, hardcoded secrets, and
  Article III constitutional violations. Triggers Safe-State if
  violations exceed threshold. Automatically rotates exposed keys.
triggers:
  - on_file_change: ["*.py", "*.json", "*.yaml", "*.env*"]
  - on_schedule: "*/30 * * * *"  # every 30 minutes
tools:
  - grep (regex secret patterns)
  - git diff (detect newly added secrets)
  - python security_engine.py (constitutional_audit)
actions:
  - detect_secret -> flag_for_review
  - detect_violation -> increment_article_iii_score
  - score_below_threshold -> activate_safe_state
dependencies:
  - .env (excluded from git but readable by agent)
  - node_identity.json (key rotation)
```

## Agent 2: Disk Health Monitor
**Purpose:** Track disk usage, predict exhaustion, trigger cleanup workflows

**Specification:**
```yaml
name: disk-health-monitor
model: opencode-zen/qwen3.7-max
mode: subagent
description: >
  Monitors C: and D: drive free space, reports when below thresholds,
  suggests cleanup actions, and can execute safe cleanup scripts.
triggers:
  - on_schedule: "*/15 * * * *"  # every 15 minutes
thresholds:
  warning: 5 GB
  critical: 1 GB
  current_status: "CRITICAL — C: has 0.0 GB free"
tools:
  - powershell (Get-PSDrive)
  - batch script execution
actions:
  - free_space_below_warning -> notify_user
  - free_space_below_critical -> suggest_cleanup_actions
  - auto_cleanup_temp -> execute_safe_deletions
```

## Agent 3: Git Hygiene Agent
**Purpose:** Manage commit hygiene, enforce .gitignore compliance, prevent secret leaks

**Specification:**
```yaml
name: git-hygiene-agent
model: opencode-zen/qwen3.7-max
mode: subagent
description: >
  Reviews staged files for secrets before commit, enforces commit
  message conventions, manages .gitignore rules, and suggests
  logical commit grouping.
triggers:
  - on_command: ["git commit", "git push"]
checks:
  - staged_files_contain_secrets -> block_commit
  - commit_message_length < 10 chars -> warn
  - .gitignore_missing_pattern -> suggest_update
tools:
  - grep (secret patterns in staged files)
  - git diff --cached
  - git log --oneline
actions:
  - secrets_detected -> abort_commit + notify
  - commit_message_ok -> allow
  - suggest_commit_grouping -> print_recommendation
```

## Agent 4: Hermes Sync Agent
**Purpose:** Bridge between workspace agents and Hermes Agent installation

**Specification:
```yaml
name: hermes-sync-agent
model: opencode-zen/qwen3.7-max
mode: subagent
description: >
  Synchronizes state between workspace Ghost Engine and Hermes Agent
  at C:\Users\zafar\AppData\Local\hermes. Handles task delegation,
  memory bridging, and cross-agent coordination.
bridge:
  type: subprocess
  path: C:\Users\zafar\AppData\Local\hermes
  entrypoint: hermes_agent_bridge.py
  protocol: JSON-over-stdin/stdout
capabilities:
  - delegate_task_to_hermes
  - query_hermes_memory
  - sync_workspace_state_to_hermes
  - receive_hermes_completions
error_handling:
  - hermes_unreachable -> queue_task_locally
  - hermes_response_timeout -> retry_hermes_with_backoff
  - hermes_quota_error -> fallback_to_local_model
```

## Agent 5: Deployment Orchestrator
**Purpose:** Manage Render.com and GitHub deployments with rollback capability

**Specification:
```yaml
name: deployment-orchestrator
model: opencode-zen/qwen3.7-max
mode: subagent
description: >
  Handles multi-target deployment: Render.com web service, HF Spaces,
  and Akash Network. Validates deployment configs before push and
  provides rollback scripts.
targets:
  - name: render
    type: web_service
    config: render.yaml
    command: uvicorn manager:app --host 0.0.0.0 --port $PORT
  - name: hf-spaces
    type: gradio
    config: hf_app.py
    secrets: [HUGGINGFACE_TOKEN]
  - name: akash
    type: sdl
    config: deploy.yaml
    replicas: 3
pre_deploy_checks:
  - verify_all_secrets_are_env_vars
  - check_requirements_txt_matches_deployment
  - validate_render_yaml
  - run_security_scan
rollback:
  - git revert --no-commit <deploy_hash>
  - git push origin main
```

## Agent 6: Ollama Model Manager
**Purpose:** Manage local LLM storage (11 GB on C:), model lifecycle, quantization

**Specification:
```yaml
name: ollama-model-manager
model: opencode-zen/deepseek-v4-flash-free
mode: subagent
description: >
  Manages Ollama model storage on C: with goal to relocate to D:.
  Tracks model usage, prunes unused models, suggests quantization
  (Q4_K_M vs Q8_0) to reduce footprint.
storage:
  current_path: C:\Users\zafar\.ollama
  current_size_gb: 11.0
  target_path: D:\.ollama
  target_size_gb: 3.0
commands:
  - list_models: "ollama list"
  - prune_model: "ollama rm <model>"
  - quantize: "ollama pull <model> --quantize Q4_K_M"
  - migrate: "Move-Item + New-Item -ItemType SymbolicLink"
rules:
  - keep_last_used_days: 30
  - auto_prune_unused_models: true
  - prefer_quantized_versions: true
  - allow_exclusions: ["llama3.2:1b", "mistral:7b"]
```
