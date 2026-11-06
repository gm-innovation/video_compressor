#!/usr/bin/env python3
"""Gera o PDF de um plano em markdown com a marca LECSOR (A4, Chrome headless).

Uso: python tools/gerar-pdf-plano.py <plano.md> <titulo> <kicker> <meta> <badge> <saida.pdf>
"""
import base64, subprocess, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
TEMPLATE = RAIZ / "tools" / "pdf-template.html"
LOGO = Path.home() / "lecsor-site" / "src" / "assets" / "logo-lecsor-white.png"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CSS = (RAIZ / "tools" / "css-plano.css")

def converter(md: str) -> str:
    import markdown
    return markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])

def main() -> int:
    md_path, titulo, kicker, meta, badge, saida = sys.argv[1:7]
    corpo = converter(Path(md_path).read_text(encoding="utf-8"))
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("{{CSS}}", CSS.read_text(encoding="utf-8"))
            .replace("{{LOGO}}", base64.b64encode(LOGO.read_bytes()).decode())
            .replace("{{TITULO}}", titulo).replace("{{KICKER}}", kicker)
            .replace("{{META}}", meta).replace("{{BADGE}}", badge)
            .replace("{{CORPO}}", corpo))
    tmp = Path(saida).with_suffix(".html")
    tmp.write_text(html, encoding="utf-8")
    subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={saida}", tmp.as_uri()], check=True, capture_output=True)
    from pypdf import PdfReader
    n = len(PdfReader(saida).pages)
    print(f"{saida}: {n} pagina(s) | html fonte: {tmp}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
