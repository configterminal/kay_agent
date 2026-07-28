# InterviewAgent 工具

## 工具

```
get_interview_questions(role_id, difficulty, count=5) → list[dict]
    根据岗位+难度出题 [{question_id, text, type, expected_topics}]

evaluate_answer(question, answer, role_id) → dict
    逐题评分 {score, strengths, weaknesses, model_answer}
    后台评分，不打断对话

generate_interview_report(session_id) → dict
    面试复盘报告 {total_score, by_question, overall_feedback, improvement_plan, offer}
    含模拟 Offer

save_interview_session(student_id, role_id, questions, answers) → str
    保存面试记录，返回 session_id
```

## 面试流程

三个阶段，自然对话式，不分"第N题"：
1. 面试官提问（自然推进 + 追问 + 深挖）
2. 学员反问（Agent 切换为"公司代表"角色回答）
3. 模拟 Offer（总分≥70 给出模拟 Offer + 谈薪 + 改进建议）
4. 复盘报告（面试结束后当场简评，详细报告可查历史）
