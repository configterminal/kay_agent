"""
索引器 — 扫描合规转写 md，解析时间戳 cue，Embedding，写入 Milvus。

唯一文本源：带 [M:SS]/[H:MM:SS] 的 .md；同 stem .mp4 只写入 media_path。
父子文档：父=整节纯文本；子=时间/字数窗口块，带 start_sec/end_sec。

使用方式：
    from src.vectordb.indexer import build_index
    total = build_index()
    total = build_index(force=True)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from src.config import config
from src.llm.base import LLMProvider
from src.vectordb.schema import (
    get_client,
    ensure_collection,
    wipe_milvus_db,
    COLLECTION_NAME,
    VECTOR_DIM,
)

logger = logging.getLogger(__name__)

# ── 分块参数 ──────────────────────────────────────

CHUNK_SIZE = 400          # 纯文本约 400 字封块
CHUNK_TIME_SEC = 45       # 或时间跨度约 45 秒
CHUNK_OVERLAP_CUES = 3    # 块间重叠 cue 条数

COURSE_DIR_RE = re.compile(
    r"^(?P<course_id>[A-Za-z0-9][A-Za-z0-9-]*) (?P<course_title>.+)$"
)
CHAPTER_DIR_RE = re.compile(r"^(?P<cc>\d{2}) (?P<chapter_title>.+)$")
LESSON_STEM_RE = re.compile(r"^(?P<section>\d{2}-\d{2}) (?P<title>.+)$")
CUE_HMS_RE = re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2})\]\s*(.*)$")
CUE_MS_RE = re.compile(r"^\[(\d{1,2}):(\d{2})\]\s*(.*)$")


def parse_timestamped_md(text: str) -> list[dict]:
    """
    从转写 md 解析 cue 列表。
    返回 [{start_sec, text}, ...]；忽略标题与空行。
    """
    cues: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = CUE_HMS_RE.match(line)
        if m:
            h, mm, ss, body = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4).strip()
            sec = h * 3600 + mm * 60 + ss
        else:
            m = CUE_MS_RE.match(line)
            if not m:
                continue
            mm, ss, body = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            sec = mm * 60 + ss
        if not body:
            continue
        cues.append({"start_sec": sec, "text": body})
    return cues


def _cues_to_plain(cues: list[dict]) -> str:
    """cue 列表拼成去时间戳纯文本。"""
    return "\n".join(c["text"] for c in cues)


def split_cues_into_chunks(cues: list[dict]) -> list[dict]:
    """
    按字数/时间窗口切块。

    窗口增长至 ≥CHUNK_SIZE 字或时间跨度 ≥CHUNK_TIME_SEC（含触顶那条 cue）。
    下一块尽量重叠 CHUNK_OVERLAP_CUES 条；若重叠会导致不前进则从下一条起。

    返回 [{content, start_sec, end_sec}, ...]
    """
    if not cues:
        return []

    chunks: list[dict] = []
    i = 0
    n = len(cues)

    while i < n:
        end = i  # inclusive
        while end + 1 < n:
            nxt = end + 1
            plain = "\n".join(c["text"] for c in cues[i : nxt + 1])
            span = cues[nxt]["start_sec"] - cues[i]["start_sec"]
            end = nxt
            if len(plain) >= CHUNK_SIZE or span >= CHUNK_TIME_SEC:
                break

        content = "\n".join(c["text"] for c in cues[i : end + 1]).strip()
        if content:
            chunks.append({
                "content": content,
                "start_sec": cues[i]["start_sec"],
                "end_sec": cues[end]["start_sec"],
            })

        if end >= n - 1:
            break
        # 重叠前进；保证 i 严格增大，避免单 cue 碎块
        next_i = end + 1 - CHUNK_OVERLAP_CUES
        i = end + 1 if next_i <= i else next_i

    return chunks


def _build_knowledge_point_chunks(
    info: dict, cues: list[dict], parent_id: str, json_path: Path
) -> list[dict]:
    """从 .knowledge.json 构建知识点子文档列表"""
    import json as _json

    try:
        data = _json.loads(json_path.read_text(encoding="utf-8"))
        kps = data.get("knowledge_points", [])
    except Exception:
        logger.warning("读取 .knowledge.json 失败，fallback 规则窗口: %s", json_path)
        return _build_rule_chunks(info, cues, parent_id)

    if not kps:
        return _build_rule_chunks(info, cues, parent_id)

    child_docs = []
    for kp in kps:
        kp_idx = int(kp.get("kp_index", 0))
        child_id = f"{info['course_id']}_{info['section']}_kp{kp_idx}"

        # content: 该知识点覆盖的 cue 文本拼接
        cue_start = int(kp.get("cue_start_idx", 0))
        cue_end = int(kp.get("cue_end_idx", 0))
        cue_start = max(0, min(cue_start, len(cues) - 1))
        cue_end = max(cue_start, min(cue_end, len(cues) - 1))
        content = "\n".join(c["text"] for c in cues[cue_start : cue_end + 1])

        # search_text: 精炼的检索锚点
        kp_title = str(kp.get("kp_title", ""))[:256]
        kp_summary = str(kp.get("kp_summary", ""))[:1024]
        key_points_list = kp.get("key_points", [])
        if isinstance(key_points_list, list):
            key_points_str = ", ".join(str(p) for p in key_points_list)[:2048]
        else:
            key_points_str = str(key_points_list)[:2048]
        search_text = (kp_title + "\n" + kp_summary + "\n" + key_points_str).strip()

        child_docs.append({
            "id": child_id,
            "content": content[:65535],
            "embedding": [],  # 批次 embedding，下面统一处理
            "parent_id": parent_id,
            "course_id": info["course_id"],
            "chapter": info["chapter"],
            "section": info["section"],
            "title": info["title"],
            "file_type": info["file_type"],
            "chunk_index": kp_idx,
            "tags": info["tags"],
            "start_sec": int(kp.get("start_sec", -1)),
            "end_sec": int(kp.get("end_sec", -1)),
            "media_path": info["media_path"],
            "kp_title": kp_title,
            "kp_summary": kp_summary,
            "kp_index": kp_idx,
            "key_points": key_points_str,
            "_search_text": search_text,
        })

    # 批量 embedding（对 search_text）
    texts = [d["_search_text"] for d in child_docs]
    provider = LLMProvider.create()
    embeddings = provider.embed(texts) if texts else []
    for i, emb in enumerate(embeddings):
        child_docs[i]["embedding"] = emb
        del child_docs[i]["_search_text"]
    # 没拿到 embedding 的用零向量占位
    zero_vec = [0.0] * VECTOR_DIM
    for d in child_docs:
        if not d.get("embedding"):
            d["embedding"] = zero_vec
        d.pop("_search_text", None)

    return child_docs


def _build_rule_chunks(
    info: dict, cues: list[dict], parent_id: str, provider=None
) -> list[dict]:
    """Fallback：现有规则窗口切块，不带知识点字段"""
    if provider is None:
        provider = LLMProvider.create()
    chunks = split_cues_into_chunks(cues)
    texts = [c["content"][:65535] for c in chunks]
    embeddings = provider.embed(texts) if texts else []
    child_docs = []
    for i, chunk in enumerate(chunks):
        child_id = f"{info['course_id']}_{info['section']}_{i}"
        child_docs.append({
            "id": child_id,
            "content": texts[i],
            "embedding": embeddings[i] if i < len(embeddings) else embeddings[0] if embeddings else [],
            "parent_id": parent_id,
            "course_id": info["course_id"],
            "chapter": info["chapter"],
            "section": info["section"],
            "title": info["title"],
            "file_type": info["file_type"],
            "chunk_index": i,
            "tags": info["tags"],
            "start_sec": int(chunk["start_sec"]),
            "end_sec": int(chunk["end_sec"]),
            "media_path": info["media_path"],
            "kp_title": "",
            "kp_summary": "",
            "kp_index": -1,
            "key_points": "",
        })
    return child_docs


def _scan_course_files(resources_dir: Path) -> list[dict]:
    """
    扫描合规 md，返回待索引条目列表。
    """
    courses_dir = resources_dir / "courses"
    if not courses_dir.exists():
        logger.warning("课程目录不存在: %s", courses_dir)
        return []

    files_to_index: list[dict] = []

    for course_dir in sorted(courses_dir.iterdir()):
        if not course_dir.is_dir():
            continue

        index_file = course_dir / "index.json"
        if not index_file.exists():
            logger.warning("缺少 index.json，跳过: %s", course_dir.name)
            continue

        course_info = json.loads(index_file.read_text(encoding="utf-8"))
        course_id = course_info["course_id"]
        course_title = course_info.get("title", "")

        dir_m = COURSE_DIR_RE.match(course_dir.name)
        if not dir_m or dir_m.group("course_id") != course_id:
            logger.warning(
                "课目录名不合规或不匹配 index.json，跳过: %s", course_dir.name
            )
            continue

        for chapter_dir in sorted(course_dir.iterdir()):
            if not chapter_dir.is_dir():
                continue
            ch_m = CHAPTER_DIR_RE.match(chapter_dir.name)
            if not ch_m:
                logger.warning("章目录不合规，跳过: %s", chapter_dir.name)
                continue
            cc = ch_m.group("cc")

            module_file = chapter_dir / "module.json"
            chapter_tags = ""
            if module_file.exists():
                module_info = json.loads(module_file.read_text(encoding="utf-8"))
                chapter_tags = ",".join(module_info.get("tags", []))

            for md_path in sorted(chapter_dir.glob("*.md")):
                stem_m = LESSON_STEM_RE.match(md_path.stem)
                if not stem_m:
                    logger.warning("节文件名不合规，跳过: %s", md_path.name)
                    continue
                section = stem_m.group("section")
                if not section.startswith(cc + "-"):
                    logger.warning(
                        "节号与章号不一致，跳过: %s (章 %s)", md_path.name, cc
                    )
                    continue

                mp4_path = md_path.with_suffix(".mp4")
                media_path = ""
                if mp4_path.is_file():
                    try:
                        media_path = str(
                            mp4_path.relative_to(resources_dir)
                        ).replace("\\", "/")
                    except ValueError:
                        media_path = str(mp4_path)

                files_to_index.append({
                    "course_id": course_id,
                    "course_title": course_title,
                    "chapter": chapter_dir.name,
                    "section": section,
                    "title": stem_m.group("title"),
                    "file_path": md_path,
                    "file_type": "md",
                    "tags": chapter_tags,
                    "media_path": media_path,
                })

    return files_to_index


def build_index(
    resources_dir: Path | None = None,
    force: bool = False,
) -> int:
    """
    构建课程内容索引。

    force=True：删除 Collection 后全量重建。
    force=False：跳过已存在的 (course_id, section) 子文档。
    """
    if resources_dir is None:
        resources_dir = config.resources_dir

    if force:
        wipe_milvus_db()

    ensure_collection()
    client = get_client()
    provider = LLMProvider.create()

    files = _scan_course_files(resources_dir)
    if not files:
        logger.warning("未找到任何合规课程 md")
        return 0

    indexed_sections: set[str] = set()
    if not force:
        try:
            results = client.query(
                collection_name=COLLECTION_NAME,
                filter="chunk_index >= 0",
                output_fields=["section", "course_id"],
                limit=16384,
            )
            indexed_sections = {
                f"{r.get('course_id', '')}|{r.get('section', '')}"
                for r in results
            }
        except Exception:
            pass

    total_chunks = 0
    zero_vec = [0.0] * VECTOR_DIM

    for info in files:
        section_key = f"{info['course_id']}|{info['section']}"
        if not force and section_key in indexed_sections:
            logger.debug("跳过已索引: %s", section_key)
            continue

        raw = info["file_path"].read_text(encoding="utf-8")
        cues = parse_timestamped_md(raw)
        if not cues:
            logger.warning("无有效 cue，跳过: %s", info["file_path"])
            continue

        plain_full = _cues_to_plain(cues)
        parent_id = f"{info['course_id']}_{info['section']}_full"

        parent_data = {
            "id": parent_id,
            "content": plain_full[:65535],
            "embedding": zero_vec,
            "parent_id": "",
            "course_id": info["course_id"],
            "chapter": info["chapter"],
            "section": info["section"],
            "title": info["title"],
            "file_type": info["file_type"],
            "chunk_index": -1,
            "tags": info["tags"],
            "start_sec": -1,
            "end_sec": -1,
            "media_path": info["media_path"],
            "kp_title": "",
            "kp_summary": "",
            "kp_index": -1,
            "key_points": "",
        }
        client.insert(collection_name=COLLECTION_NAME, data=[parent_data])

        # 检查 .knowledge.json；存在则用知识点模式，否则 fallback 规则窗口
        kp_json_path = info["file_path"].with_suffix(".knowledge.json")
        if kp_json_path.exists():
            child_docs = _build_knowledge_point_chunks(
                info, cues, parent_id, kp_json_path
            )
        else:
            logger.debug("无 .knowledge.json，fallback 规则窗口: %s", info["section"])
            child_docs = _build_rule_chunks(info, cues, parent_id, provider)

        if child_docs:
            client.insert(collection_name=COLLECTION_NAME, data=child_docs)
            total_chunks += len(child_docs)
            logger.info(
                "已索引: %s/%s (%d 块)",
                info["chapter"], info["title"], len(child_docs),
            )

    # 索引变更后清空内存 BM25，下次 warmup/search 会重新加载 payload
    from src.vectordb.hybrid_search import reset_bm25
    reset_bm25()

    logger.info("索引完成，共 %d 块", total_chunks)
    return total_chunks
