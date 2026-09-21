from pathlib import Path


def build_report(rows, output, renderer="pdf"):
    if renderer == "pdf":
        raise RuntimeError("PDF renderer unavailable in this offline workspace")
    if renderer != "html":
        raise ValueError(renderer)
    cells = "".join(
        f"<tr><td>{row['name']}</td><td>{row['amount']}</td></tr>" for row in rows
    )
    Path(output).write_text(f"<table>{cells}</table>\n")
