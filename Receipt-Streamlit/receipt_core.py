from __future__ import annotations
import base64, datetime as dt, json, re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from portable_backend import ocr, render_source, export_xlsx
DATE = re.compile(r"(?<!\d)(\d{2})[./-](\d{2})[./-](\d{4})(?!\d)")
MONEY = re.compile(r"(?<![\d.,])-?\d+[.,]\d{2}(?!\d)")
KEYS = ("date", "receipt_number", "amount")

def qr_fields(payloads):
    """Read only known Saudi TLV data tags. Never execute document contents."""
    results = []
    for payload in payloads:
        try:
            raw = base64.b64decode(payload, validate=True)
            tags, i = {}, 0
            while i < len(raw):
                tag, size = raw[i:i+2]
                if i+2+size > len(raw): raise ValueError('Truncated TLV')
                if tag in tags: raise ValueError('Duplicate TLV tag')
                tags[tag] = raw[i+2:i+2+size]
                i += size+2
            if not {1,2,3,4,5} <= tags.keys(): continue
            date = dt.datetime.fromisoformat(tags[3].decode().replace('Z','+00:00')).date().isoformat()
            amount = tags[4].decode()
            if not re.fullmatch(r'\d+\.\d{2}', amount): continue
            results.append((date, amount))
        except (ValueError, UnicodeError, InvalidOperation): continue
    return results[0] if len(set(results)) == 1 else None

def parse_page(page, confirmed_amount=None):
    lines = sorted(page.get('lines', []), key=lambda x:x['y'])
    row = dict.fromkeys(KEYS, '')
    reasons = []
    dates = []
    for line in lines:
        for match in DATE.finditer(line['text']):
            try: value = dt.date(int(match[3]),int(match[2]),int(match[1])).isoformat()
            except ValueError: continue
            if line['confidence'] >= .9: dates.append((value,line))
    if len(dates) == 1: row['date'] = dates[0][0]
    # Sample-specific Aldrees layout: one 19-digit invoice below the date.
    # Tax IDs and telephone numbers are deliberately not accepted.
    ids = []
    if len(dates) == 1:
        for line in lines:
            value = line['text'].strip()
            if (re.fullmatch(r'\d{19}', value) and line['confidence'] >= .9
                and 0 < line['y']-dates[0][1]['y'] < .13
                and value[7:11] == row['date'][:4]): ids.append(value)
    if len(ids) == 1: row['receipt_number'] = ids[0]
    qr = qr_fields(page.get('qr', []))
    # Only use the template's final monetary line when preceded by rounding.
    amounts = []
    if row['receipt_number']:
        id_y = next(x['y'] for x in lines if x['text'].strip() == row['receipt_number'])
        for line in lines:
            matches = MONEY.findall(line['text'])
            if id_y < line['y'] < .8 and line['x'] < .45 and len(matches) == 1 and '%' not in line['text']:
                amounts.append((matches[0].replace(',','.'),line))
    candidate = None
    if len(amounts) >= 2:
        last, prior = amounts[-1], amounts[-2]
        if Decimal(last[0]) >= 0 and abs(Decimal(prior[0])) <= Decimal('.05') and 0 < last[1]['y']-prior[1]['y'] < .06:
            candidate = last
    if qr:
        if row['date'] and qr[0] != row['date']:
            row['date'] = ''
            reasons.append('Printed date conflicts with QR date')
        elif not row['date'] and not dates: row['date'] = qr[0]
        if candidate:
            printed = Decimal(candidate[0])
            rounding = Decimal(amounts[-2][0])
            if printed == Decimal(qr[1]) or printed == Decimal(qr[1])+rounding:
                row['amount'] = candidate[0]
            else: reasons.append('Printed amount conflicts with QR amount')
    elif candidate and confirmed_amount == candidate[0]:
        row['amount'] = candidate[0]
    for key in KEYS:
        if not row[key]: reasons.append(f'{key.replace("_", " ").capitalize()} needs review')
    if page.get('error'): reasons.append('OCR error: '+page['error'])
    return row, reasons, candidate

