// Segment text is plain text with inline layout markers (<1/>, [[Tab/]]) plus the few formatting tags the typesetter accepts:
// <b>, <i>, <u> and <span style="font-size:Npt">. These helpers convert between that format and the editor's HTML.

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function textToHtml(text: string): string {
  const safe = esc(text)
    .replace(/&lt;(\/?)(b|i|u)&gt;/g, "<$1$2>")
    .replace(/&lt;span style="font-size:(\d{1,2}(?:\.\d)?)pt"&gt;/g, '<span style="font-size:$1pt">')
    .replace(/&lt;\/span&gt;/g, "</span>");
  return safe.split("\n").map((line) => `<p>${line}</p>`).join("");
}

function walk(node: Node): string {
  if (node.nodeType === 3) return node.textContent ?? "";
  if (node.nodeType !== 1) return "";
  const el = node as HTMLElement;
  const tag = el.tagName.toLowerCase();
  const inner = Array.from(el.childNodes).map(walk).join("");
  if (tag === "br") return "\n";
  if (tag === "strong" || tag === "b") return `<b>${inner}</b>`;
  if (tag === "em" || tag === "i") return `<i>${inner}</i>`;
  if (tag === "u") return `<u>${inner}</u>`;
  if (tag === "span") {
    const m = /font-size:\s*(\d{1,2}(?:\.\d)?)pt/.exec(el.getAttribute("style") ?? "");
    return m ? `<span style="font-size:${m[1]}pt">${inner}</span>` : inner;
  }
  return inner;
}

export function htmlToText(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const paragraphs = Array.from(doc.body.children).map((p) => Array.from(p.childNodes).map(walk).join(""));
  return paragraphs.join("\n").replace(/\n+$/, "");
}
