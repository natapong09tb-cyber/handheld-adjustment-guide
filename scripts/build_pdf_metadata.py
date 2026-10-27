"""Apply approved footer using guide-metadata.json and immutable logo PDF baseline.

No network, publication or controller operations. Reruns start from the same
baseline, never from previously stamped output. --baseline-dir supports an
already verified source archive when Git history is unavailable.
"""
import argparse, hashlib, io, json, subprocess
from datetime import date
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
ROOT = Path(__file__).resolve().parents[1]
BASELINE = '0e1097253d962d47fd2e1a5a73d2d57d033f4960'
SOURCES = {
 'TH': (43, '01940b5515cd5cb80e615c270e62bed29f92f7ec70aafcddfeaf5be1fda529c0'),
 'EN': (45, '7528d298dd9e49ddd33cc3b6b775e373198dbc6ebff809e85fef09e77bd870ce'),
 'JA': (44, '05f1ee34eedc6b796e117b4fb05ef836fc1e584a0c3c901b38b79db90a48b567')}
def footer_text(meta):
 d = date.fromisoformat(meta['updated'])
 months = ('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')
 return f"Guide Rev. R{meta['revision']}  |  Updated {d.day} {months[d.month-1]} {d.year}  |  Reference System: {meta['referenceSystemVersion']}"
def remove_page_number(page, number):
 content = page.get_contents(); ops = content.operations; remove=[]; start=None
 for i,(args,op) in enumerate(ops):
  if op == b'BT': start=i
  if op == b'ET' and start is not None:
   block=ops[start:i+1]
   low=any(o==b'Tm' and 760<float(a[4])<800 and 10<float(a[5])<16 for a,o in block)
   if low:
    texts=[str(v) for a,o in block if o==b'TJ' for v in a[0] if isinstance(v,str)]
    assert texts==[str(number)], (number,texts)
    remove.append((start,i+1))
   start=None
 assert len(remove)==1, (number,remove)
 a,b=remove[0]; content.operations=ops[:a]+ops[b:]; page.replace_contents(content)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--baseline-dir',type=Path);args=ap.parse_args()
 meta=json.loads((ROOT/'guide-metadata.json').read_text()); label=footer_text(meta)
 for lang,(count,digest) in SOURCES.items():
  name=f'Handheld_Adjustment_Guide_R12_A4_{lang}.pdf'
  data=(args.baseline_dir/name).read_bytes() if args.baseline_dir else subprocess.check_output(['git','show',f'{BASELINE}:{name}'],cwd=ROOT)
  assert hashlib.sha256(data).hexdigest()==digest, 'Unexpected PDF baseline'
  r=PdfReader(io.BytesIO(data)); assert len(r.pages)==count
  w=PdfWriter();w.clone_document_from_reader(r)
  for n,p in enumerate(w.pages,1):
   remove_page_number(p,n)
   width,height=float(p.mediabox.width),float(p.mediabox.height)
   stream=io.BytesIO();c=Canvas(stream,pagesize=(width,height),invariant=1)
   c.setFont('Helvetica',8);c.setFillColorRGB(82/255,104/255,122/255)
   # Reset inherited text spacing explicitly; baseline body uses tracked text.
   from reportlab.pdfbase.pdfmetrics import stringWidth
   for x,text in [(28,label),(width-28-stringWidth(f'Page {n} of {count}','Helvetica',8),f'Page {n} of {count}')]:
    t=c.beginText(x,13.446474);t.setFont('Helvetica',8)
    t.setCharSpace(0);t.setWordSpace(0);t.setHorizScale(100)
    t.textOut(text);c.drawText(t)
   c.save();p.merge_page(PdfReader(stream).pages[0])
  with (ROOT/name).open('wb') as f:w.write(f)
  print(lang,count,hashlib.sha256((ROOT/name).read_bytes()).hexdigest())
if __name__=='__main__':main()
