# D Drive Migration Plan

## Rationale
- C Drive: **0.0 GB free** (47.8 GB total, completely full)
- D Drive: **211 GB free** (249.3 GB total)

## Migration Steps (ordered by priority & impact)

### Phase 1: Immediate (Free ~12 GB)

| Item | From (C:) | To (D:) | Size | Method |
|------|-----------|---------|------|--------|
| Ollama models | `%USERPROFILE%\.ollama` | `D:\.ollama` | ~11 GB | Move + symlink |
| Temp files | `%TEMP%\nstA0C6.tmp` etc. | Delete | ~840 MB | Deletion |
| Hermes cache | `%LOCALAPPDATA%\hermes\hermes-agent\node_modules` | Clear | Variable | Deletion |

**Ollama migration command:**
```powershell
# Stop Ollama first
ollama stop 2>$null
taskkill /IM ollama.exe /F 2>$null

# Move data
Move-Item "$env:USERPROFILE\.ollama" "D:\.ollama"

# Create symlink
New-Item -ItemType SymbolicLink -Path "$env:USERPROFILE\.ollama" -Target "D:\.ollama"

# Restart Ollama
ollama serve
```

### Phase 2: Workspace Relocation (Free ~20 MB)

Move the entire workspace to D Drive:
```powershell
# Clone/copy workspace
Copy-Item "D:\DDecentralized_AI_Agent" "D:\DDecentralized_AI_Agent_backup" -Recurse
# Actually the workspace is ALREADY on D: — check path
```

**Note:** Workspace is already at `D:\DDecentralized_AI_Agent`. The issue is user-local data on C:.

### Phase 3: Developer Tools Relocation (Free ~1.5 GB)

| Item | From (C:) | To (D:) | Size |
|------|-----------|---------|------|
| Antigravity IDE | `%USERPROFILE%\.antigravity-ide` | `D:\.antigravity-ide` | 754 MB |
| OpenCode | `%USERPROFILE%\.opencode` | `D:\.opencode` | 210 MB |
| .local | `%USERPROFILE%\.local` | `D:\.local` | 495 MB |
| .config | `%USERPROFILE%\.config` | `D:\.config` | 65 MB |
| Gemini data | `%USERPROFILE%\.gemini` | `D:\.gemini` | 31 MB |
| Browser agent | `%USERPROFILE%\.browser_agent` | `D:\.browser_agent` | 14 MB |
| .cache | `%USERPROFILE%\.cache` | `D:\.cache` | 11 MB |
| .wdm | `%USERPROFILE%\.wdm` | `D:\.wdm` | 59 MB |

### Phase 4: Hermes Agent Relocation

Move Hermes from `%LOCALAPPDATA%\hermes` to `D:\hermes`:
```powershell
# Stop Hermes if running
# Move directory
Move-Item "$env:LOCALAPPDATA\hermes" "D:\hermes"
# Create junction (symlink for directories)
New-Item -ItemType Junction -Path "$env:LOCALAPPDATA\hermes" -Target "D:\hermes"
```

## Space Recovery Projection

| Phase | Action | Space Recovered | Cumulative |
|-------|--------|----------------|------------|
| 1a | Ollama relocation | ~11,015 MB | ~10.8 GB |
| 1b | Temp deletion | ~840 MB | ~11.6 GB |
| 2 | Workspace (already on D:) | — | ~11.6 GB |
| 3a | Antigravity IDE | ~754 MB | ~12.3 GB |
| 3b | OpenCode | ~210 MB | ~12.5 GB |
| 3c | .local | ~495 MB | ~13.0 GB |
| 3d | .config + .gemini | ~96 MB | ~13.1 GB |
| 3e | Browser agent + .cache | ~25 MB | ~13.2 GB |
| 3f | .wdm | ~59 MB | ~13.2 GB |
| Total | All phases | ~13,494 MB | ~13.2 GB free |

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Symlink breaks after Windows Update | Minor | Keep a restore script ready |
| Ollama fails to find models after move | Medium | Verify symlink works before deleting originals |
| Application configs break after .config move | High | Move app-by-app rather than entire .config |
| Hermes breaks after relocation | Medium | Update hermes_config.yaml paths |
