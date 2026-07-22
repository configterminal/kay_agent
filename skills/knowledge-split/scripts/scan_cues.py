#!/usr/bin/env python3
"""
扫描课程转写 .md，打印 cue 摘要信息。
用于知识切分前的预览——确认 cue 数量和总时长。
"""

import argparse
import json
import re
from pathlib import Path

CUE_HMS_RE = re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2})\]\s*(.*)$")
CUE_MS_RE = re.compile(r"^\[(\d{1,2}):(\d{2})\]\s*(.*)$")
LESSON_STEM_RE = re.compile(r"^(?P<section>\d{2}-\d{2}) (?P<title>.+)$")

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # f:/agent/


def parse_cues(filepath: Path) -> list[dict]:
    cues = []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = CUE_HMS_RE.match(line)
            if m:
                h, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
                sec = h * 3600 + mm * 60 + ss
            else:
                m = CUE_MS_RE.match(line)
                if not m:
                    continue
                mm, ss = int(m.group(1)), int(m.group(2))
                sec = mm * 60 + ss
            cues.append({"start_sec": sec, "text": m.group(4).strip() if m.lastindex >= 4 else ""})
    return cues


def format_duration(sec: int) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def scan_course(course_substr: str = "", chapter_substr: str = "") -> None:
    courses_dir = PROJECT_ROOT / "resources" / "courses"
    if not courses_dir.exists():
        print("课程目录不存在:", courses_dir)
        return

    md_files = []
    for course_dir in sorted(courses_dir.iterdir()):
        if not course_dir.is_dir():
            continue
        if course_substr and course_substr not in course_dir.name:
            continue
        for chapter_dir in sorted(course_dir.iterdir()):
            if not chapter_dir.is_dir():
                continue
            if chapter_substr and chapter_substr not in str(chapter_dir):
                continue
            for md in sorted(chapter_dir.glob("*.md")):
                stem_m = LESSON_STEM_RE.match(md.stem)
                if not stem_m:
                    continue
                has_kp = md.with_suffix(".knowledge.json").exists()
                md_files.append((md, has_kp, stem_m.group("section"), stem_m.group("title")))

    if not md_files:
        print("未找到匹配的 .md 文件")
        return

    total_cues = 0
    total_done = 0
    for md_path, has_kp, section, title in md_files:
        cues = parse_cues(md_path)
        n = len(cues)
        total_cues += n
        if has_kp:
            total_done += 1
        duration = cues[-1]["start_sec"] if cues else 0
        status = "✓" if has_kp else " "
        print(f"  [{status}] {section} {title}")
        print(f"         {n} cues, 时长 ~{format_duration(duration)}, 文件: {md_path.name}")

    print()
    print(f"共 {len(md_files)} 节, {total_cues} cues, 已完成 {total_done}, 待切分 {len(md_files) - total_done}")


def main():
    parser = argparse.ArgumentParser(description="扫描转写 md，打印 cue 摘要")
    parser.add_argument("--course", default="", help="课程名子串，如 RAG101")
    parser.add_argument("--chapter", default="", help="章节路径子串")
    args = parser.parse_args()
    scan_course(args.course, args.chapter)


if __name__ == "__main__":
    main()
