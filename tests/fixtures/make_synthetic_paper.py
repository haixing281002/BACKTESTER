# Quant AI Researcher
"""Writes tests/fixtures/synthetic_paper.pdf: a small, made-up research paper for tests that only need A paper.

Real papers are third-party and are not kept in git. This one is invented text with no real results; it exists so the
suite runs on a fresh clone. Run: python tests/fixtures/make_synthetic_paper.py
"""
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "synthetic_paper.pdf")
SIGNATURE = "Quant AI Researcher"


def build(path: str = OUT) -> str:
    st = getSampleStyleSheet()
    body = [
        Paragraph("A Synthetic Momentum Study for Testing (not a real paper)", st["Title"]),
        Paragraph(SIGNATURE, st["Normal"]),
        Spacer(1, 12),
        Paragraph("Abstract", st["Heading2"]),
        Paragraph("This document is invented test material. It describes a monthly cross-sectional momentum "
                  "rule on a hypothetical equity universe. No number in it is a real result.", st["Normal"]),
        Paragraph("1. Introduction", st["Heading2"]),
        Paragraph("We rank stocks on past twelve-month return, skipping the latest month, and hold the top decile "
                  "equally weighted, rebalanced monthly.", st["Normal"]),
        Paragraph("2. Data", st["Heading2"]),
        Paragraph("A hypothetical universe of 500 stocks, daily prices, 2010 to 2020.", st["Normal"]),
        Paragraph("3. Results", st["Heading2"]),
        Table([["Portfolio", "Return (made up)", "Volatility (made up)"],
               ["Top decile", "1.0%", "5.0%"], ["Bottom decile", "0.2%", "6.0%"]]),
        Paragraph("References", st["Heading2"]),
        Paragraph("None. This is synthetic test material.", st["Normal"]),
    ]

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 40, 20, SIGNATURE)

    SimpleDocTemplate(path, pagesize=A4, title="Synthetic test paper", author=SIGNATURE,
                      creator=SIGNATURE).build(body, onFirstPage=footer, onLaterPages=footer)
    return path


if __name__ == "__main__":
    print(build())
