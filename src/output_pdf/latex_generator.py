import json
import os
import re
import subprocess
from typing import Dict, List, Tuple

LATEX_TEMPLATE = r"""
\documentclass[conference]{IEEEtran}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{cite}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{algorithmic}
\usepackage{graphicx}
\usepackage{float}
\usepackage{textcomp}
\usepackage{xcolor}
\usepackage{url}
\usepackage{microtype}
\usepackage[hidelinks]{hyperref}
\begin{document}

\title{%TITLE%}
\author{%AUTHOR%}
\maketitle

\begin{abstract}
%ABSTRACT%
\end{abstract}

\begin{IEEEkeywords}
%KEYWORDS%
\end{IEEEkeywords}

%SECTIONS%

\begin{thebibliography}{99}
%BIBITEMS%
\end{thebibliography}

\end{document}
"""

def latex_escape(s: str) -> str:
    if s is None:
        return ""
    # Special LaTeX characters
    repl = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    # Common accented characters → LaTeX sequences so they survive pdflatex
    accents = {
        "à": r"\`{a}", "á": r"\'{a}", "â": r"\^{a}", "ä": r'\"{a}', "ã": r"\~{a}",
        "è": r"\`{e}", "é": r"\'{e}", "ê": r"\^{e}", "ë": r'\"{e}',
        "ì": r"\`{i}", "í": r"\'{i}", "î": r"\^{i}", "ï": r'\"{i}',
        "ò": r"\`{o}", "ó": r"\'{o}", "ô": r"\^{o}", "ö": r'\"{o}', "õ": r"\~{o}",
        "ù": r"\`{u}", "ú": r"\'{u}", "û": r"\^{u}", "ü": r'\"{u}',
        "ñ": r"\~{n}", "ç": r"\c{c}", "ß": r"\ss{}",
        "À": r"\`{A}", "Á": r"\'{A}", "Â": r"\^{A}", "Ä": r'\"{A}',
        "È": r"\`{E}", "É": r"\'{E}", "Ê": r"\^{E}", "Ë": r'\"{E}',
        "Ì": r"\`{I}", "Í": r"\'{I}", "Î": r"\^{I}", "Ï": r'\"{I}',
        "Ò": r"\`{O}", "Ó": r"\'{O}", "Ô": r"\^{O}", "Ö": r'\"{O}',
        "Ù": r"\`{U}", "Ú": r"\'{U}", "Û": r"\^{U}", "Ü": r'\"{U}',
        "Ñ": r"\~{N}", "Ç": r"\c{C}",
        "\u2013": "--", "\u2014": "---",   # en/em dash
        "\u2018": "`", "\u2019": "'",       # curly single quotes
        "\u201c": "``", "\u201d": "''",     # curly double quotes
        "\u2026": r"\ldots{}",              # ellipsis
    }
    result = []
    for ch in s:
        if ch in repl:
            result.append(repl[ch])
        elif ch in accents:
            result.append(accents[ch])
        elif ord(ch) > 127:
            # Unknown non-ASCII — drop silently rather than breaking LaTeX
            result.append("?")
        else:
            result.append(ch)
    return "".join(result)

def _section_block(title: str, body: str) -> str:
    safe_title = _cleanup_generated_text(title)
    safe_body = _cleanup_generated_text(body)
    # Preserve paragraph breaks in LaTeX body text
    safe_body = re.sub(r"\n{2,}", "\n\n", safe_body)
    return f"\\section{{{latex_escape(safe_title)}}}\n{latex_escape(safe_body)}\n"

def _cleanup_generated_text(text: str) -> str:
    if not text:
        return ""
    cleaned = str(text).strip()
    cleaned = re.sub(r"^```(?:json|latex|text)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.replace("\r\n", "\n")
    # Remove leading JSON braces if model accidentally dumps JSON object text
    cleaned = re.sub(r"^\s*[\{\[]\s*", "", cleaned)
    cleaned = re.sub(r"\s*[\}\]]\s*$", "", cleaned)
    return cleaned.strip()

def _normalize_ref_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"^\s*\[\d+\]\s*", "", str(text).strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(",;")
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned

def _is_incomplete_ref(text: str) -> bool:
    words = text.split()
    if len(words) < 8:
        return True
    # Common truncation marker from broken outputs
    if text.endswith(",") or text.endswith("et al."):
        return True
    return False

def _dedupe_references(refs: List[Dict], max_refs: int = 30) -> List[Dict]:
    deduped = []
    seen = set()

    for ref in refs:
        raw = ref.get("text", "") if isinstance(ref, dict) else str(ref)
        text = _normalize_ref_text(raw)
        if not text or _is_incomplete_ref(text):
            continue

        key = re.sub(r"[^a-z0-9]", "", text.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"text": text})
        if len(deduped) >= max_refs:
            break

    return deduped

