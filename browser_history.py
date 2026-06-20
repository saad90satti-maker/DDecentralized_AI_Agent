"""
Browser History Controller & Search Tool
========================================

Accesses the Chrome History SQLite database to search, inspect, and
control browser history entries.

Database location:
    %LOCALAPPDATA%\Google\Chrome\User Data\Default\History

Constraints:
    Chrome locks the History file while running.  This module always
    works on a *copy* of the database so the source is never corrupted.

Features:
    - search_history(query, limit)
    - get_recent_history(limit)
    - delete_history_by_pattern(query)  -- marks as hidden
    - clear_all_history()
"""

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

USER_DATA_DIR = Path(os.getenv("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data" / "Default"
HISTORY_DB = USER_DATA_DIR / "History"


def _copy_history_db() -> Optional[Path]:
    """Return a temporary copy of the Chrome History database.

    Returns None if the source does not exist or cannot be copied.
    """
    if not HISTORY_DB.exists():
        return None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".history.db")
        os.close(fd)
        shutil.copy2(HISTORY_DB, tmp_path)
        return Path(tmp_path)
    except Exception as exc:
        print(f"[ERROR] Failed to copy history database: {exc}")
        return None


def _chrome_time_to_datetime(chrome_time: int) -> str:
    """Convert Chrome's WebKit timestamp (microseconds since 1601-01-01) to ISO string."""
    from datetime import datetime, timezone, timedelta
    epoch_start = datetime(1601, 1, 1, tzinfo=timezone.utc)
    delta = timedelta(microseconds=chrome_time)
    return (epoch_start + delta).isoformat()


def search_history(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Search browser history by URL or title containing *query* (case-insensitive)."""
    tmp = _copy_history_db()
    if not tmp:
        return []

    results = []
    try:
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        pattern = f"%{query.lower()}%"
        cur.execute(
            """
            SELECT url, title, visit_count, last_visit_time, typed_count
            FROM urls
            WHERE LOWER(url) LIKE ? OR LOWER(title) LIKE ?
            ORDER BY last_visit_time DESC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        )
        for row in cur.fetchall():
            results.append(
                {
                    "url": row["url"],
                    "title": row["title"],
                    "visit_count": row["visit_count"],
                    "typed_count": row["typed_count"],
                    "last_visit_time": _chrome_time_to_datetime(row["last_visit_time"]),
                }
            )
    except sqlite3.Error as exc:
        print(f"[ERROR] Database read failed: {exc}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    return results


def get_recent_history(limit: int = 100) -> List[Dict[str, Any]]:
    """Return the most recent history entries (by last_visit_time)."""
    tmp = _copy_history_db()
    if not tmp:
        return []

    results = []
    try:
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT url, title, visit_count, last_visit_time, typed_count
            FROM urls
            ORDER BY last_visit_time DESC
            LIMIT ?
            """,
            (limit,),
        )
        for row in cur.fetchall():
            results.append(
                {
                    "url": row["url"],
                    "title": row["title"],
                    "visit_count": row["visit_count"],
                    "typed_count": row["typed_count"],
                    "last_visit_time": _chrome_time_to_datetime(row["last_visit_time"]),
                }
            )
    except sqlite3.Error as exc:
        print(f"[ERROR] Database read failed: {exc}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    return results


def delete_history_by_pattern(query: str) -> int:
    """Mark history entries whose URL or title matches *query* as hidden.

    Returns the number of rows affected.
    WARNING: Requires Chrome to be closed or the database must be unlocked.
    """
    tmp = _copy_history_db()
    if not tmp:
        print("[ERROR] Cannot access history database.")
        return 0

    affected = 0
    try:
        conn = sqlite3.connect(tmp)
        cur = conn.cursor()
        pattern = f"%{query.lower()}%"
        cur.execute(
            """
            UPDATE urls
            SET hidden = 1
            WHERE LOWER(url) LIKE ? OR LOWER(title) LIKE ?
            """,
            (pattern, pattern),
        )
        affected = cur.rowcount
        conn.commit()
    except sqlite3.Error as exc:
        print(f"[ERROR] Database write failed: {exc}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

        # Copy the modified file back over the original (best-effort)
        try:
            shutil.copy2(tmp, HISTORY_DB)
        except Exception as exc:
            print(f"[WARN] Could not write changes back to Chrome history: {exc}")
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    return affected


def clear_all_history() -> bool:
    """Delete all history entries (marks everything as hidden).

    Returns True on success.
    WARNING: Requires Chrome to be closed or the database must be unlocked.
    """
    tmp = _copy_history_db()
    if not tmp:
        print("[ERROR] Cannot access history database.")
        return False

    try:
        conn = sqlite3.connect(tmp)
        cur = conn.cursor()
        cur.execute("UPDATE urls SET hidden = 1")
        conn.commit()
    except sqlite3.Error as exc:
        print(f"[ERROR] Database write failed: {exc}")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass

        try:
            shutil.copy2(tmp, HISTORY_DB)
        except Exception as exc:
            print(f"[WARN] Could not write changes back to Chrome history: {exc}")
            return False
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    return True


def print_history_table(entries: List[Dict[str, Any]], max_title_len: int = 60) -> None:
    """Pretty-print a list of history entries to the console."""
    if not entries:
        print("No entries found.")
        return

    print(f"{'#':<4} {'Last Visited':<26} {'Visits':<8} {'Title'}")
    print("-" * 90)
    for idx, entry in enumerate(entries, 1):
        title = entry.get("title") or entry.get("url") or "(no title)"
        if len(title) > max_title_len:
            title = title[: max_title_len - 3] + "..."
        last = entry.get("last_visit_time", "")[:19]
        visits = entry.get("visit_count", 0)
        print(f"{idx:<4} {last:<26} {visits:<8} {title}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Chrome History Search & Control")
    parser.add_argument("--search", "-s", help="Search query for URL/title")
    parser.add_argument("--recent", "-r", type=int, default=20, help="Show N most recent entries")
    parser.add_argument("--delete", "-d", help="Delete/hide entries matching this query")
    parser.add_argument("--clear", action="store_true", help="Clear/hide ALL history")
    args = parser.parse_args()

    if args.search:
        hits = search_history(args.search, limit=50)
        print(f"\nSearch results for '{args.search}': {len(hits)} entries")
        print_history_table(hits)
    elif args.delete:
        count = delete_history_by_pattern(args.delete)
        print(f"Marked {count} entries as hidden.")
    elif args.clear:
        confirm = input("Are you sure you want to hide ALL history? (yes/no): ")
        if confirm.lower() == "yes":
            ok = clear_all_history()
            print("History cleared." if ok else "Failed to clear history.")
        else:
            print("Cancelled.")
    else:
        entries = get_recent_history(args.recent)
        print(f"\nMost recent {len(entries)} history entries:")
        print_history_table(entries)
