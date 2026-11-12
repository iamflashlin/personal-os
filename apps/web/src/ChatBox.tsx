import { useRef, useState } from "react";
import { type Api, ApiError, type ChatAnswer, type ChatTurn } from "./api";
import { MailLine } from "./MailView";
import { browserZone } from "./TodayView";

export const MAX_HISTORY = 6; // turns sent with each question (the Hub accepts at most 6)
const MAX_TURN = 1000;
const MAX_QUESTION = 500;

interface Exchange {
  question: string;
  answer?: ChatAnswer;
  error?: string;
}

/** The last turns as the Hub expects them: text only, newest last, each cut to its limit. */
export function historyFor(exchanges: Exchange[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  for (const e of exchanges) {
    if (!e.answer) continue; // an unanswered question is not part of the conversation
    turns.push({ role: "user", text: e.question.slice(0, MAX_TURN) });
    turns.push({ role: "assistant", text: e.answer.answer.slice(0, MAX_TURN) || "（无）" });
  }
  return turns.slice(-MAX_HISTORY);
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  return `连不上 Hub：${String(err)}`;
}

export function ChatBox({ api }: { api: Api }) {
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); // blocks Enter + click in the same tick

  async function send() {
    const question = draft.trim().slice(0, MAX_QUESTION);
    if (!question || inFlight.current) return; // one question at a time: each is billed
    inFlight.current = true;
    setBusy(true);
    const history = historyFor(exchanges);
    setExchanges((xs) => [...xs, { question }]);
    setDraft("");
    let result: Exchange;
    try {
      const answer = await api.askMail({ question, history, time_zone: browserZone() });
      result = { question, answer };
    } catch (err) {
      result = { question, error: errorText(err) };
    }
    setExchanges((xs) => [...xs.slice(0, -1), result]);
    inFlight.current = false;
    setBusy(false);
  }

  return (
    <section className="chat" data-testid="chat">
      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          data-testid="chat-input"
          value={draft}
          maxLength={MAX_QUESTION}
          placeholder="问问你的邮件，比如：这周有哪些作业要交？"
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" data-testid="chat-send" disabled={busy || !draft.trim()}>
          {busy ? "正在想…" : "问"}
        </button>
        {exchanges.length > 0 && !busy && (
          <button type="button" onClick={() => setExchanges([])}>
            清空对话
          </button>
        )}
      </form>
      {exchanges.map((e, i) => (
        <div key={i} className="chat-exchange" data-testid="chat-exchange">
          <p className="chat-question">问：{e.question}</p>
          {e.error && (
            <p className="error" role="alert" data-testid="chat-error">
              {e.error}
            </p>
          )}
          {!e.answer && !e.error && <p className="muted">正在想…</p>}
          {e.answer && (
            <>
              {/* Plain text only: the answer is model output and is never rendered as HTML. */}
              <p className="chat-answer" data-testid="chat-answer">
                {e.answer.answer}
              </p>
              {e.answer.unsummarised > 0 && (
                <p className="muted">还有 {e.answer.unsummarised} 封邮件没整理完，暂时查不到。</p>
              )}
              {e.answer.cited.length > 0 && (
                <ul className="memories" data-testid="chat-cited">
                  {e.answer.cited.map((c) => (
                    <MailLine
                      key={c.item.id}
                      row={{ item: c.item, source: "", summary: c.summary }}
                    />
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      ))}
    </section>
  );
}
