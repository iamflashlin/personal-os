import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MailBody, paragraphs } from "./MailBody";

const flat =
  "Your assignment Film has been graded. You can review it here: https://deanza.instructure.com/courses/1/a/2 " +
  "________________________________________ You received this email because you use Canvas.";

describe("MailBody", () => {
  it("splits old flattened mail at separator rules and keeps real paragraphs", () => {
    expect(paragraphs(flat)).toHaveLength(2);
    expect(paragraphs("第一段\n第二行\n\n第二段")).toEqual(["第一段\n第二行", "第二段"]);
  });

  it("shows web addresses as short safe links, never raw HTML", () => {
    const html = renderToStaticMarkup(createElement(MailBody, { body: `${flat} <b>x</b> javascript:alert(1)` }));
    expect(html).toContain('href="https://deanza.instructure.com/courses/1/a/2"');
    expect(html).toContain("打开链接 · deanza.instructure.com");
    expect(html).not.toContain("<b>x</b>");
    expect(html).toContain("&lt;b&gt;x&lt;/b&gt;");
    expect(html).not.toContain('href="javascript');
  });

  it("keeps Chinese text after a link, and links with --- whole", () => {
    const html = renderToStaticMarkup(
      createElement(MailBody, { body: "详情 https://a.com/x请在周五前提交 https://b.com/post---title。" }),
    );
    expect(html).toContain('href="https://a.com/x"');
    expect(html).toContain("请在周五前提交");
    expect(html).toContain('href="https://b.com/post---title"');
    expect(paragraphs("a --- b")).toEqual(["a", "b"]);
  });

  it("turns a malformed address into plain text, not a link", () => {
    const html = renderToStaticMarkup(createElement(MailBody, { body: "see https://[bad here" }));
    expect(html).not.toContain("<a");
    expect(html).toContain("https://[bad");
  });
});
