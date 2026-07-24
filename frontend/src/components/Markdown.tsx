import ReactMarkdown from "react-markdown";

// 只读 Markdown 渲染（react-markdown，默认安全、不注入 HTML）。用于 issue 正文 / 评论——
// triage 的 schema_render 产的 `### 分节`、以及用户报告里的 **粗体** / _斜体_ / `code` / --- / 列表都能渲染。
// 样式见 styles.css 的 `.md`（走设计 token，双主题）。
export function Markdown({ children, dim }: { children: string; dim?: boolean }) {
  return (
    <div className={dim ? "md dim" : "md"}>
      <ReactMarkdown>{children || ""}</ReactMarkdown>
    </div>
  );
}
