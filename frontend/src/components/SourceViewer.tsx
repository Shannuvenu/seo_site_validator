import { useEffect, useMemo, useRef } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { html as htmlLang } from "@codemirror/lang-html";
import { EditorView, Decoration } from "@codemirror/view";
import { StateEffect, StateField, RangeSet } from "@codemirror/state";
import type { SourceLocation } from "../types/api";

/**
 * Highlight decorations: when a source range is active, highlight the exact
 * line and (if offsets are present) the exact character range.
 */
const highlightEffect = StateEffect.define<SourceLocation | null>();

const highlightField = StateField.define<RangeSet<Decoration>>({
  create: () => RangeSet.empty,
  update(value, tr) {
    value = value.map(tr.changes);
    for (const e of tr.effects) {
      if (e.is(highlightEffect)) {
        if (!e.value) return RangeSet.empty;
        const { start_offset, end_offset } = e.value;
        if (
          typeof start_offset === "number" &&
          typeof end_offset === "number" &&
          start_offset < end_offset
        ) {
          return RangeSet.of([
            Decoration.mark({
              attributes: { class: "cm-source-highlight-range" },
            }).range(start_offset, end_offset),
          ]);
        }
      }
    }
    return value;
  },
});

interface SourceViewerProps {
  html: string;
  highlight?: SourceLocation | null;
  onClearHighlight?: () => void;
  height?: string;
}

export default function SourceViewer({
  html,
  highlight,
  onClearHighlight,
  height = "100%",
}: SourceViewerProps) {
  const viewRef = useRef<EditorView | null>(null);

  const extensions = useMemo(
    () => [
      htmlLang(),
      highlightField,
      EditorView.lineWrapping,
      EditorView.theme({
        "&": { backgroundColor: "transparent", color: "var(--text)" },
        ".cm-gutters": { backgroundColor: "var(--bg-panel)", color: "var(--text-faint)" },
        ".cm-activeLine": { backgroundColor: "transparent" },
        ".cm-activeLineGutter": { backgroundColor: "transparent" },
        ".cm-source-highlight-line": { backgroundColor: "rgba(59, 130, 246, 0.12)" },
        ".cm-source-highlight-range": {
          backgroundColor: "rgba(59, 130, 246, 0.35)",
          borderRadius: "2px",
        },
        "&.cm-focused": { outline: "none" },
      }),
      EditorView.theme(
        {
          ".cm-content": { caretColor: "var(--accent)" },
        },
        { dark: false },
      ),
    ],
    [],
  );

  // Scroll to and highlight the target line when the highlight changes.
  useEffect(() => {
    const view = viewRef.current;
    if (!view || !highlight) return;
    const lineNo = highlight.html_line;
    if (lineNo && lineNo >= 1 && lineNo <= view.state.doc.lines) {
      const line = view.state.doc.line(lineNo);
      view.dispatch({
        effects: [EditorView.scrollIntoView(line.from, { y: "center" })],
      });
    }
    view.dispatch({ effects: [highlightEffect.of(highlight)] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlight?.html_line, highlight?.start_offset, highlight?.end_offset]);

  return (
    <div
      className="source-viewer"
      style={{ height, overflow: "hidden" }}
      onClick={onClearHighlight}
    >
      <CodeMirror
        value={html}
        height={height}
        extensions={extensions}
        readOnly
        theme="light"
        basicSetup={{
          lineNumbers: true,
          foldGutter: false,
          highlightActiveLine: false,
          highlightActiveLineGutter: false,
        }}
        onCreateEditor={(view) => {
          viewRef.current = view;
        }}
      />
    </div>
  );
}
