import ReactMarkdown from "react-markdown";

// Read-only Markdown rendering (react-markdown; safe by default, no HTML injection). Used for issue bodies/comments.
// Supports triage schema_render's `### sections` and user reports' **bold** / _italic_ / `code` / --- / lists.
// See `.md` in styles.css for styles (design tokens, both themes).
export function Markdown({ children, dim }: { children: string; dim?: boolean }) {
  return (
    <div className={dim ? "md dim" : "md"}>
      <ReactMarkdown>{children || ""}</ReactMarkdown>
    </div>
  );
}
