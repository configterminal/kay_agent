"""简历终稿 artifact：预览 HTML + PDF 下载。"""

from src.resume.artifact import (
    get_resume_artifact,
    save_resume_artifact,
    render_resume_html,
    render_resume_pdf,
)

__all__ = [
    "get_resume_artifact",
    "save_resume_artifact",
    "render_resume_html",
    "render_resume_pdf",
]
