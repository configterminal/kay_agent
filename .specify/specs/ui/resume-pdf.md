# 简历优化结果 — A4 / PDF 展示

> 状态：**Phase 1 已实现** | 最后更新：2026-07-16  
> 关联：[ResumeAgent](../agents/resume.md) · [API](api.md) · [UI 总览](index.md)  
> 目标：HR 主要看 PDF，优化结果需有**独立、像简历的呈现**，而不是只埋在聊天气泡里。

## 1. 问题

当前 ResumeAgent 把「审计说明 + 改前改后 + 闭环」混在 Markdown 聊天里：

- 学员难一眼看到「投递用终稿长什么样」  
- 无法按 A4/PDF 心智检查版式与一页密度  
- 不便下载后投递或给他人看  

## 2. 产品原则

| 原则 | 说明 |
|------|------|
| **双轨输出** | 聊天区 = 教练点评；PDF 区 = 可投递/可预览的简历正文 |
| **像 HR 看的** | A4 单栏、中文技术岗常见结构；非仪表盘卡片墙 |
| **模式诚实** | `target` 蓝图页眉/水印标明「目标蓝图·完成学习前勿当已有经历」 |
| **事实底线** | PDF 生成不改写任职造假规则；内容来自 Agent 结构化稿 |
| **先预览后下载** | 页内 A4 预览必有；下载 PDF 一键可得 |

## 3. 信息架构

```
助手消息（聊天）
├── 点评区（Markdown）：30 秒结论 / 对照 / 改写说明 / 课练面闭环
└── [📄 查看优化简历] 按钮 ──► ResumeDock（底部或右侧展开）
                                  ├── A4 预览（HTML 或 PDF embed）
                                  ├── 下载 PDF
                                  └── 关闭
```

对标现有 [VideoDock](video-jump.md)：点 citation 出视频；点「查看优化简历」出 ResumeDock。

布局（与 VideoDock 互斥或分栏，MVP **互斥**：同时只开一个 Dock）：

```
┌─ Sidebar ─┬─ 消息列表 ─────────────────────────────┐
│           │  …助手点评 Markdown…                    │
│           │  [📄 查看优化简历]                      │
│           │  ┌─ ResumeDock ─────────────────────┐ │
│           │  │ 目标：RAG方向 · fact · 下载PDF    │ │
│           │  │ ┌─ A4 纸面预览 ─────────────────┐ │ │
│           │  │ │  姓名 / 求职意向 …             │ │ │
│           │  │ │  工作经历 …                    │ │ │
│           │  │ └───────────────────────────────┘ │ │
│           │  └───────────────────────────────────┘ │
│           │  ChatInput                             │
└───────────┴────────────────────────────────────────┘
```

## 4. 数据契约

聊天里的 Markdown **不再充当**唯一简历正文。Agent / 编排层额外产出结构化稿：

```text
ResumeDocument:
  mode: "fact" | "target"
  role_id: str
  role_title: str
  title: str                 # 下载文件名友好名
  contact: { name, phone, email, city }   # 有则填
  intention: str             # 求职意向
  sections: [
    { type: "skills"|"experience"|"projects"|"education"|"summary"|...,
      heading: str,
      blocks: [
        { company?, title?, period?, bullets: [str], skills_line? }
      ]
    }
  ]
  footer_note: str           # fact 免责 / target 蓝图警告
```

来源（实现阶段二选一，方案定 **B**）：

| 方案 | 做法 | 取舍 |
|------|------|------|
| A | 仅从聊天 Markdown 再解析 | 脆、易丢结构 |
| **B** | ResumeAgent 工具或编排后处理生成 `ResumeDocument` JSON | 稳，推荐 |

MVP 可增工具：`build_resume_document(mode, role_id, base_text, feedback_json) → ResumeDocument`，或由 Agent 在结束时调用、Supervisor 写入响应。

### API

