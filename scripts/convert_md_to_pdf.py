from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import re

with open('.nova/research/joji-artist-profile/final_report.md', 'r', encoding='utf-8') as f:
    md_content = f.read()

doc = SimpleDocTemplate(
    '.nova/research/joji-artist-profile/final_report.pdf',
    pagesize=letter,
    rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18
)

styles = getSampleStyleSheet()

title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=24, textColor=colors.HexColor('#1a1a2e'), spaceAfter=30, alignment=1)
heading1_style = ParagraphStyle('CustomH1', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#16213e'), spaceAfter=12, spaceBefore=20)
heading2_style = ParagraphStyle('CustomH2', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#0f3460'), spaceAfter=10, spaceBefore=15)
body_style = ParagraphStyle('CustomBody', parent=styles['BodyText'], fontSize=10, leading=14, spaceAfter=8, alignment=4)
meta_style = ParagraphStyle('MetaStyle', parent=styles['BodyText'], fontSize=9, textColor=colors.grey, alignment=1, spaceAfter=20)
bullet_style = ParagraphStyle('BulletStyle', parent=styles['BodyText'], fontSize=10, leading=14, leftIndent=20, spaceAfter=6, bulletIndent=10)

story = []
lines = md_content.split('\n')
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.strip()
    
    if stripped.startswith('# ') and not stripped.startswith('## '):
        story.append(Paragraph(stripped[2:], title_style))
        story.append(Spacer(1, 10))
    elif stripped.startswith('**Query:**') or stripped.startswith('**Date:**') or stripped.startswith('**Confidence:**'):
        story.append(Paragraph(f'<i>{stripped.replace("**", "")}</i>', meta_style))
    elif stripped == '---':
        story.append(Spacer(1, 15))
    elif stripped.startswith('## '):
        story.append(Paragraph(stripped[3:], heading1_style))
    elif stripped.startswith('### '):
        story.append(Paragraph(stripped[4:], heading2_style))
    elif stripped.startswith('- '):
        text = stripped[2:]
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
        story.append(Paragraph(f'• {text}', bullet_style))
    elif stripped:
        text = stripped
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
        story.append(Paragraph(text, body_style))
    else:
        story.append(Spacer(1, 6))
    i += 1

doc.build(story)
print('PDF created successfully at: .nova/research/joji-artist-profile/final_report.pdf')
