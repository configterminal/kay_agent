"""
情感检测器 — 实时分析学员情绪，支持趋势查询和预警。

每条消息都通过 detect() 分析情绪，结果写入 emotion_records 表。
Supervisor 及子 Agent 根据情绪标签调整回复风格。

使用方式：
    from src.emotion.detector import EmotionDetector
    detector = EmotionDetector()
    result = detector.detect("这个报错我查了一下午都没解决")
    # → EmotionResult(state="frustrated", confidence=0.9, evidence="...")

Prompt 定义在 src/llm/base.py 的 _build_emotion_prompt() 中。
"""

from datetime import datetime, timedelta

from src.db.init_db import get_session
from src.db.schema import EmotionRecord
from src.llm.base import LLMProvider, EmotionResult


class EmotionDetector:
    """情感检测器 — 每条消息分析情绪，支持趋势查询和预警"""

    def __init__(self):
        self._provider = LLMProvider.create()

    # ── 核心检测 ─────────────────────────────────────

    def detect(self, text: str) -> EmotionResult:
        """
        分析单条消息的情绪。
        LLMProvider 内部已包含 Few-Shot prompt 和 JSON 解析，这里直接调用。
        """
        return self._provider.analyze_emotion(text)

    # ── 持久化 ───────────────────────────────────────

    def record(
        self,
        student_id: int,
        result: EmotionResult,
        context: str = "",
    ) -> None:
        """将情绪分析结果写入 SQLite emotion_records 表"""
        with get_session() as session:
            record = EmotionRecord(
                student_id=student_id,
                state=result.state,
                confidence=result.confidence,
                trigger=result.evidence,
                context=context,
            )
            session.add(record)
            session.commit()

    # ── 趋势分析 ─────────────────────────────────────

    def get_recent_trend(self, student_id: int, minutes: int = 60) -> dict:
        """
        查询最近 N 分钟的情绪趋势。
        返回 {"dominant": 主导情绪, "count": 记录数, "variety": 情绪种类数}
        """
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        with get_session() as session:
            records = (
                session.query(EmotionRecord)
                .filter(
                    EmotionRecord.student_id == student_id,
                    EmotionRecord.created_at >= cutoff,
                )
                .order_by(EmotionRecord.created_at.desc())
                .all()
            )

        if not records:
            return {"dominant": "unknown", "count": 0, "variety": 0}

        # 统计各情绪出现次数，找出主导情绪
        from collections import Counter
        counter = Counter(r.state for r in records)
        dominant = counter.most_common(1)[0][0]

        return {
            "dominant": dominant,
            "count": len(records),
            "variety": len(counter),
        }

    # ── 预警检查 ─────────────────────────────────────

    def should_alert(self, student_id: int) -> dict:
        """
        检查是否需要预警。
        返回 {"alert": bool, "reason": str, "level": "warning"|"notice"|"none"}
        """
        with get_session() as session:
            # 查最近 10 条情绪记录
            recent = (
                session.query(EmotionRecord)
                .filter(EmotionRecord.student_id == student_id)
                .order_by(EmotionRecord.created_at.desc())
                .limit(10)
                .all()
            )

        if not recent:
            return {"alert": False, "reason": "", "level": "none"}

        states = [r.state for r in recent]

        # 连续 3 次 frustrated 或 anxious → 警告
        negative_streak = 0
        for s in states:
            if s in ("frustrated", "anxious"):
                negative_streak += 1
            else:
                break
        if negative_streak >= 3:
            return {
                "alert": True,
                "reason": f"连续 {negative_streak} 次负面情绪（{states[0]}），建议主动干预",
                "level": "warning",
            }

        # 最近记录全是 disengaged → 提醒
        if all(s == "disengaged" for s in states[:5]):
            return {
                "alert": True,
                "reason": "学员近期状态懈怠，建议发送学习提醒",
                "level": "notice",
            }

        return {"alert": False, "reason": "", "level": "none"}
