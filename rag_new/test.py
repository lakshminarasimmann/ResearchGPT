import shutil
print(shutil.which("pdflatex"))

from src.output_pdf.pdf_generator import generate_ieee_pdf
print(generate_ieee_pdf)
