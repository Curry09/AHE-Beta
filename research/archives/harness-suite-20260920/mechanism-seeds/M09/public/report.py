"""Seed: intentionally unavailable renderer; preserve a small public API."""


def build_report(rows, output, renderer="pdf"):
    if renderer == "pdf":
        raise RuntimeError("PDF renderer unavailable in this offline workspace")
    if renderer != "html":
        raise ValueError(f"Unsupported renderer: {renderer}")
    lines = ["<table>", "<tr><th>name</th><th>amount</th></tr>"]
    lines.extend(f"<tr><td>{row['name']}</td><td>{row['amount']}</td></tr>" for row in rows)
    lines.append("</table>")
    output.write_text("\n".join(lines) + "\n")
