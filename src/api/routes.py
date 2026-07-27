"""API 路由 — 处理前端请求，调用 Supervisor。"""

import json
import queue
import threading
import time

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from fastapi.responses import HTMLResponse, Response, StreamingResponse

from src.api.schemas import (
    ChatRequest, ChatResponse, ChatOption, Citation, ResumeDocument,
    StudentResponse, StudentUpdate,
    ConversationItem, ConversationList,
    ThreadMessage, ThreadMessages, ThreadDialogState,
    InterviewTtsRequest, InterviewAsrResponse, SpeechReadyResponse,
    SpeechEnginesResponse, SpeechPrepareResponse, SpeechReleaseResponse,
    TtsEngineItem,
)
from src.agents.citations import normalize_citations
from src.db.init_db import get_session
from src.db.schema import Student, QAHistory
from src.agents.supervisor import (
    run_supervisor,
    get_thread_dialog_state,
    delete_thread_checkpoint,
)
from src.agents.stream_events import set_stream_callback, reset_stream_callback
from src.memory.context import delete_thread_summary
from src.perf import get_perf_logger, log_timing
from src.resume.artifact import (
    get_resume_artifact,
    save_resume_artifact,
    render_resume_html,
    render_resume_pdf,
)

router = APIRouter()

_timings: dict[str, float] = {}


def _start() -> float:
    return time.perf_counter()


def _end(start: float, label: str):
    elapsed = time.perf_counter() - start
    _timings[label] = elapsed
    log_timing(f"api.{label}", elapsed)


def _to_options(raw: list | None) -> list[ChatOption]:
    """将 supervisor 返回的 dict 列表转为 ChatOption。"""
    options: list[ChatOption] = []
    for item in raw or []:
        try:
            options.append(ChatOption(id=int(item["id"]), text=str(item.get("text", ""))))
        except (KeyError, TypeError, ValueError):
            continue
    return options


def _persist_chat_result(
    *,
    student_id: int,
    message: str,
    thread_id: str,
    result: dict,
) -> ChatResponse:
    """规范化 citations、写 QAHistory，返回 ChatResponse（流式/非流式共用）。"""
    citations_raw = normalize_citations(result.get("citations") or [])
    analogy_raw = normalize_citations(result.get("analogy_citations") or [])
    citations = [Citation(**c) for c in citations_raw]
    analogy_citations = [Citation(**c) for c in analogy_raw]
    top = citations[0] if citations else None

    content = result["content"]
    thread_id = result.get("thread_id") or thread_id
    options = _to_options(result.get("options"))
    resume_artifact_id = str(result.get("resume_artifact_id") or "")
    resume_mode = str(result.get("resume_mode") or "")
    resume_title = str(result.get("resume_title") or "")

    docs_payload: dict | None = None
    if citations or analogy_citations or resume_artifact_id:
        docs_payload = {
            "citations": [c.model_dump() for c in citations],
            "analogy_citations": [c.model_dump() for c in analogy_citations],
        }
        if resume_artifact_id:
            docs_payload["resume_artifact_id"] = resume_artifact_id
            docs_payload["resume_mode"] = resume_mode
            docs_payload["resume_title"] = resume_title
    with get_session() as session:
        record = QAHistory(
            student_id=student_id,
            thread_id=thread_id,
            question=message,
            answer=content,
            retrieved_docs=docs_payload,
        )
        session.add(record)
        session.commit()

    return ChatResponse(
        content=content,
        source=top.source if top else "",
        score=top.score if top else 0.0,
        emotion=result.get("emotion", "neutral"),
        agent=result.get("agent", ""),
        thread_id=thread_id,
        options=options,
        citations=citations,
        analogy_citations=analogy_citations,
        resume_artifact_id=resume_artifact_id,
        resume_mode=resume_mode,
        resume_title=resume_title,
    )


