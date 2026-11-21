import { describe, expect, it } from "vitest";
import { htmlToText, textToHtml } from "@/lib/richtext";

describe("richtext", () => {
  it("round-trips formatting, font sizes, layout markers and paragraphs", () => {
    const text = 'Vir <b>ons</b> <span style="font-size:11pt">groot</span> <1/>a<2/>\n<i>Tweede</i> [[Tab/]]x';
    expect(htmlToText(textToHtml(text))).toBe(text);
  });
  it("maps editor tags to the stored format and drops unsupported markup", () => {
    expect(htmlToText('<p><strong>a</strong><em>b</em><span style="font-size: 12pt">c</span><span style="color:red">d</span></p>'))
      .toBe('<b>a</b><i>b</i><span style="font-size:12pt">c</span>d');
  });
  it("escapes literal angle brackets", () => {
    expect(htmlToText(textToHtml("a < b & c"))).toBe("a < b & c");
  });
});
