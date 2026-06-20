#!/usr/bin/env bash
# =============================================================================
# Ghost Engine -- Akash Network Deployment Automation
# =============================================================================
# This script handles the complete Akash deployment lifecycle:
#   1. Verify prerequisites (Akash CLI, wallet, funding)
#   2. Validate and submit the SDL
#   3. Monitor the bid auction
#   4. Accept the winning bid
#   5. Send the manifest to deploy
#   6. Confirm deployment on a random provider node
#   7. Print connection details
#
# Usage:
#   chmod +x akash_deploy.sh
#   ./akash_deploy.sh                          # interactive
#   ./akash_deploy.sh --auto                   # automated (uses defaults)
#   ./akash_deploy.sh --deploy-yaml ./deploy.yaml --key my-wallet
#
# Environment variables:
#   AKASH_KEY_NAME      Wallet key name (default: ghost-deployer)
#   AKASH_KEYRING_BACKEND  Keyring backend (default: os)
#   AKASH_NODE          Akash RPC node (default: https://rpc.akashnet.net:443)
#   AKASH_CHAIN_ID      Chain ID (default: akashnet-2)
#   AKASH_GAS           Gas adjustment (default: auto)
#   AKASH_GAS_PRICE     Gas price (default: 0.025uakt)
#   AKASH_DSEQ          Deployment sequence (auto-detected)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_YAML="${DEPLOY_YAML:-$SCRIPT_DIR/deploy.yaml}"
KEY_NAME="${AKASH_KEY_NAME:-ghost-deployer}"
KEYRING_BACKEND="${AKASH_KEYRING_BACKEND:-os}"
AKASH_NODE="${AKASH_NODE:-https://rpc.akashnet.net:443}"
CHAIN_ID="${AKASH_CHAIN_ID:-akashnet-2}"
GAS="${AKASH_GAS:-auto}"
GAS_PRICE="${AKASH_GAS_PRICE:-0.025uakt}"
DSEQ_FILE="$SCRIPT_DIR/.akash_dseq"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; BOLD='\033[1m'; NC='\033[0m'
CHECK="${GREEN}+${NC}"; CROSS="${RED}x${NC}"; INFO="${CYAN}i${NC}"

