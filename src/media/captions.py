"""
课程字幕 — 从合规转写 .md 动态生成 WebVTT。

mp4 与同 stem .md 一一对应；供 Plyr <track> 使用。
"""

from __future__ import annotations

from pathlib import Path

from src.config import config
from src.vectordb.indexer import parse_timestamped_md


def _sec_to_vtt(sec: float) -> str:
    """秒 → WebVTT 时间戳 HH:MM:SS.mmm"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _escape_vtt(text: str) -> str:
    """VTT 文本转义。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def cues_to_vtt(cues: list[dict], default_duration: float = 8.0) -> str:
    """cue 列表 → WebVTT 文本。"""
    if not cues:
        return "WEBVTT\n\n"
    lines = ["WEBVTT", ""]
    for i, cue in enumerate(cues):
        start = float(cue["start_sec"])
        if i + 1 < len(cues):
            end = float(cues[i + 1]["start_sec"])
            if end <= start:
                end = start + default_duration
        else:
            end = start + default_duration
        body = _escape_vtt(str(cue.get("text") or "").strip())
        if not body:
            continue
        lines.append(f"{_sec_to_vtt(start)} --> {_sec_to_vtt(end)}")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def resolve_md_for_media(media_rel: str) -> Path | None:
    """相对 resources/ 的 mp4 路径 → 同 stem .md 绝对路径。"""
    rel = (media_rel or "").replace("\\", "/").lstrip("/")
    if not rel.lower().endswith(".mp4"):
        return None
    root = config.resources_dir.resolve()
    mp4 = (root / rel).resolve()
    try:
        mp4.relative_to(root)
    except ValueError:
        return None
    md = mp4.with_suffix(".md")
    return md if md.is_file() else None


def build_vtt_for_media(media_rel: str) -> str | None:
    """按 mp4 相对路径生成 VTT；无转写则 None。"""
    md_path = resolve_md_for_media(media_rel)
    if not md_path:
        return None
    text = md_path.read_text(encoding="utf-8")
    cues = parse_timestamped_md(text)
    if not cues:
        return None
    return cues_to_vtt(cues)
