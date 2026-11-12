# 0036: The mail assistant - tools, full text, proposals the user confirms

Status: accepted (2026-11-11). The user: "交互至少要像chatgpt里的邮件那样智能". Sending full
mail text to DeepSeek was agreed earlier ("直接用", ADR 0027), as was sending questions
("我同意把问题和总结发给deepseek", ADR 0033).

## Context
The first chat (ADR 0033) saw at most 60 one-line summaries and could not act. On real
questions it could not quote links or details, and it answered "我不能" to "过期的都标为已处理".
A spike on the user's real mail (`.evidence/spike-mail-agent/`) showed that DeepSeek with
tools gives ChatGPT-level answers, at about US$0.002 and 4–7 s per question.

## Decision
- **Tool calling.** `POST /chat/ask` runs up to 6 model turns. Tools:
  - `search_mail`: all non-sensitive mail, matching sender, subject, AI title, points and
    body;
  - `read_mail`: the full body, up to 4000 characters;
  - `list_mail`: open or all, with due = overdue, next 7 days or any;
  - `propose_mark_handled`.
- **Nothing is changed by the model.** A proposal returns item ids that the Hub has
  checked, open mail only, with a description written by code. The web shows it with
  确认, which calls `POST /triage/handle`: owner-scoped, audited, and undoable.
- **Privacy.**
  - Sensitive mail (one-time codes, reset links) is never searched, listed or read.
  - The question and the conversation are stored nowhere: `model_call.ref` is "", and the
    browser keeps the turns.
  - The full body of a mail the model reads is sent to DeepSeek.
- **Transport.** `ModelProvider.complete_tools` sends plain OpenAI-compatible HTTP over
  httpx. litellm-core imports its MCP handler whenever `tools` is passed, and that needs
  the `mcp` package, which we do not add. The timeouts, the error mapping and
  `ModelClient` accounting (reservation, the monthly cap, `model_call` rows) are the same
  as for JSON calls.
- **Prompt `mail_assistant` v1:**
  - answers only from mail it has read;
  - shows no refs;
  - proposes only when asked;
  - never does homework;
  - treats mail text as data.
- **Replaced.** The summary-only retrieval (`chat/retrieval.py`, `chat/output.py`, prompt
  `mail_chat` v1) is removed.

## Consequences
- Real cost on the user's mail: 29 calls for 9 questions, 16 082 micro-USD (about
  US$0.0018 per question).
- Search is a scan in Python over every mail per question. That is fine for hundreds of
  mails; at many thousands, a full-text index (FTS5) is the next step.
- Rules ("以后都不用提醒"), memory facts with categories and delete-to-trash come in later
  cards (each needs its own confirm flow).