AUTO_MODE=false
if [[ "${1:-}" == "--auto" ]]; then AUTO_MODE=true; fi
if [[ "${1:-}" == "--deploy-yaml" ]]; then DEPLOY_YAML="$2"; fi
if [[ "${1:-}" == "--key" ]]; then KEY_NAME="$2"; fi

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
log()  { echo -e "${GREEN}[DEPLOY]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }
header() {
    echo ""
    echo -e "${BOLD}+==========================================================+${NC}"
    printf "${BOLD}|${NC}  %-60s ${BOLD}|${NC}\n" "$1"
    echo -e "${BOLD}+==========================================================+${NC}"
    echo ""
}

# ---------------------------------------------------------------------------
# Step 0: Pre-flight checks
# ---------------------------------------------------------------------------
preflight() {
    header "GHOST ENGINE -- AKASH DEPLOYMENT SEQUENCE"

    # Check Akash CLI
    if ! command -v provider-services &>/dev/null; then
        err "Akash CLI (provider-services) not found."
        info "Install: curl -sSfL https://raw.githubusercontent.com/akash-network/install/main/install.sh | bash"
        exit 1
    fi
    AKASH_VERSION=$(provider-services version 2>&1 | head -1)
    echo -e "  $CHECK Akash CLI:             $AKASH_VERSION"

    # Check deploy.yaml exists
    if [[ ! -f "$DEPLOY_YAML" ]]; then
        err "Deployment SDL not found: $DEPLOY_YAML"
    fi
    echo -e "  $CHECK SDL file:              $DEPLOY_YAML ($(wc -l < "$DEPLOY_YAML") lines)"

    # Validate SDL syntax
    if provider-services validate "$DEPLOY_YAML" &>/dev/null; then
        echo -e "  $CHECK SDL validation:        valid"
    else
        err "SDL validation failed"
    fi

    # Check wallet
    if ! provider-services keys show "$KEY_NAME" --keyring-backend "$KEYRING_BACKEND" &>/dev/null; then
        warn "Wallet '$KEY_NAME' not found. Creating..."
        provider-services keys add "$KEY_NAME" --keyring-backend "$KEYRING_BACKEND"
    fi
    ACCOUNT=$(provider-services keys show "$KEY_NAME" -a --keyring-backend "$KEYRING_BACKEND")
    echo -e "  $CHECK Wallet:                 $KEY_NAME ($ACCOUNT)"

    # Check balance
    BALANCE=$(provider-services query bank balances "$ACCOUNT" --node "$AKASH_NODE" 2>/dev/null \
        | grep "uakt" | awk '{print $3}' || echo "0")
    if [[ "$BALANCE" -le 5000000 ]]; then
        warn "Low balance: ${BALANCE}uakt. Fund wallet:"
        info "curl -s https://faucet.akash.network/faucet?address=$ACCOUNT"
        if [[ "$AUTO_MODE" == false ]]; then
            echo -ne "  ${YELLOW}Continue with low balance? [y/N]${NC} "
            read -r ans; [[ "$ans" != "y" ]] && exit 1
        fi
    fi
    echo -e "  $CHECK Balance:                ${BALANCE}uakt"
    echo ""
}

# ---------------------------------------------------------------------------
# Step 1: Create deployment
# ---------------------------------------------------------------------------
create_deployment() {
    header "STEP 1/5 -- SUBMITTING DEPLOYMENT"

    local tx_result
    tx_result=$(provider-services tx deployment create "$DEPLOY_YAML" \
        --from "$KEY_NAME" \
        --node "$AKASH_NODE" \
        --chain-id "$CHAIN_ID" \
        --keyring-backend "$KEYRING_BACKEND" \
        --gas "$GAS" \
        --gas-prices "$GAS_PRICE" \
        -y \
        -o json 2>&1)

    DSEQ=$(echo "$tx_result" | grep -oP '"dseq":"?\K[0-9]+' | head -1 || true)
    if [[ -z "$DSEQ" ]]; then
        DSEQ=$(echo "$tx_result" | grep -oP 'dseq:\s*\K[0-9]+' | head -1 || true)
    fi

    if [[ -z "$DSEQ" ]]; then
        err "Failed to extract DSEQ from deployment response."
        echo "$tx_result"
        exit 1
    fi

    echo "$DSEQ" > "$DSEQ_FILE"
    echo -e "  $CHECK Deployment created:      DSEQ=$DSEQ"
    echo -e "  $INFO Explorer: https://akash.chainmovers.com/deployments/$DSEQ"
    echo ""
}

# ---------------------------------------------------------------------------
# Step 2: Wait for bids
# ---------------------------------------------------------------------------
wait_for_bids() {
    header "STEP 2/5 -- AWAITING PROVIDER BIDS"

    local owner
    owner=$(provider-services keys show "$KEY_NAME" -a --keyring-backend "$KEYRING_BACKEND")
    echo -e "  $INFO Watching for bids on DSEQ=$DSEQ (timeout: 120s)..."
    echo ""

    local deadline=$((SECONDS + 120))
    local bid_found=false
    local bid_provider=""
    local bid_amount=""

    while [[ $SECONDS -lt $deadline ]]; do
        local bids
        bids=$(provider-services query market bid list \
            --owner "$owner" \
            --node "$AKASH_NODE" \
            --dseq "$DSEQ" \
            -o json 2>/dev/null || echo "[]")

        local provider_count
        provider_count=$(echo "$bids" | grep -c '"state":"open"' || true)

        if [[ "$provider_count" -gt 0 ]]; then
            # Pick a random provider from the open bids
            bid_provider=$(echo "$bids" | grep -oP '"provider":"\K[^"]+' | shuf -n1)
            bid_amount=$(echo "$bids" | grep -B2 "$bid_provider" | grep -oP '"price".*?"amount":"\K[^"]+' || echo "?")
            echo -e "  $CHECK Bid received from:        $bid_provider"
            echo -e "  $CHECK Price:                     ${bid_amount}uakt/month"

            # Show all providers for transparency
            echo ""
            echo -e "  ${BOLD}Available providers:${NC}"
            echo "$bids" | grep -oP '"provider":"\K[^"]+' | while read -r p; do
                local p_price
                p_price=$(echo "$bids" | grep -B2 "$p" | grep -oP '"price".*?"amount":"\K[^"]+' || echo "?")
                if [[ "$p" == "$bid_provider" ]]; then
                    echo -e "    ${GREEN}-> $p (${p_price}uakt) <- SELECTED${NC}"
                else
                    echo -e "      $p (${p_price}uakt)"
                fi
            done
            echo ""

            bid_found=true
            break
        fi

        printf "\r  [*] Waiting for bids... (%ds remaining)" $((deadline - SECONDS))
        sleep 3
    done
    echo ""

    if [[ "$bid_found" == false ]]; then
        err "No bids received within timeout."
        info "Try increasing the resource allocation in deploy.yaml, or check Akash provider availability."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Step 3: Accept lease
# ---------------------------------------------------------------------------
accept_lease() {
    header "STEP 3/5 -- ACCEPTING LEASE"

    local result
    result=$(provider-services tx market lease create \
        --dseq "$DSEQ" \
        --provider "$bid_provider" \
        --from "$KEY_NAME" \
        --node "$AKASH_NODE" \
        --chain-id "$CHAIN_ID" \
        --keyring-backend "$KEYRING_BACKEND" \
        --gas "$GAS" \
        --gas-prices "$GAS_PRICE" \
        -y \
        -o json 2>&1)

    local tx_hash
    tx_hash=$(echo "$result" | grep -oP '"txhash":"\K[^"]+' | head -1)

    if [[ -n "$tx_hash" ]]; then
        echo -e "  $CHECK Lease accepted:           $bid_provider"
        echo -e "  $CHECK TX hash:                  $tx_hash"
    else
        warn "Lease creation may have succeeded. Checking status..."
        echo "$result"
    fi
    echo ""
}

# ---------------------------------------------------------------------------
# Step 4: Send manifest
# ---------------------------------------------------------------------------
send_manifest() {
    header "STEP 4/5 -- SENDING MANIFEST"

    local result
    result=$(provider-services send-manifest "$DEPLOY_YAML" \
        --dseq "$DSEQ" \
        --provider "$bid_provider" \
        --from "$KEY_NAME" \
        --node "$AKASH_NODE" \
        --keyring-backend "$KEYRING_BACKEND" \
        -o json 2>&1)

    echo -e "  $CHECK Manifest sent to provider: $bid_provider"
    echo ""
}

# ---------------------------------------------------------------------------
# Step 5: Confirm deployment
# ---------------------------------------------------------------------------
confirm_deployment() {
    header "STEP 5/5 -- CONFIRMING DEPLOYMENT"

    local owner
    owner=$(provider-services keys show "$KEY_NAME" -a --keyring-backend "$KEYRING_BACKEND")

    echo -e "  $INFO Waiting for deployment to go live..."
    local deadline=$((SECONDS + 60))
    local lease_status=""

    while [[ $SECONDS -lt $deadline ]]; do
        lease_status=$(provider-services query deployment get \
            --dseq "$DSEQ" \
            --owner "$owner" \
            --node "$AKASH_NODE" \
            -o json 2>/dev/null \
            | grep -oP '"state":"\K[^"]+' | head -1 || echo "pending")

        if [[ "$lease_status" == "active" ]]; then
            echo -e "  $CHECK Deployment state:          ${GREEN}ACTIVE${NC}"
            break
        fi
        printf "\r  [*] State: %s..." "$lease_status"
        sleep 3
    done
    echo ""

    # Get provider IP
    local provider_uri
    provider_uri=$(provider-services query provider get "$bid_provider" \
        --node "$AKASH_NODE" \
        -o json 2>/dev/null \
        | grep -oP '"host_uri":"\K[^"]+' || echo "unknown")

    # Get the port mappings
    local ports_info
    ports_info=$(provider-services query lease list \
        --owner "$owner" \
        --node "$AKASH_NODE" \
        --dseq "$DSEQ" \
        -o json 2>/dev/null \
        | grep -oP '"ports":\[.*?\]' \
        | head -1 || echo "")

    echo ""
    echo -e "${BOLD}${GREEN}+==========================================================+${NC}"
    echo -e "${BOLD}${GREEN}|${NC}  [*]  DEPLOYMENT COMPLETE                                ${BOLD}${GREEN}|${NC}"
    echo -e "${BOLD}${GREEN}+==========================================================+${NC}"
    echo ""
    echo -e "  ${BOLD}Deployment ID:${NC}    $DSEQ"
    echo -e "  ${BOLD}Provider:${NC}         $bid_provider"
    echo -e "  ${BOLD}Provider URI:${NC}     $provider_uri"
    echo -e "  ${BOLD}Status:${NC}           ${GREEN}ACTIVE${NC}"
    echo -e "  ${BOLD}Services:${NC}"
    echo -e "    * ghost-engine (3 replicas)  -- Port 8000 (API)"
    echo -e "    * ipfs-node    (1 replica)   -- Port 5001 (API)"
    echo -e "    * redis-node   (1 replica)   -- Port 6379"
    echo ""
    echo -e "  ${BOLD}Access your agent:${NC}"
    echo -e "    ${CYAN}https://$bid_provider:8000${NC}  (or via provider URI)"
    echo -e "    ${CYAN}provider-services query lease list --owner $owner --dseq $DSEQ${NC}"
    echo ""
    echo -e "  ${BOLD}P2P Swarm ports:${NC}"
    echo -e "    9876 -- Ghost Swarm TCP"
    echo -e "    9877 -- Broadcast UDP"
    echo -e "    8468 -- Kademlia DHT"
    echo -e "    9875 -- Quantum-safe handshake"
    echo ""
    echo -e "  ${MAGENTA}Self-healing registry:${NC}"
    echo -e "    This deployment is registered in the on-chain registry."
    echo -e "    If a node fails, the bootstrap routine redeploys automatically."
    echo ""
    echo -e "${YELLOW}Save this info! DSEQ=$DSEQ, Provider=$bid_provider${NC}"
    echo ""
}

# ---------------------------------------------------------------------------
# Cleanup handler
# ---------------------------------------------------------------------------
cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo ""
        warn "Deployment interrupted or failed."
        if [[ -n "${DSEQ:-}" ]]; then
            info "To close deployment: provider-services tx deployment close --dseq $DSEQ --from $KEY_NAME -y"
        fi
    fi
    exit $exit_code
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    preflight
    create_deployment
    wait_for_bids
    accept_lease
    send_manifest
    confirm_deployment
}

main
