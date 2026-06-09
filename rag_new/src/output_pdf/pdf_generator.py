import subprocess
from pathlib import Path
from .latex_template import IEEE_CONFERENCE_TEMPLATE
import re


def sanitize_for_latex(text: str) -> str:
    
    text = re.sub(r'^\s*#+\s*', '', text, flags=re.MULTILINE)
    
    unicode_replacements = {
        "∗": "*",
        "–": "-",
        "—": "-",
        "≤": "<=",
        "≥": ">=",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "•": "-",
        "→": "->",
        "←": "<-",
    }

    for k, v in unicode_replacements.items():
        text = text.replace(k, v)
    
    replacements = {
        '\\': r'\textbackslash{}',
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
    }
    
   
    for char, escaped in replacements.items():
        text = text.replace(char, escaped)
        
    text = text.encode("ascii", "ignore").decode()
    
    return text


def generate_ieee_pdf(
    paper_text: str,
    title: str,
    output_dir="output",
    filename="urop_ieee_paper",
    author_name="Author Name",
    affiliation="Department, University",
    email="email@university.edu"
):
    Path(output_dir).mkdir(exist_ok=True)

    tex_path = Path(output_dir) / f"{filename}.tex"
    pdf_path = Path(output_dir) / f"{filename}.pdf"
    safe_text = sanitize_for_latex(paper_text)

    tex_content = IEEE_CONFERENCE_TEMPLATE.format(
        title=title,
        author_name=author_name,
        affiliation=affiliation,
        email=email,
        content=safe_text
    )

    tex_path.write_text(tex_content, encoding="utf-8")

    try:
        subprocess.run(
            ["pdflatex", "-output-directory", output_dir, tex_path.name],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "pdflatex not found. Install TeX Live or MiKTeX and ensure pdflatex is on PATH."
        )
    except subprocess.CalledProcessError as e:
        log = (e.stdout or b"").decode(errors="replace")[-2000:]
        raise RuntimeError(f"pdflatex compilation failed:\n{log}")

    if not pdf_path.exists():
        raise RuntimeError(f"pdflatex ran but no PDF was produced at {pdf_path}")

    return pdf_path

