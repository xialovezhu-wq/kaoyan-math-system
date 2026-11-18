"""Prepare a standalone local math page for the Codex browser panel."""
from __future__ import annotations

import argparse
from html import escape
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import quote


def standalone(title: str, fragment: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
:root {{
  color-scheme: light dark; --background: Canvas; --foreground: CanvasText;
  --card: Canvas; --card-foreground: CanvasText; --ring: Highlight;
  --muted: color-mix(in srgb, CanvasText 5%, Canvas);
  --border: color-mix(in srgb, CanvasText 38%, Canvas);
  --muted-foreground: color-mix(in srgb, CanvasText 72%, Canvas);
  --font-size-base: 1rem;
}}
body {{ margin: 0; padding: .8rem; background: Canvas; color: CanvasText;
  font: 16px/1.5 system-ui, "PingFang SC", sans-serif; }}
button, input, select {{ font: inherit; }}
summary, button {{ cursor: pointer; }}
</style></head><body>
{fragment}
</body></html>
"""


def write_page(path: Path, contents: str) -> None:
    if path.suffix.lower() not in (".html", ".htm"):
        raise ValueError("a sidebar page needs an .html or .htm extension")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            tmp = Path(handle.name)
            handle.write(contents)
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def panel_target(path: Path, title: str | None = None) -> dict:
    if path.suffix.lower() not in (".html", ".htm") or not path.is_file():
        raise ValueError(f"HTML page not found: {path}")
    label = f"打开{title or path.stem}讲解"
    link_text = label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    link_path = quote(str(path), safe="/ :@()+,;=._~-")
    return {
        "path": str(path),
        "link_label": label,
        "html_link": f"[{link_text}](<{link_path}>)",
        "open_in_codex": {"target": {"type": "file", "path": str(path)}},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("page", type=Path, help="Existing review page, or destination for a rendered fragment")
    parser.add_argument("--fragment", type=Path, help="An authorized fragment from the local math renderer")
    parser.add_argument("--title", help="Public link title (also the tab title when wrapping a fragment)")
    args = parser.parse_args()
    path = args.page.expanduser().resolve()
    if args.fragment is not None and not args.title:
        parser.error("--fragment needs a public --title")
    if args.fragment is not None:
        write_page(path, standalone(args.title, args.fragment.read_text(encoding="utf-8")))
    print(json.dumps(panel_target(path, args.title), ensure_ascii=False))


if __name__ == "__main__":
    main()
