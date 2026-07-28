"""API 请求/响应 Pydantic 模型"""

from pydantic import BaseModel, Field


# ── 结构化选项（会话级 pending）─────────────────────

class ChatOption(BaseModel):
    """可点 / 可手输 id 的选项"""
    id: int = Field(description="选项编号，与学员手输 id 对应")
    text: str = Field(description="选项展示文案")


# ── POST /api/chat/ ────────────────────────────────

class ChatRequest(BaseModel):
    """聊天请求"""
    message: str = Field(description="学员消息")
    student_id: int = Field(default=1, description="学员 ID")
    thread_id: str | None = Field(
        default=None,
        description="会话 ID（与 Checkpointer 共用；每会话独立状态）",
    )
    selected_option_id: int | None = Field(
        default=None,
        description="前端点击选项时传入；与手输 id 等价",
    )
    voice_mode: bool = Field(
        default=False,
        description="语音模式：开启后 LLM 输出适合 TTS 朗读的自然口语",
    )


class Citation(BaseModel):
    """课程来源跳转（来自检索工具，非 LLM 编造）"""
    source: str = Field(default="", description="展示文案，可含 @M:SS")
    score: float = Field(default=0, description="相关性得分")
    section: str = Field(default="", description="节号如 02-03")
    title: str = Field(default="", description="课时标题")
    start_sec: int = Field(default=-1, description="跳转秒；<0 不可 seek")
    end_sec: int = Field(default=-1, description="块结束秒")
    media_path: str = Field(default="", description="相对 resources/ 的 mp4")
    media_url: str = Field(default="", description="供 <video src> 的 /media/...")
    captions_url: str = Field(default="", description="WebVTT 字幕 /captions/...")
    kp_title: str = Field(default="", description="知识点标题（知识切分后可用）")
    kp_summary: str = Field(default="", description="知识点摘要")
    kp_index: int = Field(default=-1, description="节内知识点序号；无则 -1")


class ResumeContact(BaseModel):
    """简历联系信息（有则填）"""
    name: str = Field(default="", description="姓名")
    phone: str = Field(default="", description="电话")
    email: str = Field(default="", description="邮箱")
    city: str = Field(default="", description="城市")


class ResumeBlock(BaseModel):
    """简历块：一段经历 / 技能行 / 项目"""
    company: str = Field(default="", description="公司（经历块）")
    title: str = Field(default="", description="岗位 title")
    period: str = Field(default="", description="在职/项目时间")
    bullets: list[str] = Field(default_factory=list, description="要点列表")
    skills_line: str = Field(default="", description="技能一行摘要")


class ResumeSection(BaseModel):
    """简历章节"""
    type: str = Field(default="", description="skills/experience/projects/...")
    heading: str = Field(default="", description="章节标题")
    blocks: list[ResumeBlock] = Field(default_factory=list)


class ResumeDocument(BaseModel):
    """投递用结构化简历终稿（聊天点评之外的 PDF 数据源）"""
    mode: str = Field(default="fact", description="fact | target")
    role_id: str = Field(default="", description="站内岗位 ID")
    role_title: str = Field(default="", description="岗位展示名")
    title: str = Field(default="", description="下载友好文件名")
    contact: ResumeContact = Field(default_factory=ResumeContact)
    intention: str = Field(default="", description="求职意向")
    sections: list[ResumeSection] = Field(default_factory=list)
    footer_note: str = Field(default="", description="页脚说明 / 蓝图警告")


class ChatResponse(BaseModel):
    """聊天响应"""
    content: str = Field(description="AI 助教回复")
    source: str = Field(default="", description="来源标注（兼容：citations[0]）")
    score: float = Field(default=0, description="相关性得分（兼容：citations[0]）")
    emotion: str = Field(default="neutral", description="检测到的情绪")
    agent: str = Field(default="", description="处理该消息的 Agent")
    thread_id: str = Field(default="", description="本轮使用的会话 ID")
    options: list[ChatOption] = Field(
        default_factory=list,
        description="本线程当前可选项（供气泡下可点按钮）",
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="本轮主课检索来源，供前端跳转视频",
    )
    analogy_citations: list[Citation] = Field(
        default_factory=list,
        description="类比课程来源（与主 citations 分区展示）",
    )
    resume_artifact_id: str = Field(
        default="",
        description="本轮 Resume 终稿 artifact；有则前端可打开 ResumeDock",
    )
    resume_mode: str = Field(
        default="",
        description="fact | target；配合 artifact 按钮文案",
    )
    resume_title: str = Field(
        default="",
        description="简历预览标题（方向/姓名）",
    )


# ── GET /api/student/{id} ─────────────────────────

class StudentResponse(BaseModel):
    """学员信息响应"""
    id: int
    display_name: str
    persona: str
    coach_style: str
    skill_level: str
    target_role: str


# ── PUT /api/student/{id} ─────────────────────────

class StudentUpdate(BaseModel):
    """学员信息更新请求"""
    coach_style: str | None = Field(default=None, description="新的人格标识")