def _sanitize_structured(structured: Dict) -> Dict:
    safe = {
        "title": str(structured.get("title", "Untitled") or "Untitled"),
        "author": str(structured.get("author", "Author Name") or "Author Name"),
        "abstract": str(structured.get("abstract", "") or ""),
        "keywords": structured.get("keywords", []),
        "sections": structured.get("sections", []),
        "references": structured.get("references", []),
    }
    if not isinstance(safe["keywords"], list):
        safe["keywords"] = [str(safe["keywords"])]
    safe["keywords"] = [_cleanup_generated_text(k) for k in safe["keywords"] if str(k).strip()]

    if isinstance(safe["author"], list):
        safe["author"] = ", ".join(str(a) for a in safe["author"] if a)
    safe["author"] = _cleanup_generated_text(safe["author"]) or "Author Name"
    safe["title"] = _cleanup_generated_text(safe["title"]) or "Untitled"
    safe["abstract"] = _cleanup_generated_text(safe["abstract"])

    if not isinstance(safe["sections"], list):
        safe["sections"] = []
    normalized_sections = []
    for sec in safe["sections"]:
        if not isinstance(sec, dict):
            continue
        sec_title = _cleanup_generated_text(sec.get("title", "Section"))
        sec_content = _cleanup_generated_text(sec.get("content", ""))
        if sec_content:
            normalized_sections.append({"title": sec_title or "Section", "content": sec_content})
    safe["sections"] = normalized_sections[:20]

    if not safe["sections"]:
        safe["sections"] = [
            {
                "title": "Introduction",
                "content": "No section content was generated.",
            }
        ]

    if not isinstance(safe["references"], list):
        safe["references"] = []

    safe["references"] = _dedupe_references(safe["references"])
    if not safe["references"]:
        safe["references"] = [{"text": "References unavailable from generated output."}]
    return safe

def _bibitems(refs: List[Dict]) -> str:
    items = []
    for i, r in enumerate(refs, 1):
        key = f"ref{i}"
        txt = r.get("text", f"Source {i}")
        items.append(f"\\bibitem{{{key}}} {latex_escape(txt)}")
    return "\n".join(items)

def render_ieee_tex(structured: Dict) -> str:
    structured = _sanitize_structured(structured)
    sections = "".join(
        _section_block(s.get("title", "Section"), s.get("content", ""))
        for s in structured.get("sections", [])
    )
    return (
        LATEX_TEMPLATE
        .replace("%TITLE%", latex_escape(structured.get("title", "Untitled")))
        .replace("%AUTHOR%", latex_escape(structured.get("author", "Author Name")))
        .replace("%ABSTRACT%", latex_escape(structured.get("abstract", "")))
        .replace("%KEYWORDS%", latex_escape(", ".join(structured.get("keywords", []))))
        .replace("%SECTIONS%", sections)
        .replace("%BIBITEMS%", _bibitems(structured.get("references", [])))
    )

def compile_tex(tex_path: str) -> Tuple[bool, str]:
    cwd = os.path.dirname(tex_path)
    name = os.path.basename(tex_path)
    cmd = ["pdflatex", "-interaction=nonstopmode", name]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    ok = p.returncode == 0
    log = (p.stdout or "")[-3000:] + "\n" + (p.stderr or "")[-3000:]
    return ok, log.strip()

def generate_ieee_latex_pdf(structured: Dict, output_dir: str, filename: str) -> Dict:
    os.makedirs(output_dir, exist_ok=True)
    tex = render_ieee_tex(structured)
    tex_path = os.path.join(output_dir, f"{filename}.tex")
    with open(tex_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(tex)

    ok, log = compile_tex(tex_path)
    pdf_path = os.path.join(output_dir, f"{filename}.pdf")
    return {
        "ok": ok and os.path.exists(pdf_path),
        "pdf_path": pdf_path if os.path.exists(pdf_path) else None,
        "tex_path": tex_path,
        "compile_log": log,
    }