def _sse_line(payload: dict) -> str:
    """编码一条 SSE data 行。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ── 核心接口：发送消息 ──────────────────────────────

@router.post("/chat/", response_model=ChatResponse)
def chat(request: ChatRequest, req: Request):
    t0 = _start()
    _timings.clear()

    # 会话 ID：前端传入；缺省才生成。必须与 Checkpointer 使用同一 key。
    thread_id = (request.thread_id or "").strip() or (
        f"stu_{request.student_id}_{int(time.time())}"
    )

    # ① 查学员信息
    t = _start()
    with get_session() as session:
        student = session.query(Student).filter_by(id=request.student_id).first()
        if student is None:
            raise HTTPException(status_code=404, detail=f"学员不存在: id={request.student_id}")
    _end(t, "① 查学员 (SQLite)")

    # ② 调 Supervisor（按 thread_id 隔离图状态）
    t = _start()
    try:
        result = run_supervisor(
            graph=req.app.state.graph,
            student_id=request.student_id,
            message=request.message,
            thread_id=thread_id,
            selected_option_id=request.selected_option_id,
            voice_mode=bool(request.voice_mode),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理消息失败: {str(e)}")
    _end(t, "② Supervisor 总耗时")

    # ③ 写入 QAHistory
    t_cite = _start()
    response = _persist_chat_result(
        student_id=request.student_id,
        message=request.message,
        thread_id=thread_id,
        result=result,
    )
    _end(t_cite, "③ 规范化citations+写QAHistory")

    # ── 汇总写到 logs/perf.log ──
    total = time.perf_counter() - t0
    log_timing(
        "api.chat.total",
        total,
        thread_id=response.thread_id,
        agent=response.agent,
        citations=len(response.citations),
        analogy=len(response.analogy_citations),
    )
    perf = get_perf_logger()
    perf.info("------ chat 明细 thread=%s ------", response.thread_id)
    for label in list(_timings.keys()):
        pct = _timings[label] / total * 100 if total > 0 else 0
        perf.info("  %s: %.3fs (%.0f%%)", label, _timings[label], pct)

    return response


@router.post("/chat/stream")
def chat_stream(request: ChatRequest, req: Request):
    """
    聊天主路径：SSE 流式（status → token* → done | error）。
    协议见 docs/architecture/ui/chat-stream.md。
    """
    thread_id = (request.thread_id or "").strip() or (
        f"stu_{request.student_id}_{int(time.time())}"
    )

    with get_session() as session:
        student = session.query(Student).filter_by(id=request.student_id).first()
        if student is None:
            raise HTTPException(status_code=404, detail=f"学员不存在: id={request.student_id}")

    graph = req.app.state.graph
    student_id = request.student_id
    message = request.message
    selected_option_id = request.selected_option_id
    voice_mode = bool(request.voice_mode)

    def event_generator():
        t0 = time.perf_counter()
        q: queue.Queue = queue.Queue()
        first_token_at: list[float | None] = [None]

        def on_event(ev: dict):
            if ev.get("type") == "token" and first_token_at[0] is None:
                first_token_at[0] = time.perf_counter()
            q.put(ev)

        def worker():
            token = set_stream_callback(on_event)
            try:
                result = run_supervisor(
                    graph=graph,
                    student_id=student_id,
                    message=message,
                    thread_id=thread_id,
                    selected_option_id=selected_option_id,
                )
                response = _persist_chat_result(
                    student_id=student_id,
                    message=message,
                    thread_id=thread_id,
                    result=result,
                )
                done = {"type": "done", "voice_mode": voice_mode, **response.model_dump()}
                q.put(done)
            except Exception as e:
                q.put({"type": "error", "detail": str(e)})
            finally:
                reset_stream_callback(token)
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()

        try:
            while True:
                item = q.get()
                if item is None:
                    break
                yield _sse_line(item)
        finally:
            total = time.perf_counter() - t0
            ft = first_token_at[0]
            log_timing(
                "api.chat.stream.total",
                total,
                thread_id=thread_id,
            )
            if ft is not None:
                log_timing(
                    "api.chat.stream.first_token",
                    ft - t0,
                    thread_id=thread_id,
                )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 历史对话列表（按 thread 聚合） ──────────────────

@router.get("/conversations/", response_model=ConversationList)
def get_conversations(student_id: int):
    """查询学员的会话列表（按 thread_id 聚合，每 thread 一条）"""
    from sqlalchemy import func
    with get_session() as session:
        rows = (
            session.query(
                QAHistory.thread_id,
                func.min(QAHistory.created_at).label("first_at"),
            )
            .filter(QAHistory.student_id == student_id)
            .filter(QAHistory.thread_id.isnot(None))
            .filter(QAHistory.thread_id != "")
            .group_by(QAHistory.thread_id)
            .order_by(func.min(QAHistory.created_at).desc())
            .limit(50)
            .all()
        )
        # 二次查询取每个 thread 的第一条 question
        conversations = []
        for row in rows:
            tid = row.thread_id
            first_q = (
                session.query(QAHistory.question)
                .filter(QAHistory.thread_id == tid)
                .order_by(QAHistory.created_at.asc())
                .first()
            )
            conversations.append(ConversationItem(
                thread_id=tid or "",
                title=(first_q.question if first_q else "新对话"),
                created_at=row.first_at.isoformat() if row.first_at else "",
            ))
        return ConversationList(student_id=student_id, conversations=conversations)


# ── 会话消息 ────────────────────────────────────────

def _docs_bucket_from_record(record: QAHistory) -> tuple[list, list]:
    """从 retrieved_docs 拆出主 citations / 类比（兼容旧 list 格式）。"""
    raw = record.retrieved_docs
    if not raw:
        return [], []
    if isinstance(raw, dict) and (
        "citations" in raw or "analogy_citations" in raw
    ):
        main = [x for x in (raw.get("citations") or []) if isinstance(x, dict)]
        analogy = [
            x for x in (raw.get("analogy_citations") or []) if isinstance(x, dict)
        ]
        return main, analogy
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)], []
    if isinstance(raw, dict):
        return [raw], []
    return [], []


def _citations_from_items(items: list) -> list[Citation]:
    """dict 列表 → Citation 列表。"""
    normalized = normalize_citations(items)
    out: list[Citation] = []
    for item in normalized:
        try:
            out.append(Citation(**item))
        except Exception:
            continue
    return out


def _citations_from_record(record: QAHistory) -> list[Citation]:
    """从 QAHistory.retrieved_docs 恢复主 citations。"""
    main, _ = _docs_bucket_from_record(record)
    return _citations_from_items(main)


@router.get("/conversations/{thread_id}/messages", response_model=ThreadMessages)
def get_thread_messages(thread_id: str):
    """查询某个会话的全部消息"""
    with get_session() as session:
        records = (
            session.query(QAHistory)
            .filter(QAHistory.thread_id == thread_id)
            .order_by(QAHistory.created_at.asc())
            .all()
        )
        messages = []
        for r in records:
            messages.append(ThreadMessage(
                id=r.id,
                role="user",
                content=r.question or "",
                created_at=r.created_at.isoformat() if r.created_at else "",
            ))
            if r.answer:
                main_raw, analogy_raw = _docs_bucket_from_record(r)
                citations = _citations_from_items(main_raw)
                analogy_citations = _citations_from_items(analogy_raw)
                top = citations[0] if citations else None
                messages.append(ThreadMessage(
                    id=r.id,
                    role="assistant",
                    content=r.answer,
                    created_at=r.created_at.isoformat() if r.created_at else "",
                    source=top.source if top else "",
                    citations=citations,
                    analogy_citations=analogy_citations,
                ))
        return ThreadMessages(thread_id=thread_id, messages=messages)


# ── 会话对话状态（pending_options，按 thread 隔离）──

@router.get("/conversations/{thread_id}/state", response_model=ThreadDialogState)
def get_conversation_state(thread_id: str, req: Request):
    """读取本会话 Checkpointer 中的 pending_options，用于切会话后恢复选项条。"""
    graph = getattr(req.app.state, "graph", None)
    if graph is None:
        raise HTTPException(status_code=503, detail="图未就绪")
    state = get_thread_dialog_state(graph, thread_id)
    return ThreadDialogState(
        thread_id=state.get("thread_id") or thread_id,
        pending_options=_to_options(state.get("pending_options")),
        pending_agent=state.get("pending_agent") or "",
    )


# ── 删除会话 ──────────────────────────────────────

@router.delete("/conversations/{thread_id}")
def delete_conversation(thread_id: str, req: Request):
    """删除某个会话的全部消息，并清理该 thread 的图状态与摘要。"""
    student_id: int | None = None
    with get_session() as session:
        first = (
            session.query(QAHistory.student_id)
            .filter(QAHistory.thread_id == thread_id)
            .first()
        )
        if first:
            student_id = first.student_id
        count = (
            session.query(QAHistory)
            .filter(QAHistory.thread_id == thread_id)
            .delete()
        )
        session.commit()

    graph = getattr(req.app.state, "graph", None)
    if graph is not None:
        delete_thread_checkpoint(graph, thread_id)
    if student_id is not None:
        try:
            delete_thread_summary(student_id, thread_id)
        except Exception:
            pass

    return {"success": True, "deleted": count}


# ── 学员信息 ──────────────────────────────────────

@router.get("/student/{student_id}", response_model=StudentResponse)
def get_student(student_id: int):
    """查询学员基本信息"""
    with get_session() as session:
        student = session.query(Student).filter_by(id=student_id).first()
        if student is None:
            raise HTTPException(status_code=404, detail=f"学员不存在: id={student_id}")
        return StudentResponse(
            id=student.id,
            display_name=student.display_name or "",
            persona=student.persona or "",
            coach_style=student.coach_style or "encouraging",
            skill_level=student.skill_level or "beginner",
            target_role=student.target_role or "",
        )


@router.put("/student/{student_id}")
def update_student(student_id: int, update: StudentUpdate):
    """更新学员信息（人格切换等）"""
    with get_session() as session:
        student = session.query(Student).filter_by(id=student_id).first()
        if student is None:
            raise HTTPException(status_code=404, detail=f"学员不存在: id={student_id}")
        if update.coach_style:
            student.coach_style = update.coach_style
            session.commit()
            return {"success": True, "message": f"已切换为 {update.coach_style}"}
        return {"success": False, "message": "未提供更新字段"}


# ── 简历预览 / PDF ─────────────────────────────────

@router.get("/resume/preview/{artifact_id}")
def resume_preview(artifact_id: str):
    """A4 HTML 预览（与 PDF 同源数据）。"""
    doc = get_resume_artifact(artifact_id)
    if not doc:
        raise HTTPException(status_code=404, detail="简历 artifact 不存在或已过期")
    return HTMLResponse(content=render_resume_html(doc))


@router.get("/resume/pdf/{artifact_id}")
def resume_pdf(artifact_id: str):
    """下载 PDF。"""
    doc = get_resume_artifact(artifact_id)
    if not doc:
        raise HTTPException(status_code=404, detail="简历 artifact 不存在或已过期")
    try:
        pdf_bytes = render_resume_pdf(doc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 渲染失败: {e}") from e
    # HTTP header 仅 ASCII；中文文件名用 RFC 5987 filename*
    from urllib.parse import quote

    name = (doc.get("title") or doc.get("role_id") or "resume").strip() or "resume"
    ascii_name = "".join(
        ch if ("A" <= ch <= "Z" or "a" <= ch <= "z" or "0" <= ch <= "9" or ch in "-_") else "_"
        for ch in name
    )[:48].strip("_") or "resume"
    filename = f"{ascii_name}.pdf"
    filename_star = quote(f"{name}.pdf", safe="")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; '
                f"filename*=UTF-8''{filename_star}"
            ),
        },
    )


@router.post("/resume/render")
def resume_render(doc: ResumeDocument):
    """调试：直接提交 ResumeDocument → artifact_id。"""
    aid = save_resume_artifact(doc.model_dump())
    return {
        "artifact_id": aid,
        "preview_path": f"/api/resume/preview/{aid}",
        "pdf_path": f"/api/resume/pdf/{aid}",
        "mode": doc.mode,
        "title": doc.title or doc.role_title,
    }


# ── 模拟面试语音（ASR / TTS，可插拔 local）──────────


@router.get("/interview/speech/ready", response_model=SpeechReadyResponse)
def interview_speech_ready():
    """探测本地 ASR/TTS 是否可用（不阻塞主 chat）。"""
    from src.config import config
    from src.speech import check_speech_ready

    ok, detail = check_speech_ready()
    return SpeechReadyResponse(
        ready=ok,
        detail=detail,
        asr_backend=config.speech.asr_backend,
        tts_backend=config.speech.tts_backend,
    )


@router.get("/interview/speech/engines", response_model=SpeechEnginesResponse)
def interview_speech_engines():
    """发现可用 TTS 引擎（不启进程、不迁 Embedding）。"""
    from src.speech.lifecycle import (
        discover_tts_engines,
        engines_to_dict,
        get_selected_engine_id,
        gpu_free_mb,
    )

    engines = discover_tts_engines()
    return SpeechEnginesResponse(
        engines=[TtsEngineItem(**x) for x in engines_to_dict(engines)],
        selected=get_selected_engine_id(),
        gpu_free_mb=gpu_free_mb(),
    )


@router.post("/interview/speech/prepare", response_model=SpeechPrepareResponse)
def interview_speech_prepare():
    """进面试场前：发现 → 可选启本机 Cosy → 选定引擎。"""
    from src.speech.lifecycle import engines_to_dict, prepare_interview_speech

    result = prepare_interview_speech()
    return SpeechPrepareResponse(
        selected=result.selected,
        detail=result.detail,
        engines=[TtsEngineItem(**x) for x in engines_to_dict(result.engines)],
    )


@router.post("/interview/speech/release", response_model=SpeechReleaseResponse)
def interview_speech_release():
    """结束面试：停本场拉起的 Cosy；不碰 Embedding。"""
    from src.speech.lifecycle import release_interview_speech

    data = release_interview_speech()
    return SpeechReleaseResponse(
        released=bool(data.get("released")),
        selected=str(data.get("selected") or "edge"),
    )


@router.post("/interview/asr", response_model=InterviewAsrResponse)
async def interview_asr(file: UploadFile = File(..., description="学员语音片段")):
    """学员一句语音 → 文本（AsrProvider）。"""
    from src.speech import SpeechError, get_asr_provider

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空音频")
    mime = file.content_type or "audio/webm"
    try:
        result = get_asr_provider().transcribe(raw, mime=mime)
    except SpeechError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ASR 失败: {e}") from e
    return InterviewAsrResponse(
        text=result.text,
        duration_ms=result.duration_ms,
        language=result.language,
    )


@router.post("/interview/tts")
def interview_tts(body: InterviewTtsRequest):
    """面试官文本 → 音频（TtsProvider）；默认 audio/mpeg。"""
    from src.speech import SpeechError, get_tts_provider
    from src.speech.local_tts import DEFAULT_INTERVIEW_INSTRUCT

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本为空")
    instruct = body.instruct or DEFAULT_INTERVIEW_INSTRUCT
    try:
        result = get_tts_provider().synthesize(
            text, voice=body.voice, instruct=instruct,
        )
    except SpeechError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 失败: {e}") from e
    return Response(content=result.audio, media_type=result.mime or "audio/mpeg")