def extract(source, directory):
    directory.mkdir(parents=True, exist_ok=True)
    paths = render_source(source, directory)
    pages = ocr(paths)
    if pages and all(p.get('error') for p in pages):
        raise RuntimeError('OCR failed. Please try a clearer scan. '+pages[0]['error'])
    return finish_extraction(pages, paths, directory)

def finish_extraction(pages, paths, directory):
    from PIL import Image
    crops, indexes = [], []
    for i,page in enumerate(pages):
        row, reasons, candidate = parse_page(page)
        if candidate and not row['amount'] and not qr_fields(page.get('qr', [])):
            number = next((n for n in candidate[1].get('numbers',[]) if n['text'].replace(',','.') == candidate[0]), None)
            if number:
                with Image.open(paths[i]) as im:
                    w,h=im.size
                    x,y,nw,nh = [number[k] for k in ('x','y','w','h')]
                    box=(max(0,int((x-.008)*w)),max(0,int((y-.006)*h)),min(w,int((x+nw+.008)*w)),min(h,int((y+nh+.006)*h)))
                    crop=im.crop(box)
                    crop=crop.resize((crop.width*3,crop.height*3))
                    target=directory/f'amount-{i+1:02}.png'
                    crop.save(target)
                    crops.append(target); indexes.append(i)
    checks = dict(zip(indexes,ocr(crops))) if crops else {}
    records=[]
    for i,page in enumerate(pages):
        confirmed=None
        if i in checks:
            hits=[l['text'].strip().rstrip(':;').strip().replace(',','.') for l in checks[i]['lines'] if l['confidence'] >= .9]
            if len(hits)==1 and re.fullmatch(r'\d+\.\d{2}',hits[0]): confirmed=hits[0]
        row,reasons,_=parse_page(page,confirmed)
        records.append({**row,'page':i+1,'image':Path(paths[i]).name,'reasons':reasons})
    (directory/'ocr.json').write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding="utf-8")
    (directory/'amount-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding="utf-8")
    return records

def validate_rows(rows):
    if not isinstance(rows,list) or not 0 < len(rows) <= 1000: raise ValueError('Expected 1 to 1000 rows')
    clean=[]
    for i,row in enumerate(rows,1):
        result={key:str(row.get(key,'')).strip() for key in KEYS}
        if result['date']:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', result['date']): raise ValueError(f'Row {i}: use YYYY-MM-DD')
            dt.date.fromisoformat(result['date'])
        if result['receipt_number'] and not re.fullmatch(r'[0-9A-Za-z/-]{1,64}',result['receipt_number']):
            raise ValueError(f'Row {i}: invalid receipt number')
        if result['amount']:
            if not re.fullmatch(r'\d{1,10}(?:\.\d{1,2})?',result['amount']): raise ValueError(f'Row {i}: enter a positive amount with up to two decimals')
            result['amount']=f"{Decimal(result['amount']):.2f}"
        clean.append(result)
    return clean

def export_pdf(rows, path):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    body=[['Date','Receipt number','Amount (SAR)']]
    for row in rows:
        date=dt.date.fromisoformat(row['date']).strftime('%d.%m.%Y') if row['date'] else ''
        body.append([date,row['receipt_number'],row['amount']])
    table=Table(body,colWidths=[110,250,110],repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#203950')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),9),('ALIGN',(2,1),(2,-1),'RIGHT'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f0f4f8')])]))
    styles=getSampleStyleSheet()
    SimpleDocTemplate(str(path),title='Receipt register').build([Paragraph('Receipt register',styles['Title']),Paragraph('Blank cells need review. Amounts include VAT.',styles['Normal']),Spacer(1,16),table])

def atomic_json(path,value):
    temp=path.with_suffix('.new')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(path)
