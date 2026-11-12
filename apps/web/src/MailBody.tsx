import { Fragment, type ReactNode } from "react";
import { safeLink } from "./ConnectionsView";

// ASCII URL characters only: Chinese mail often runs text straight after a link
// ("https://a.com/x请在周五前提交"), which must stay visible (as in summaries' _LONG_URL).
const URL_RE = /https?:\/\/[A-Za-z0-9\-._~:/?#[\]@!$&*+,;=%()]+/g;
// Lines of ___ / --- / === (3+) separate a mail's footer; older stored mail lost its line
// breaks, so these are the only paragraph marks left in it.
// Only a rule standing on its own: "post---title" inside a link is not a separator.
const RULE_RE = /(?:^|\s)[_\-=]{3,}(?=\s|$)/g;

/** Paragraphs of a mail body: its own blank lines, plus breaks at separator rules. */
export function paragraphs(body: string): string[] {
  return body
    .replace(/\r\n?/g, "\n")
    .split(/\n\s*\n/)
    .flatMap((block) => block.split(RULE_RE))
    .map((p) => p.trim())
    .filter(Boolean);
}

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** Text with each web address shown as a short link ("打开链接 · example.com"). Plain
 * React text and anchors only: mail is never rendered as HTML. */
export function linkify(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    let raw = m[0].replace(/[.,;:!?]+$/, "");
    if (raw.endsWith(")") && !raw.includes("(")) raw = raw.slice(0, -1);
    const at = m.index ?? 0;
    out.push(text.slice(last, at));
    const link = safeLink(raw);
    out.push(
      link ? (
        <a key={at} href={link} target="_blank" rel="noreferrer noopener">
          打开链接 · {host(link)}
        </a>
      ) : (
        raw
      ),
    );
    last = at + raw.length;
  }
  out.push(text.slice(last));
  return out;
}

export function MailBody({ body }: { body: string }) {
  const parts = paragraphs(body);
  if (parts.length === 0) return <p className="muted">（没有正文）</p>;
  return (
    <div className="original" data-testid="mail-body">
      {parts.map((p, i) => (
        <p key={i}>
          {p.split("\n").map((line, j) => (
            <Fragment key={j}>
              {j > 0 && <br />}
              {linkify(line)}
            </Fragment>
          ))}
        </p>
      ))}
    </div>
  );
}
