"""
Purge nodes whose last_seen is older than a threshold from regional nodes_*.json files.
"""

from __future__ import annotations

import glob
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


def _is_regional_nodes_basename(name: str) -> bool:
    base = os.path.basename(name)
    return base.startswith("nodes_") and base.endswith(".json")


def regional_nodes_files_from_config(config) -> list[str]:
    """Unique nodes_file paths from numeric category sections that use regional nodes_*.json."""
    seen: set[str] = set()
    out: list[str] = []
    for section in config.sections():
        try:
            int(section)
        except (ValueError, TypeError):
            continue
        if not config.has_option(section, "nodes_file"):
            continue
        nf = config.get(section, "nodes_file", fallback="nodes.json").strip()
        if not nf or not _is_regional_nodes_basename(nf):
            continue
        if nf not in seen:
            seen.add(nf)
            out.append(nf)
    return out


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


def purge_stale_nodes_from_regional_files(
    config,
    *,
    stale_after_days: int = 30,
    data_dir: str | None = None,
    quiet: bool = False,
    use_glob: bool = True,
) -> list[tuple[str, int, int]]:
    """
    Remove nodes with last_seen (or last_heard) at least stale_after_days ago from each
    regional file. Nodes without a parseable last_seen/last_heard are kept.

    Files are discovered from config (per-category nodes_file) and optionally by globbing
    nodes_*.json under the data root.

    Returns:
        List of (absolute path, removed_count, kept_count) for each file processed.
    """
    min_age = timedelta(days=stale_after_days)
    now = datetime.now().astimezone()
    root = _data_root(data_dir)

    abs_paths: set[str] = set()
    for nf in regional_nodes_files_from_config(config):
        abs_paths.add(os.path.normpath(os.path.join(root, nf)))

    if use_glob:
        for p in glob.glob(os.path.join(root, "nodes_*.json")):
            if _is_regional_nodes_basename(p):
                abs_paths.add(os.path.normpath(p))

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