```text
ChatResponse 扩展：
  resume_document: ResumeDocument | null   # 本轮有则非空
  # 或仅 resume_artifact_id，按需拉取

GET  /api/resume/preview/{artifact_id}     # text/html A4 预览
GET  /api/resume/pdf/{artifact_id}         # application/pdf 下载
POST /api/resume/render                    # body=ResumeDocument → 临时 artifact（调试/重渲）
```

- artifact 存：进程内存 LRU + 可选落 `tmp/resume/{id}.json`（MVP 不进 SQLite）。  
- 预览 HTML 与 PDF **同源排版数据**（同一套 section 渲染），避免「预览一个样、PDF 另一个样」。

## 5. PDF / 预览技术选型（已定）

| 项 | 选择 | 原因 |
|----|------|------|
| 服务端 PDF | **ReportLab**（纯 Python） | Windows 友好；与现有 venv 一致；社区简历 Skill 常用 |
| 页内预览 | **服务端渲染的 A4 HTML**（同数据）或 PDF.js 嵌 PDF | MVP 用 HTML 预览更快；下载走真 PDF |
| 前端 | `ResumeDock.vue` + `iframe[src=previewUrl]` + 下载按钮 | 对齐 VideoDock 交互 |
| 禁止 | 复杂双栏/图标墙 HTML | ATS 与「像纸质简历」冲突 |

一页策略：渲染时用约 A4 高度提示；超一页在 Dock 提示「内容偏长，建议回聊天压缩」。

`target` 模式：页眉条或半透明水印「目标蓝图 · 非已有任职经历」。

## 6. 聊天与 PDF 的内容分工

| 内容 | 聊天 Markdown | PDF / A4 |
|------|:-------------:|:--------:|
| 30 秒结论、关键词对照 | ✅ | ❌ |
| 改前→改后说明 | ✅ | ❌（只留「改后」终稿） |
| 课 / 练 / 面闭环 | ✅ | ❌（或 PDF 末可选附录页，MVP 不做） |
| 求职意向、技能、经历、项目终稿 | 可摘要 | ✅ 正文 |
| 蓝图警告 | ✅ | ✅ 页眉/页脚 |

## 7. 前端交互

1. `agent === resume_agent` 且 `resume_document` 非空 → MessageItem 显示「查看优化简历」。  
2. 点击 → 打开 ResumeDock，请求 preview URL。  
3. 「下载 PDF」→ `GET .../pdf/...`（`Content-Disposition: attachment`）。  
4. 同轮再次优化 → 新 artifact_id，Dock 刷新。  
5. `target`：按钮文案「查看蓝图简历」；Dock 标题带警告色。

## 8. 实现分期

### Phase 1（本阶段建议）

1. 定 `ResumeDocument` schema（`src/schemas` + API）  
2. Resume 出口产出 JSON（工具或后处理）  
3. `GET preview` HTML A4 + `GET pdf` ReportLab  
4. `ResumeDock.vue` + MessageItem 入口  
5. 验收：fact 一轮优化 → 预览像一页纸 → 下载 PDF 可打开  

### Phase 2

- artifact 写入会话历史，刷新可回看  
- 学员在 Dock 内微调字段后重渲  
- 可选附录页：学习闭环  

### Phase 3

- Word/PDF 上传解析后进入同一预览链路  
- 真实 JD 关键词高亮（市场数据阶段）  

## 9. 明确不做（Phase 1）

- 花哨双栏模板、照片墙  
- 仅靠浏览器 `window.print` 当唯一导出（可作兜底，主路径仍是服务端 PDF）  
- 在 PDF 里塞虚假任职（规则同 ResumeAgent）  

## 10. 待确认（建议默认）

| 项 | 建议默认 |
|----|----------|
| Dock 位置 | 底部全宽（与 VideoDock 一致），互斥 |
| 预览形态 | HTML A4；下载为 ReportLab PDF |
| 聊天是否仍贴「终稿全文」 | **不贴全文**，只贴点评 + 按钮，避免双份不一致 |
| 文件名 | `{姓名或学员}_{role_id}_{mode}_{date}.pdf` |

Phase 1 已落地：`compose_resume_document` → artifact → `GET /api/resume/preview|pdf` + `ResumeDock`。
