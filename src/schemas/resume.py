"""简历终稿 Schema（与 API ResumeDocument 对齐，供工具侧复用）。"""

from pydantic import BaseModel, Field


class ResumeContact(BaseModel):
    """联系信息"""
    name: str = ""
    phone: str = ""
    email: str = ""
    city: str = ""


class ResumeBlock(BaseModel):
    """经历/项目/技能块"""
    company: str = ""
    title: str = ""
    period: str = ""
    bullets: list[str] = Field(default_factory=list)
    skills_line: str = ""


class ResumeSection(BaseModel):
    """章节"""
    type: str = ""
    heading: str = ""
    blocks: list[ResumeBlock] = Field(default_factory=list)


class ResumeDocument(BaseModel):
    """投递用结构化简历"""
    mode: str = Field(default="fact", description="fact | target")
    role_id: str = ""
    role_title: str = ""
    title: str = ""
    contact: ResumeContact = Field(default_factory=ResumeContact)
    intention: str = ""
    sections: list[ResumeSection] = Field(default_factory=list)
    footer_note: str = ""