# ── GET /api/conversations?student_id=N ────────────

class ConversationItem(BaseModel):
    """会话列表条目（按 thread 聚合）"""
    thread_id: str
    title: str
    created_at: str
    is_trashed: bool = Field(default=False, description="是否在垃圾桶中")


class ConversationList(BaseModel):
    """会话列表"""
    student_id: int
    conversations: list[ConversationItem]


# ── GET /api/conversations/{thread_id}/messages ─────

class ThreadMessage(BaseModel):
    """会话内的一条消息"""
    id: int
    role: str          # "user" | "assistant"
    content: str
    created_at: str
    source: str = Field(default="", description="来源标注（兼容 citations[0]）")
    citations: list[Citation] = Field(default_factory=list, description="主课检索来源跳转")
    analogy_citations: list[Citation] = Field(
        default_factory=list,
        description="类比课程来源",
    )


class ThreadMessages(BaseModel):
    """会话的全部消息"""
    thread_id: str
    messages: list[ThreadMessage]


# ── GET /api/conversations/{thread_id}/state ───────

class ThreadDialogState(BaseModel):
    """会话级对话状态（与 Checkpointer 一致，会话间互不干扰）"""
    thread_id: str
    pending_options: list[ChatOption] = Field(default_factory=list)
    pending_agent: str = Field(default="", description="选号后粘性路由目标")


# ── 模拟面试语音 ───────────────────────────────────

class InterviewTtsRequest(BaseModel):
    """面试官 TTS 请求"""
    text: str = Field(description="要播报的文本")
    voice: str | None = Field(default=None, description="可选音色覆盖")
    instruct: str | None = Field(
        default=None,
        description="风格指令（CosyVoice）；Edge 可忽略",
    )


class InterviewAsrResponse(BaseModel):
    """学员语音识别结果"""
    text: str = Field(description="转写文本")
    duration_ms: int = Field(default=0, description="音频时长估算（毫秒）")
    language: str = Field(default="zh")


class SpeechReadyResponse(BaseModel):
    """语音后端就绪状态"""
    ready: bool
    detail: str
    asr_backend: str = ""
    tts_backend: str = ""


class TtsEngineItem(BaseModel):
    """一条 TTS 引擎发现结果"""
    id: str
    kind: str = ""
    base_url: str = ""
    model: str = ""
    priority: int = 0
    min_free_vram_mb: int = 0
    available: bool = False
    reason: str = ""
    latency_ms: int = 0


class SpeechEnginesResponse(BaseModel):
    """TTS 引擎目录探测"""
    engines: list[TtsEngineItem] = Field(default_factory=list)
    selected: str = Field(default="", description="当前 prepare 选定的引擎")
    gpu_free_mb: int | None = None


class SpeechPrepareResponse(BaseModel):
    """进面试场前 prepare 结果"""
    selected: str
    detail: str = ""
    engines: list[TtsEngineItem] = Field(default_factory=list)


class SpeechReleaseResponse(BaseModel):
    """释放本场拉起的 Cosy"""
    released: bool = False
    selected: str = "edge"


# ── 对话垃圾桶 ─────────────────────────────────────

class TrashRequest(BaseModel):
    """垃圾桶操作请求"""
    action: str = Field(description="trash | restore | purge")


class TrashResponse(BaseModel):
    """垃圾桶操作响应"""
    ok: bool = Field(default=True)
    action: str = Field(default="")
    thread_id: str = Field(default="")
    deleted: dict | None = Field(default=None, description="purge 时返回 {blocks, summary}")


# ── 会话内话题块检索 ────────────────────────────────

class TopicBlock(BaseModel):
    """单个话题块"""
    block_id: str = Field(description="块编号，如 block_1")
    topic: str = Field(description="话题名（≤15 字）")
    summary: str = Field(default="", description="片断摘要")
    message_count: int = Field(default=0, description="消息数量")
    created_at: str = Field(default="", description="块创建时间 ISO 格式")
    time_range: str = Field(default="", description="时间段，如 '10:00 - 10:03'")


class ThreadTopicsResponse(BaseModel):
    """单个会话的话题块列表"""
    thread_id: str
    topics: list[TopicBlock] = Field(default_factory=list)
    count: int = Field(default=0, description="话题块数量")


class ThreadTopicSummary(BaseModel):
    """一个会话的话题汇总信息"""
    thread_id: str
    thread_title: str = Field(default="", description="会话标题（首条消息）")
    created_at: str = Field(default="")
    topic_count: int = Field(default=0)
    message_count: int = Field(default=0)
    topics: list[TopicBlock] = Field(default_factory=list)
    is_trashed: bool = Field(default=False, description="是否在垃圾桶中")


class StudentTopicsResponse(BaseModel):
    """学员全部会话的话题汇总"""
    student_id: int
    time_range: str = Field(default="")
    threads: list[ThreadTopicSummary] = Field(default_factory=list)
    thread_count: int = Field(default=0)
    total_topics: int = Field(default=0)
