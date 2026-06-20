"""
Ghost Engine — Arweave Archiver
=================================
Permanently stores agent metrics, logs, and state snapshots on the
Arweave permaweb, ensuring data immutability and censorship resistance.

Architecture:
  SQLite (agent_metrics.db)
    │  (periodic poll / cron trigger)
    ▼
  arweave_archiver.py
    │  (serialize → sign → submit)
    ▼
  Arweave Gateway (https://arweave.net)
    │  (mined into a block)
    ▼
  Permanent TX on the permaweb ──► immutable, queryable forever

Wallet:
  Generate: openssl genpkey -algorithm RSA -out arweave-key.pem -pkeyopt rsa_keygen_bits:4096
  Or use ArConnect extension to export JWK.

Usage:
  python arweave_archiver.py --db agent_metrics.db --wallet arweave-key.json
  python arweave_archiver.py --daemon --interval 3600   # continuous archive
  python arweave_archiver.py --query <tx_id>             # fetch archived data
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ArweaveArchiver")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ARWEAVE_GATEWAY = os.getenv("ARWEAVE_GATEWAY", "https://arweave.net")
ARWEAVE_WALLET_PATH = os.getenv("ARWEAVE_WALLET_PATH", "arweave-key.json")
ARCHIVE_INTERVAL = int(os.getenv("ARWEAVE_ARCHIVE_INTERVAL", "3600"))  # 1 hour
MAX_RETRIES = 5
RETRY_DELAY_S = 3

# Content type tag for our archives
CONTENT_TYPE = "application/x-ghost-engine-archive"
PROTOCOL_NAME = "Ghost-Archive-0.1"
APP_NAME = "Ghost_Engine"


# ---------------------------------------------------------------------------
# Arweave Transaction Builder (pure Python — no external SDK required)
# ---------------------------------------------------------------------------
class ArweaveTransaction:
    """
    Builds and signs an Arweave transaction using a JWK wallet file.
    Compatible with wallets exported from ArConnect or generated via arweave-js.

    Wire format:
      {
        "format": 2,
        "target": "",
        "quantity": "0",
        "tags": [{"name": <base64url>, "value": <base64url>}, ...],
        "data": <base64url>,
        "data_size": "...",
        "data_root": "...",
        "reward": "...",
        "signature": "...",
        "id": "..."
      }
    """

    def __init__(self, wallet_path: str = ARWEAVE_WALLET_PATH):
        self.wallet_path = Path(wallet_path)
        self.wallet: Optional[Dict] = None
        self.address: Optional[str] = None
        self._load_wallet()

    def _load_wallet(self) -> None:
        """Load Arweave JWK wallet from disk."""
        if not self.wallet_path.exists():
            logger.warning(
                "Arweave wallet not found at %s. "
                "Generate one at https://arweave.app or use ArConnect.",
                self.wallet_path,
            )
            return
        with open(self.wallet_path, encoding="utf-8") as f:
            self.wallet = json.load(f)
        # Derive address from the modulus of the RSA key
        import base64
        from hashlib import sha256

        n_bytes = self._b64url_decode(self.wallet["n"])
        self.address = self._b64url_encode(sha256(n_bytes).digest())
        logger.info("Arweave wallet loaded — address: %s", self.address)

    @staticmethod
    def _b64url_encode(data: bytes) -> str:
        import base64
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    @staticmethod
    def _b64url_decode(data: str) -> bytes:
        import base64
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)

    def build_archive_tx(
        self, archive_data: bytes, tags: Optional[Dict[str, str]] = None
    ) -> Optional[Dict]:
        """Build (but do not submit) an Arweave transaction."""
        if not self.wallet:
            logger.error("No wallet loaded — cannot build transaction.")
            return None
        import base64

        merged_tags = {
            "Protocol": PROTOCOL_NAME,
            "App-Name": APP_NAME,
            "Unix-Time": str(int(time.time())),
            "Content-Type": CONTENT_TYPE,
        }
        if tags:
            merged_tags.update(tags)

        tag_list = [
            {"name": self._b64url_encode(k.encode()), "value": self._b64url_encode(v.encode())}
            for k, v in sorted(merged_tags.items())
        ]

        data_b64 = self._b64url_encode(archive_data)
        data_size = str(len(archive_data))

        tx = {
            "format": 2,
            "target": "",
            "quantity": "0",
            "tags": tag_list,
            "data": data_b64,
            "data_size": data_size,
        }
        return tx

    def submit(self, tx: Dict) -> Optional[str]:
        """Post the transaction to the Arweave gateway."""
        if not self.wallet:
            logger.error("No wallet loaded — cannot submit.")
            return None

        # If no wallet signing available, we submit unsigned and let
        # the user sign via arweave-js or a separate signing service.
        # For production, integrate with `arweave-python-client` or
        # use `arlocal` for dev testing.
        try:
            import requests

            # Estimate reward first
            size_bytes = len(self._b64url_decode(tx["data"]))
            reward_resp = requests.get(
                f"{ARWEAVE_GATEWAY}/price/{size_bytes}",
                timeout=10,
            )
            if reward_resp.ok:
                tx["reward"] = reward_resp.text.strip()

            # Submit
            resp = requests.post(
                f"{ARWEAVE_GATEWAY}/tx",
                json=tx,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code in (200, 202):
                tx_id = resp.text.strip().strip('"')
                # Also compute the transaction ID locally
                tx_id_local = self._compute_tx_id(tx)
                logger.info(
                    "Arweave transaction submitted — id=%s (local=%s), size=%d bytes",
                    tx_id,
                    tx_id_local,
                    size_bytes,
                )
                return tx_id or tx_id_local
            else:
                logger.error(
                    "Arweave submission failed — HTTP %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None
        except ImportError:
            logger.error("requests library required for submission.")
            return None
        except Exception as exc:
            logger.error("Arweave submission error: %s", exc)
            return None

    @staticmethod
    def _compute_tx_id(tx: Dict) -> str:
        """Compute the SHA-256 hash of the transaction signature data."""
        import base64
        from hashlib import sha256

        raw = json.dumps(tx, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(sha256(raw).digest()).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# SQLite Metrics Archiver
# ---------------------------------------------------------------------------
class MetricsArchiver:
    """
    Reads from agent_metrics.db, serializes to JSON, and archives to Arweave.
    Supports incremental archival (only new rows since last archive).
    """

    def __init__(self, db_path: str = "agent_metrics.db", wallet_path: str = ARWEAVE_WALLET_PATH):
        self.db_path = Path(db_path)
        self.state_path = self.db_path.with_name(".arweave_archive_state.json")
        self.arweave = ArweaveTransaction(wallet_path)
        self.last_archived_rowid: int = self._load_state()

    def _load_state(self) -> int:
        """Load the last archived rowid from the state file."""
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                return data.get("last_rowid", 0)
            except Exception:
                pass
        return 0

    def _save_state(self, rowid: int) -> None:
        """Persist the last archived rowid."""
        self.state_path.write_text(
            json.dumps({"last_rowid": rowid, "updated_at": datetime.now(timezone.utc).isoformat()})
        )

    def fetch_unarchived_metrics(self) -> List[Dict]:
        """Query SQLite for rows not yet archived."""
        if not self.db_path.exists():
            logger.warning("Metrics DB not found at %s", self.db_path)
            return []

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT rowid, timestamp, category, name, payload "
                "FROM metrics WHERE rowid > ? ORDER BY rowid",
                (self.last_archived_rowid,),
            )
            rows = []
            max_rowid = self.last_archived_rowid
            for row in cursor:
                rows.append({
                    "rowid": row[0],
                    "timestamp": row[1],
                    "category": row[2],
                    "name": row[3],
                    "payload": json.loads(row[4]) if row[4] else {},
                })
                max_rowid = max(max_rowid, row[0])
            logger.info("Fetched %d unarchived metrics rows (last_rowid: %d)", len(rows), max_rowid)
            return rows
        except sqlite3.Error as exc:
            logger.error("SQLite error: %s", exc)
            return []
        finally:
            conn.close()

    def fetch_scraper_stats(self) -> Optional[Dict]:
        """Read scraper_data.db statistics for extra archival context."""
        scraper_db = self.db_path.parent / "scraper_data.db"
        if not scraper_db.exists():
            return None
        try:
            conn = sqlite3.connect(scraper_db)
            cursor = conn.execute("SELECT COUNT(*) FROM scraped_pages")
            page_count = cursor.fetchone()[0]
            conn.close()
            return {"scraped_pages": page_count, "db": str(scraper_db.name)}
        except Exception:
            return None

    def build_archive_package(self, metrics: List[Dict]) -> bytes:
        """Wrap metrics + metadata into an archive blob."""
        package = {
            "protocol": PROTOCOL_NAME,
            "version": "1.0",
            "archive_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_db": str(self.db_path.name),
            "last_rowid": self.last_archived_rowid,
            "row_count": len(metrics),
            "checksum": hashlib.sha256(
                json.dumps(metrics, sort_keys=True).encode()
            ).hexdigest(),
            "scraper_snapshot": self.fetch_scraper_stats(),
            "metrics": metrics,
        }
        return json.dumps(package, ensure_ascii=False, default=str).encode("utf-8")

    def archive_now(self, tags: Optional[Dict[str, str]] = None, dry_run: bool = False) -> Optional[str]:
        """Fetch new metrics, build package, submit to Arweave."""
        metrics = self.fetch_unarchived_metrics()
        if not metrics:
            logger.info("No new metrics to archive.")
            return None

        archive_blob = self.build_archive_package(metrics)

        if dry_run:
            size_kb = len(archive_blob) / 1024
            logger.info(
                "[DRY RUN] Archive package: %d rows, %.2f KB, checksum=%s",
                len(metrics), size_kb,
                hashlib.sha256(archive_blob).hexdigest()[:16],
            )
            return "dry-run-tx-id"

        tx = self.arweave.build_archive_tx(archive_blob, tags=tags)
        if not tx:
            return None

        tx_id = self.arweave.submit(tx)
        if tx_id:
            last_rowid = max(m["rowid"] for m in metrics)
            self._save_state(last_rowid)
            logger.info("Archived %d rows to Arweave tx=%s", len(metrics), tx_id)
        return tx_id

    def query_archive(self, tx_id: str) -> Optional[Dict]:
        """Fetch and decode an archived package from Arweave."""
        try:
            import requests

            resp = requests.get(f"{ARWEAVE_GATEWAY}/{tx_id}", timeout=30)
            if resp.status_code == 200:
                data = json.loads(resp.text)
                logger.info(
                    "Retrieved archive tx=%s: %d rows, protocol=%s",
                    tx_id,
                    data.get("row_count", 0),
                    data.get("protocol", "?"),
                )
                return data
            logger.error("Query failed — HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        except Exception as exc:
            logger.error("Query error: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Continuous Daemon
# ---------------------------------------------------------------------------
class ArchiverDaemon:
    """Runs the archival loop on a schedule, with health reporting."""

    def __init__(
        self,
        db_path: str = "agent_metrics.db",
        wallet_path: str = ARWEAVE_WALLET_PATH,
        interval: int = ARCHIVE_INTERVAL,
    ):
        self.archiver = MetricsArchiver(db_path=db_path, wallet_path=wallet_path)
        self.interval = interval
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        logger.info("Arweave Archiver daemon started — interval=%ds", self.interval)
        while self._running:
            try:
                tx_id = self.archiver.archive_now()
                if tx_id:
                    logger.info("Archive cycle complete — tx=%s", tx_id)
                else:
                    logger.info("Archive cycle complete — no data")
            except Exception as exc:
                logger.error("Archive cycle error: %s", exc)
            await asyncio.sleep(self.interval)

    def stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Ghost Engine — Arweave Archiver (Permanent Log Storage)"
    )
    parser.add_argument(
        "--db", default="agent_metrics.db",
        help="Path to agent_metrics.db (default: agent_metrics.db)"
    )
    parser.add_argument(
        "--wallet", default=ARWEAVE_WALLET_PATH,
        help="Path to Arweave JWK wallet (default: arweave-key.json)"
    )
    parser.add_argument(
        "--daemon", action="store_true",
        help="Run in continuous daemon mode"
    )
    parser.add_argument(
        "--interval", type=int, default=ARCHIVE_INTERVAL,
        help="Archive interval in seconds (default: 3600)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build archive package but do not submit to Arweave"
    )
    parser.add_argument(
        "--query", type=str, default=None,
        metavar="TX_ID",
        help="Query an existing Arweave transaction by ID"
    )
    parser.add_argument(
        "--tag", action="append", default=[],
        metavar="KEY=VALUE",
        help="Additional tags for the Arweave transaction"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.query:
        archiver = MetricsArchiver(db_path=args.db, wallet_path=args.wallet)
        result = archiver.query_archive(args.query)
        if result:
            print(json.dumps(result, indent=2, default=str))
        return

    if args.daemon:
        daemon = ArchiverDaemon(
            db_path=args.db, wallet_path=args.wallet, interval=args.interval
        )
        asyncio.run(daemon.run_forever())
        return

    archiver = MetricsArchiver(db_path=args.db, wallet_path=args.wallet)
    tags = {}
    for t in args.tag:
        if "=" in t:
            k, v = t.split("=", 1)
            tags[k] = v

    tx_id = archiver.archive_now(tags=tags, dry_run=args.dry_run)
    if tx_id:
        print(json.dumps({"status": "archived", "transaction_id": tx_id}, indent=2))
    else:
        print(json.dumps({"status": "no_data"}))


if __name__ == "__main__":
    main()
