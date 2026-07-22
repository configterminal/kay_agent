"""
简历 artifact 内存存储 + HTML/PDF 渲染。

MVP：进程内 dict；PDF 用 ReportLab + 微软雅黑/黑体。
"""

from __future__ import annotations

import html
import io
import logging
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# artifact_id → ResumeDocument dict
_STORE: dict[str, dict[str, Any]] = {}
_MAX_STORE = 64

_FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
]


def save_resume_artifact(doc: dict[str, Any]) -> str:
    """保存文档，返回 artifact_id。"""
    aid = str(uuid.uuid4())
    _STORE[aid] = dict(doc or {})
    # 简单 LRU：超额删最早 key
    while len(_STORE) > _MAX_STORE:
        oldest = next(iter(_STORE))
        _STORE.pop(oldest, None)
    return aid


def get_resume_artifact(artifact_id: str) -> dict[str, Any] | None:
    """按 id 取文档。"""
    return _STORE.get((artifact_id or "").strip())


def _escape(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def render_resume_html(doc: dict[str, Any]) -> str:
    """同源数据 → A4 风格 HTML 预览。"""
    mode = str(doc.get("mode") or "fact")
    role_title = _escape(doc.get("role_title") or doc.get("role_id") or "")
    banner = ""
    if mode == "target":
        banner = (
            '<div class="banner warn">目标蓝图 · 完成对应学习前请勿当作已有任职经历投递</div>'
        )
    contact = doc.get("contact") or {}
    name = _escape(contact.get("name") or "（姓名）")
    contact_line = " · ".join(
        _escape(contact.get(k))
        for k in ("phone", "email", "city")
        if contact.get(k)
    )
    intention = _escape(doc.get("intention") or "")
    footer = _escape(doc.get("footer_note") or "")

    sections_html: list[str] = []
    for sec in doc.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        heading = _escape(sec.get("heading") or sec.get("type") or "")
        blocks_html: list[str] = []
        for block in sec.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            head_parts = [
                _escape(block.get(k))
                for k in ("company", "title", "period")
                if block.get(k)
            ]
            if head_parts:
                blocks_html.append(
                    f'<div class="block-head">{" · ".join(head_parts)}</div>'
                )
            if block.get("skills_line"):
                blocks_html.append(
                    f'<p class="skills">{_escape(block.get("skills_line"))}</p>'
                )
            bullets = block.get("bullets") or []
            if bullets:
                items = "".join(f"<li>{_escape(b)}</li>" for b in bullets if b)
                blocks_html.append(f"<ul>{items}</ul>")
        if heading or blocks_html:
            sections_html.append(
                f'<section><h2>{heading}</h2>{"".join(blocks_html)}</section>'
            )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>简历预览</title>
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  body {{
    font-family: "Microsoft YaHei", "SimHei", "PingFang SC", sans-serif;
    font-size: 11pt; line-height: 1.45; color: #1a1a1a;
    max-width: 210mm; margin: 0 auto; padding: 16px 20px;
    background: #f0f0f0;
  }}
  .page {{
    background: #fff; min-height: 277mm; padding: 18mm 16mm;
    box-shadow: 0 2px 12px rgba(0,0,0,.12);
  }}
  .banner {{
    font-size: 10pt; padding: 6px 10px; margin-bottom: 12px;
    border: 1px solid #c9a227; background: #fff8e1; color: #6d5a00;
  }}
  h1 {{ font-size: 18pt; margin: 0 0 4px; font-weight: 700; }}
  .meta {{ font-size: 10pt; color: #444; margin-bottom: 8px; }}
  .intention {{ font-size: 11pt; margin: 0 0 14px; }}
  .role-tag {{ font-size: 9pt; color: #666; margin-bottom: 12px; }}
  h2 {{
    font-size: 12pt; margin: 14px 0 6px; padding-bottom: 3px;
    border-bottom: 1px solid #333;
  }}
  .block-head {{ font-weight: 600; margin: 6px 0 2px; }}
  ul {{ margin: 2px 0 8px 1.2em; padding: 0; }}
  li {{ margin: 2px 0; }}
  .skills {{ margin: 0 0 6px; }}
  .footer {{ margin-top: 18px; font-size: 9pt; color: #777; }}
</style>
</head>
<body>
<div class="page">
  {banner}
  <h1>{name}</h1>
  <div class="meta">{contact_line}</div>
  <div class="role-tag">对照方向：{role_title} · 模式：{_escape(mode)}</div>
  {f'<p class="intention"><strong>求职意向：</strong>{intention}</p>' if intention else ''}
  {"".join(sections_html)}
  {f'<p class="footer">{footer}</p>' if footer else ''}
</div>
</body>
</html>"""


def _resolve_font() -> tuple[str, str]:
    """返回 (reportlab 注册名, 字体路径)。"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for path in _FONT_CANDIDATES:
        if not path.is_file():
            continue
        name = "ResumeCN"
        try:
            # ttc 可能需 subfontIndex；优先 ttf
            if path.suffix.lower() == ".ttf":
                pdfmetrics.registerFont(TTFont(name, str(path)))
                return name, str(path)
            pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=0))
            return name, str(path)
        except Exception as e:
            logger.warning("注册字体失败 %s: %s", path, e)
            continue
    return "Helvetica", ""


def render_resume_pdf(doc: dict[str, Any]) -> bytes:
    """同源数据 → PDF bytes。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    font_name, _ = _resolve_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    left = 16 * mm
    right = width - 16 * mm
    y = height - 18 * mm
    line_h = 5.2 * mm

    def draw_wrapped(text: str, size: float = 10, bold: bool = False, indent: float = 0):
        nonlocal y
        from reportlab.pdfbase.pdfmetrics import stringWidth

        c.setFont(font_name, size)
        max_w = right - left - indent
        s = text or ""
        while s:
            if y < 18 * mm:
                c.showPage()
                c.setFont(font_name, size)
                y = height - 18 * mm
            # 逐字估宽（中文）
            cut = len(s)
            for i in range(1, len(s) + 1):
                if stringWidth(s[:i], font_name, size) > max_w:
                    cut = max(1, i - 1)
                    break
            c.drawString(left + indent, y, s[:cut])
            y -= line_h
            s = s[cut:]

    mode = str(doc.get("mode") or "fact")
    if mode == "target":
        c.setFillColorRGB(0.42, 0.35, 0.0)
        draw_wrapped("【目标蓝图】完成对应学习前请勿当作已有任职经历投递", size=9)
        c.setFillColorRGB(0, 0, 0)
        y -= 2 * mm

    contact = doc.get("contact") or {}
    name = str(contact.get("name") or "（姓名）")
    draw_wrapped(name, size=16)
    contact_line = " · ".join(
        str(contact.get(k))
        for k in ("phone", "email", "city")
        if contact.get(k)
    )
    if contact_line:
        draw_wrapped(contact_line, size=9)
    role_title = str(doc.get("role_title") or doc.get("role_id") or "")
    draw_wrapped(f"对照方向：{role_title} · 模式：{mode}", size=9)
    if doc.get("intention"):
        draw_wrapped(f"求职意向：{doc['intention']}", size=10)
    y -= 3 * mm

    for sec in doc.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading") or sec.get("type") or "")
        if heading:
            y -= 2 * mm
            draw_wrapped(heading, size=12)
            c.setStrokeColorRGB(0.2, 0.2, 0.2)
            c.line(left, y + 3.5 * mm, right, y + 3.5 * mm)
        for block in sec.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            head_parts = [
                str(block.get(k))
                for k in ("company", "title", "period")
                if block.get(k)
            ]
            if head_parts:
                draw_wrapped(" · ".join(head_parts), size=10)
            if block.get("skills_line"):
                draw_wrapped(str(block["skills_line"]), size=9)
            for b in block.get("bullets") or []:
                if b:
                    draw_wrapped(f"· {b}", size=9, indent=3 * mm)

    footer = str(doc.get("footer_note") or "")
    if footer:
        y -= 4 * mm
        draw_wrapped(footer, size=8)

    c.save()
    return buf.getvalue()
