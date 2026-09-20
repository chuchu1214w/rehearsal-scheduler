"""把仓库里的 Markdown 文档(含 Mermaid 图、表格、中文)转成 PDF。

用法:
    python scripts/md2pdf.py 交互设计.md -o 交互设计.pdf
依赖:pip 包 markdown;本机安装的 Google Chrome(无头模式打印);Mermaid 通过 CDN 加载,需要联网。
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import markdown

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
]

CSS = """
@page { size: A4; margin: 16mm 14mm; }
html { -webkit-print-color-adjust: exact; }
body { font-family: "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", "Microsoft YaHei", sans-serif;
       font-size: 11.5px; line-height: 1.65; color: #1f2430; margin: 0; }
h1 { font-size: 24px; margin: 0 0 10px; }
h2 { font-size: 18px; margin: 26px 0 10px; padding-bottom: 4px; border-bottom: 2px solid #5369af; page-break-after: avoid; }
h3 { font-size: 14.5px; margin: 18px 0 8px; color: #2f3f78; page-break-after: avoid; }
p { margin: 6px 0; }
blockquote { margin: 8px 0; padding: 6px 12px; border-left: 4px solid #f7a0d1; background: #fef0fb; }
blockquote p { margin: 2px 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #b9bfd6; padding: 5px 7px; vertical-align: top; text-align: left; }
th { background: #fef0fb; font-weight: 700; }
th:empty { display: none; }
code { font-family: Menlo, Consolas, monospace; font-size: 10.5px; background: #f3f4f9; padding: 1px 4px; border-radius: 3px; }
pre.mermaid { display: block; text-align: center; margin: 10px 0 14px; white-space: normal; break-inside: avoid; page-break-inside: avoid; background: transparent; }
pre.mermaid svg { display: block; margin: 0 auto; }
hr { border: 0; border-top: 1px solid #d8dbe8; margin: 18px 0; }
ul, ol { padding-left: 22px; }
li { margin: 2px 0; }
.meta { color: #6b6f8a; font-size: 10.5px; margin-bottom: 14px; }
"""


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
        if "/" not in c and subprocess.run(["which", c], capture_output=True, check=False).returncode == 0:
            return c
    raise SystemExit("找不到 Google Chrome / Chromium,无法打印 PDF")


def md_to_html(text: str, title: str) -> str:
    blocks: list[str] = []

    def stash(match: re.Match) -> str:
        blocks.append(match.group(1))
        return f"\n\nMERMAIDBLOCK{len(blocks) - 1}END\n\n"

    text = re.sub(r"```mermaid\n(.*?)```", stash, text, flags=re.DOTALL)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    for i, block in enumerate(blocks):
        body = body.replace(f"<p>MERMAIDBLOCK{i}END</p>", f'<pre class="mermaid">{html.escape(block)}</pre>')
        body = body.replace(f"MERMAIDBLOCK{i}END", f'<pre class="mermaid">{html.escape(block)}</pre>')
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{CSS}</style></head><body>
{body}
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
mermaid.initialize({{ startOnLoad: false, theme: 'neutral', fontFamily: '"PingFang SC","Hiragino Sans GB",sans-serif' }});
// 逐张渲染并显式指定 id:无头 Chrome 的虚拟时间里 Date.now() 不走,mermaid.run 会给多张图同一个 id,后面的图会画进第一张里
const blocks = [...document.querySelectorAll('pre.mermaid')];
for (let i = 0; i < blocks.length; i++) {{
  try {{
    const {{ svg }} = await mermaid.render('mmd' + i, blocks[i].textContent);
    blocks[i].innerHTML = svg;
  }} catch (e) {{
    blocks[i].innerHTML = '<p style="color:#b13556">图渲染失败:' + String(e).replace(/</g, '&lt;') + '</p>';
  }}
}}
// Chrome 打印时,inline SVG 用 height:auto + max-width 会在分页处错位重叠;改为按页面尺寸算出固定像素宽高,且每张图不超过一页
const PAGE_H = 930;
for (const svg of document.querySelectorAll('pre.mermaid svg')) {{
  const vb = svg.viewBox.baseVal;
  if (!vb || !vb.width || !vb.height) continue;
  const maxW = svg.parentElement.clientWidth || 690;
  const scale = Math.min(1, maxW / vb.width, PAGE_H / vb.height);
  svg.style.maxWidth = 'none';
  svg.style.width = Math.floor(vb.width * scale) + 'px';
  svg.style.height = Math.floor(vb.height * scale) + 'px';
  svg.setAttribute('width', Math.floor(vb.width * scale));
  svg.setAttribute('height', Math.floor(vb.height * scale));
}}
document.documentElement.dataset.ready = '1';
</script></body></html>"""


def run_chrome(cmd: list[str], *, capture: bool = False, wait_for: Path | None = None, timeout: float = 150) -> str:
    """运行无头 Chrome。capture=True 时收集 stdout;wait_for 指向输出文件时,文件大小稳定后即结束进程。"""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    if capture:
        # --dump-dom 输出完整文档后 Chrome 可能不退出:读到 </html> 就结束
        assert proc.stdout is not None
        lines: list[str] = []
        deadline = time.time() + timeout
        for line in proc.stdout:
            lines.append(line)
            if "</html>" in line or time.time() > deadline:
                break
        if proc.poll() is None:
            proc.kill()
        return "".join(lines)
    deadline = time.time() + timeout
    last_size, stable = -1, 0
    while time.time() < deadline and proc.poll() is None:
        if wait_for is not None and wait_for.exists():
            size = wait_for.stat().st_size
            stable = stable + 1 if size > 0 and size == last_size else 0
            last_size = size
            if stable >= 4:  # 连续 2 秒大小不变
                break
        time.sleep(0.5)
    if proc.poll() is None:
        proc.kill()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("-o", "--output")
    parser.add_argument("--keep-html", action="store_true")
    args = parser.parse_args()
    src = Path(args.input)
    out = Path(args.output) if args.output else src.with_suffix(".pdf")
    text = src.read_text(encoding="utf-8")
    title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("# ")), src.stem)
    page = md_to_html(text, title)
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "doc.html"
        html_path.write_text(page, encoding="utf-8")
        if args.keep_html:
            src.with_suffix(".html").write_text(page, encoding="utf-8")
        chrome = find_chrome()
        # 第一步:用虚拟时间让 Mermaid 渲染完,把带静态 SVG 的 DOM 导出来。
        # (直接在这一步打印 PDF 会让多张图错位重叠;不用虚拟时间又会在渲染完成前打印。)
        static_path = Path(tmp) / "static.html"
        dump = run_chrome(
            [chrome, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp}/profile1", "--virtual-time-budget=30000", "--dump-dom", html_path.resolve().as_uri()],
            capture=True,
        )
        if "pre class=\"mermaid\"" in dump and "<svg" not in dump:
            raise SystemExit("Mermaid 没有渲染(需要联网加载 mermaid)")
        dump = re.sub(r"<script type=\"module\">.*?</script>", "", dump, flags=re.DOTALL)
        static_path.write_text(dump, encoding="utf-8")
        # 第二步:对静态页面打印(不再有异步内容)。
        out.unlink(missing_ok=True)
        run_chrome(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={tmp}/profile2",
                "--run-all-compositor-stages-before-draw",
                "--no-pdf-header-footer",
                f"--print-to-pdf={out.resolve()}",
                static_path.resolve().as_uri(),
            ],
            wait_for=out,
        )
        if not out.exists() or out.stat().st_size == 0:
            print("Chrome 未生成 PDF", file=sys.stderr)
            return 1
    print(f"已生成 {out}({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
