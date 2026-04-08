"""
Purge stale entries from nodes/removedNodes JSON files.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from helpers.data_utils import load_data_from_json, save_data_to_json

logger = logging.getLogger(__name__)

STALE_NODES_PURGE_SECTION = "stale_nodes_purge"


def stale_after_days_from_config(config, fallback: int = 30) -> int:
    """
    Read the purge threshold from ``[stale_nodes_purge]``.

    Accepts ``stale_after_days`` or ``days`` (``stale_after_days`` wins if both are set).
    """
    sec = STALE_NODES_PURGE_SECTION
    if not config.has_section(sec):
        return max(1, fallback)
    for key in ("stale_after_days", "days"):
        if config.has_option(sec, key):
            try:
                return max(1, config.getint(sec, key))
            except (ValueError, TypeError):
                return max(1, fallback)
    return max(1, fallback)


def data_files() -> list[str]:
    return ["nodes.json", "removedNodes.json"]


def _data_root(data_dir: str | None) -> str:
    return os.path.abspath(data_dir) if data_dir else os.getcwd()


def _last_seen_raw(node: dict[str, Any]) -> Any:
    if node.get("last_seen") is not None:
        return node.get("last_seen")
    return node.get("last_heard")


def _is_stale(node: dict[str, Any], now: datetime, min_age: timedelta) -> bool:
    raw = _last_seen_raw(node)
    if raw is None or raw == "":
        return False
    try:
        ls = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ls.tzinfo is None:
            ls = ls.replace(tzinfo=now.tzinfo)
        return (now - ls) >= min_age
    except (ValueError, TypeError, OSError):
        return False


def purge_stale_nodes(
    *,
    stale_after_days: int = 30,
    data_dir: str | None = None,
    quiet: bool = False,
) -> list[tuple[str, int, int]]:
    """
    Remove entries with last_seen (or last_heard) at least stale_after_days ago from each
    data file. Entries without a parseable last_seen/last_heard are kept.

    Returns:
        List of (absolute path, removed_count, kept_count).
    """
    min_age = timedelta(days=stale_after_days)
    now = datetime.now().astimezone()
    root = _data_root(data_dir)

    abs_paths: set[str] = set()
    for nf in data_files():
        abs_paths.add(os.path.normpath(os.path.join(root, nf)))

    results: list[tuple[str, int, int]] = []
    for filepath in sorted(abs_paths):
        if not os.path.isfile(filepath):
            continue

        basename = os.path.basename(filepath)
        dirpath = os.path.dirname(filepath) or root

        data = load_data_from_json(basename, data_dir=dirpath)
        if data is None:
            continue
        nodes = data.get("data", [])
        if not isinstance(nodes, list):
            logger.warning("Skipping %s: invalid data format", filepath)
            continue

        kept: list[Any] = []
        removed = 0
        for node in nodes:
            if isinstance(node, dict) and _is_stale(node, now, min_age):
                removed += 1
            else:
                kept.append(node)

        if removed:
            ok = save_data_to_json(
                kept,
                filename=basename,
                data_dir=dirpath,
                quiet=quiet,
            )
            if ok:
                logger.info(
                    "Purged %d stale node(s) from %s (%d kept, threshold %d days)",
                    removed,
                    filepath,
                    len(kept),
                    stale_after_days,
                )
            else:
                logger.error("Failed to save after purge: %s", filepath)

        results.append((filepath, removed, len(kept)))

    return results
