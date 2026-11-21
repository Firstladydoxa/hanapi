"use client";

import { Extension } from "@tiptap/core";
import { TextStyle } from "@tiptap/extension-text-style";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect } from "react";
import { htmlToText, textToHtml } from "@/lib/richtext";

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    fontSize: { setFontSize: (size: string) => ReturnType; unsetFontSize: () => ReturnType };
  }
}

const FontSize = Extension.create({
  name: "fontSize",
  addGlobalAttributes() {
    return [{
      types: ["textStyle"],
      attributes: {
        fontSize: {
          default: null,
          parseHTML: (el: HTMLElement) => /(\d{1,2}(?:\.\d)?)pt/.exec(el.style.fontSize)?.[0] ?? null,
          renderHTML: (attrs: { fontSize?: string | null }) => (attrs.fontSize ? { style: `font-size:${attrs.fontSize}` } : {}),
        },
      },
    }];
  },
  addCommands() {
    return {
      setFontSize: (size: string) => ({ chain }) => chain().setMark("textStyle", { fontSize: size }).run(),
      unsetFontSize: () => ({ chain }) => chain().setMark("textStyle", { fontSize: null }).removeEmptyTextStyle().run(),
    };
  },
});

export const SIZES = [7, 8, 9, 9.5, 10, 11, 12, 14, 16, 18, 22, 28];

interface Props { value: string; onChange: (text: string) => void; dir?: "ltr" | "rtl"; minHeight?: number; label: string; readOnly?: boolean }

export function RichText({ value, onChange, dir = "ltr", minHeight = 80, label, readOnly = false }: Props) {
  const editor = useEditor({
    immediatelyRender: false,
    extensions: [StarterKit.configure({ heading: false, blockquote: false, bulletList: false, orderedList: false, listItem: false, code: false, codeBlock: false, horizontalRule: false, strike: false }), TextStyle, FontSize],
    content: textToHtml(value),
    editable: !readOnly,
    editorProps: { attributes: { class: "rich-body", dir, role: "textbox", "aria-label": label, "aria-multiline": "true", style: `min-height:${minHeight}px` } },
    onUpdate: ({ editor: e }) => onChange(htmlToText(e.getHTML())),
  });
  useEffect(() => { editor?.setEditable(!readOnly); }, [editor, readOnly]);
  if (!editor) return <div className="input" style={{ minHeight }} />;
  const size = (editor.getAttributes("textStyle").fontSize as string | undefined)?.replace("pt", "") ?? "";
  const btn = (name: string, text: string, active: boolean, run: () => void, cls = "") => (
    <button type="button" className={`rich-btn ${cls} ${active ? "is-active" : ""}`} aria-label={name} aria-pressed={active} title={name} disabled={readOnly}
      onMouseDown={(e) => e.preventDefault()} onClick={run}>{text}</button>);
  return (
    <div className="rich">
      <div className="rich-bar" role="toolbar" aria-label={`${label} formatting`}>
        {btn("Bold", "B", editor.isActive("bold"), () => editor.chain().focus().toggleBold().run(), "font-bold")}
        {btn("Italic", "I", editor.isActive("italic"), () => editor.chain().focus().toggleItalic().run(), "italic")}
        {btn("Underline", "U", editor.isActive("underline"), () => editor.chain().focus().toggleUnderline().run(), "underline")}
        <select className="rich-size" aria-label="Font size" value={size} disabled={readOnly}
          onChange={(e) => (e.target.value ? editor.chain().focus().setFontSize(`${e.target.value}pt`).run() : editor.chain().focus().unsetFontSize().run())}>
          <option value="">Size</option>
          {SIZES.map((s) => <option key={s} value={String(s)}>{s} pt</option>)}
        </select>
        {btn("Undo", "↶", false, () => editor.chain().focus().undo().run())}
        {btn("Redo", "↷", false, () => editor.chain().focus().redo().run())}
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}
