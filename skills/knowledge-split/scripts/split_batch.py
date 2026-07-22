#!/usr/bin/env python3
"""
批量知识切分脚本。
对指定的课程 .md 逐节调用 LLM，产出 .knowledge.json。

用法：
  python skills/knowledge-split/scripts/split_batch.py --course RAG101 --dry-run
  python skills/knowledge-split/scripts/split_batch.py --course CAREER201
  python skills/knowledge-split/scripts/split_batch.py --chapter "resources/courses/.../10 章名"
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("split_batch")

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # f:/agent/

CUE_HMS_RE = re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2})\]\s*(.*)$")
CUE_MS_RE = re.compile(r"^\[(\d{1,2}):(\d{2})\]\s*(.*)$")
LESSON_STEM_RE = re.compile(r"^(?P<section>\d{2}-\d{2}) (?P<title>.+)$")
CHAPTER_DIR_RE = re.compile(r"^(?P<cc>\d{2}) (?P<chapter_title>.+)$")

# 从 .env 加载 API Key
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Prompt 模板
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prompts"))
from split_prompt import SYSTEM_PROMPT, USER_MESSAGE_TEMPLATE


def parse_cues(filepath: Path) -> list[dict]:
    """解析转写 md，返回 [{idx, start_sec, text}]"""
    cues = []
    with open(filepath, encoding="utf-8") as f:
        idx = 0
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = CUE_HMS_RE.match(line)
            if m:
                h, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
                sec = h * 3600 + mm * 60 + ss
                body = m.group(4).strip()
            else:
                m = CUE_MS_RE.match(line)
                if not m:
                    continue
                mm, ss = int(m.group(1)), int(m.group(2))
                sec = mm * 60 + ss
                body = m.group(3).strip()
            if not body:
                continue
            cues.append({"idx": idx, "start_sec": sec, "text": body})
            idx += 1
    return cues


def format_cues_text(cues: list[dict]) -> str:
    """格式化 cue 列表为 LLM 输入文本"""
    lines = []
    for c in cues:
        m, s = divmod(c["start_sec"], 60)
        lines.append(f"[{c['idx']}] [{m}:{s:02d}] {c['text']}")
    return "\n".join(lines)


def build_user_message(cues: list[dict], course_title: str, chapter: str,
                       section: str, section_title: str) -> str:
    return USER_MESSAGE_TEMPLATE.format(
        course_title=course_title,
        chapter=chapter,
        section=section,
        section_title=section_title,
        cues_text=format_cues_text(cues),
        max_idx=len(cues) - 1,
    )


def validate_knowledge_points(kps: list[dict], max_idx: int) -> bool:
    """校验 LLM 返回的知识点列表"""
    if not kps:
        return False
    prev_end = -1
    for i, kp in enumerate(kps):
        if kp.get("kp_index") != i:
            logger.warning("  校验失败: kp_index 不连续，期望 %d 实际 %s", i, kp.get("kp_index"))
            return False
        start = kp.get("cue_start_idx")
        end = kp.get("cue_end_idx")
        if not isinstance(start, int) or not isinstance(end, int):
            logger.warning("  校验失败: cue_start_idx/cue_end_idx 不是 int")
            return False
        if start < 0 or end > max_idx or start > end:
            logger.warning("  校验失败: 边界越界 start=%d end=%d max=%d", start, end, max_idx)
            return False
        if start != prev_end + 1:
            logger.warning("  校验失败: 不连续，期望 %d 实际 %d", prev_end + 1, start)
            return False
        prev_end = end
    if prev_end != max_idx:
        logger.warning("  校验失败: 未覆盖全部 cue，末位 %d，max=%d", prev_end, max_idx)
        return False
    return True


def split_one(llm: ChatOpenAI, md_path: Path, course_title: str, chapter: str,
              section: str, section_title: str) -> bool:
    """处理一节"""
    cues = parse_cues(md_path)
    if not cues:
        logger.info("  跳过: 无有效 cue")
        return False

    user_msg = build_user_message(cues, course_title, chapter, section, section_title)

    for attempt in range(2):
        try:
            response = llm.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ])
            text = response.content.strip()
            # 去掉可能的 markdown 代码块
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3]
            kps = json.loads(text)
            if not isinstance(kps, list):
                raise ValueError("返回不是数组")

            # 校验
            if not validate_knowledge_points(kps, len(cues) - 1):
                if attempt == 0:
                    logger.info("  第 1 次校验失败，重试...")
                    continue
                return False

            # 补全 start_sec / end_sec
            for kp in kps:
                kp["start_sec"] = cues[kp["cue_start_idx"]]["start_sec"]
                kp["end_sec"] = cues[kp["cue_end_idx"]]["start_sec"]

            # 写入 .knowledge.json
            output = {
                "section": section,
                "title": section_title,
                "course_id": course_title.split()[0] if course_title else "",
                "total_cues": len(cues),
                "knowledge_points": kps,
            }
            json_path = md_path.with_suffix(".knowledge.json")
            json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("  ✓ %d 个知识点 → %s", len(kps), json_path.name)
            return True

        except Exception as e:
            logger.warning("  第 %d 次失败: %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(1)
    return False


def scan_md_files(course_substr: str = "", chapter_substr: str = "") -> list[dict]:
    """扫描 .md 文件，返回待切分列表"""
    courses_dir = PROJECT_ROOT / "resources" / "courses"
    items = []
    for course_dir in sorted(courses_dir.iterdir()):
        if not course_dir.is_dir():
            continue
        if course_substr and course_substr not in course_dir.name:
            continue
        # 从目录名取课程标题（去掉 course_id 前缀）
        course_name = course_dir.name
        course_title = course_name

        index_file = course_dir / "index.json"
        if index_file.exists():
            info = json.loads(index_file.read_text(encoding="utf-8"))
            course_title = info.get("title", course_name)

        for chapter_dir in sorted(course_dir.iterdir()):
            if not chapter_dir.is_dir():
                continue
            if chapter_substr and chapter_substr not in str(chapter_dir):
                continue
            ch_m = CHAPTER_DIR_RE.match(chapter_dir.name)
            chapter_label = chapter_dir.name
            if ch_m:
                chapter_label = f"第{ch_m.group('cc')}章"

            for md_path in sorted(chapter_dir.glob("*.md")):
                stem_m = LESSON_STEM_RE.match(md_path.stem)
                if not stem_m:
                    continue
                # 跳过已有 .knowledge.json 的
                if md_path.with_suffix(".knowledge.json").exists():
                    continue
                items.append({
                    "md_path": md_path,
                    "course_title": course_title,
                    "chapter": chapter_label,
                    "section": stem_m.group("section"),
                    "section_title": stem_m.group("title"),
                })
    return items


def main():
    parser = argparse.ArgumentParser(description="批量知识切分")
    parser.add_argument("--course", default="", help="课程名子串")
    parser.add_argument("--chapter", default="", help="章节路径子串")
    parser.add_argument("--dry-run", action="store_true", help="只预览不执行")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 节（调试用）")
    args = parser.parse_args()

    items = scan_md_files(args.course, args.chapter)
    if not items:
        logger.info("未找到待切分文件（或已全部完成）")
        return

    logger.info("待切分: %d 节", len(items))
    if args.dry_run:
        for it in items:
            cues = parse_cues(it["md_path"])
            logger.info("  %s %s (%d cues)", it["section"], it["section_title"], len(cues))
        return

    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com/v1",
        temperature=0.3,
    )

    count = 0
    success = 0
    for it in items:
        if args.limit and count >= args.limit:
            break
        md = it["md_path"]
        logger.info("[%d/%d] %s %s", count + 1, len(items), it["section"], it["section_title"])
        ok = split_one(llm, md, it["course_title"], it["chapter"],
                       it["section"], it["section_title"])
        if ok:
            success += 1
        count += 1
        # API rate limit: 短暂停顿
        time.sleep(0.3)

    logger.info("完成: %d/%d 成功", success, count)


if __name__ == "__main__":
    main()
