"""A typeset reading edition from saved final prose; no model rewrites."""
import hashlib
import json
from pathlib import Path
import re
from xml.sax.saxutils import escape


def build_pdf(job):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether
    import reportlab
    from audiobook import studio_data
    # During formatting the book is still running. Read the exact same final
    # chapters directly, rather than relaxing the studio's completed-book gate.
    job = Path(job)
    memory = job / '08_Memory'
    metadata = json.loads((memory / 'metadata.json').read_text(encoding='utf-8'))
    pipeline = json.loads((memory / 'pipeline_state.json').read_text(encoding='utf-8'))
    chapters = [json.loads((memory / f'chapter_{n:02d}.json').read_text(encoding='utf-8'))
                for n in range(1, pipeline['total_chapters'] + 1)]
    if not chapters or any(not isinstance(c.get('prose_content'), str) or not c['prose_content'].strip() for c in chapters):
        raise ValueError('PDF requires all final chapter prose.')
    identity = hashlib.sha256(json.dumps([metadata, chapters], sort_keys=True).encode()).hexdigest()
    output = memory / 'manuscript.pdf'
    stamp = memory / 'pdf.json'
    if output.exists() and stamp.exists() and json.loads(stamp.read_text())['fingerprint'] == identity:
        return output
    font_paths = [Path('C:/Windows/Fonts/georgia.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'),
                  Path(reportlab.__file__).parent / 'fonts/Vera.ttf']
    font = next(p for p in font_paths if p.exists())
    if 'AthenaBook' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('AthenaBook', str(font)))
    ink, accent, muted = colors.HexColor('#292524'), colors.HexColor('#9a3412'), colors.HexColor('#78716c')
    body = ParagraphStyle('Prose', fontName='AthenaBook', fontSize=11, leading=17.5,
                          textColor=ink, alignment=TA_JUSTIFY, spaceAfter=11, allowWidows=0, allowOrphans=0)
    title = ParagraphStyle('Title', fontName='AthenaBook', fontSize=30, leading=39, alignment=TA_CENTER, textColor=ink)
    heading = ParagraphStyle('Chapter', fontName='AthenaBook', fontSize=23, leading=31, textColor=ink, spaceAfter=22)
    small = ParagraphStyle('Label', fontName='Helvetica', fontSize=8.5, leading=14, textColor=accent,
                           alignment=TA_CENTER, spaceAfter=20)
    scene = ParagraphStyle('Scene', parent=small, textColor=muted, spaceBefore=15, spaceAfter=15)
    contents = ParagraphStyle('Contents', fontName='AthenaBook', fontSize=12, leading=22, textColor=ink, spaceAfter=9)
    parts = [Spacer(1, 85), Paragraph('A T H E N A   E D I T I O N S', small), Spacer(1, 34),
             Paragraph(escape(metadata['title']), title), Spacer(1, 28),
             Paragraph('THE READING EDITION', small)]
    if metadata.get('blurb'):
        blurb = ParagraphStyle('Blurb', parent=body, fontSize=10, leading=16, alignment=TA_CENTER, textColor=muted)
        parts.extend([Spacer(1, 28), Paragraph(escape(metadata['blurb']), blurb)])
    parts.extend([PageBreak(), Paragraph('Contents', heading)])
    for number, chapter in enumerate(chapters, 1):
        parts.append(Paragraph(f'<link href="#chapter-{number}" color="#9a3412">{number:02d} &nbsp; {escape(chapter.get("title") or f"Chapter {number}")}</link>', contents))
    for number, chapter in enumerate(chapters, 1):
        parts.extend([PageBreak(), Spacer(1, 28), Paragraph(f'<a name="chapter-{number}"/>CHAPTER {number:02d}', small),
                      Paragraph(escape(chapter.get('title') or f'Chapter {number}'), heading)])
        for paragraph in re.split(r'\n\s*\n', chapter['prose_content'].strip()):
            if re.fullmatch(r'#{1,6}\s+[^\n]+', paragraph.strip()):
                parts.append(Paragraph(escape(re.sub(r'^#+\s+', '', paragraph.strip())), scene))
            else:
                parts.append(Paragraph(escape(paragraph).replace('\n', '<br/>'), body))
    def page(canvas, document):
        canvas.saveState()
        width, height = document.pagesize
        if document.page == 1:
            canvas.setStrokeColor(accent); canvas.setLineWidth(.7)
            canvas.rect(27, 27, width-54, height-54)
        else:
            canvas.setFont('Helvetica', 7.5); canvas.setFillColor(muted)
            short = metadata['title']
            while canvas.stringWidth(short, 'Helvetica', 7.5) > width-110:
                short = short[:-4] + '…'
            canvas.drawCentredString(width/2, height-31, short)
            canvas.setStrokeColor(colors.HexColor('#e7e2da')); canvas.setLineWidth(.4)
            canvas.line(50, 44, width-50, 44)
            canvas.drawCentredString(width/2, 29, str(document.page))
        canvas.restoreState()
    temporary = output.with_suffix('.pdf.tmp')
    try:
        document = SimpleDocTemplate(str(temporary), pagesize=(432, 648), rightMargin=51, leftMargin=51,
            topMargin=56, bottomMargin=60, title=metadata['title'], author='Athena Editions',
            pageCompression=1, allowSplitting=1)
        document.build(parts, onFirstPage=page, onLaterPages=page)
        temporary.replace(output)
        from job_runner import atomic_json
        atomic_json(stamp, {'fingerprint': identity, 'pages': document.page, 'format': '6 × 9 inch reading edition'})
    finally:
        temporary.unlink(missing_ok=True)
    return output
