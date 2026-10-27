"""Verify every approved footer and unchanged page area using Poppler raster QA."""
import argparse, hashlib, json, subprocess
from pathlib import Path
import fitz
import numpy as np
from PIL import Image, ImageDraw
from build_pdf_metadata import ROOT,SOURCES,BASELINE,footer_text

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--baseline-dir',type=Path);ap.add_argument('--review-dir',type=Path,default=ROOT.parent/'pdf-footer-review');a=ap.parse_args()
 a.review_dir.mkdir(parents=True,exist_ok=True)
 if a.baseline_dir is None:
  a.baseline_dir=a.review_dir/'baseline-source';a.baseline_dir.mkdir(exist_ok=True)
  for lang in SOURCES:
   name=f'Handheld_Adjustment_Guide_R12_A4_{lang}.pdf'
   (a.baseline_dir/name).write_bytes(subprocess.check_output(['git','show',f'{BASELINE}:{name}'],cwd=ROOT))
 meta=json.loads((ROOT/'guide-metadata.json').read_text()); label=footer_text(meta); results={}
 for lang,(count,digest) in SOURCES.items():
  name=f'Handheld_Adjustment_Guide_R12_A4_{lang}.pdf'; src=a.baseline_dir/name;dst=ROOT/name
  assert hashlib.sha256(src.read_bytes()).hexdigest()==digest
  old=fitz.open(src);new=fitz.open(dst);assert len(old)==len(new)==count
  entries=[]
  for i,(p,q) in enumerate(zip(old,new),1):
   assert p.rect==q.rect
   oldbody=p.get_text(clip=fitz.Rect(0,0,p.rect.width,570))
   newbody=q.get_text(clip=fitz.Rect(0,0,q.rect.width,570))
   assert oldbody==newbody,(lang,i,'body text changed')
   ft=q.get_text(clip=fitz.Rect(0,570,q.rect.width,q.rect.height))
   assert ft.strip().splitlines()==[label,f'Page {i} of {count}'],(lang,i,ft)
   entries.append({'page':i,'footer_text_exact':True,'body_text_unchanged':True})
  renderdir=a.review_dir/lang;renderdir.mkdir(exist_ok=True)
  for kind,path in [('baseline',src),('result',dst)]:
   subprocess.run(['pdftoppm','-r','96','-png',str(path),str(renderdir/kind)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  for i,e in enumerate(entries,1):
   oldim=Image.open(renderdir/f'baseline-{i:02}.png').convert('RGB');im=Image.open(renderdir/f'result-{i:02}.png').convert('RGB')
   pix1=np.asarray(oldim);pix2=np.asarray(im);cut=760 # 570pt at96dpi, below original footer line
   assert np.array_equal(pix1[:cut],pix2[:cut]),(lang,i,'pixels changed above footer')
   e['pixels_above_y570_identical']=True
  for start in range(1,count+1,9):
   sheet=Image.new('RGB',(1350,1020),'#e9eef2');draw=ImageDraw.Draw(sheet)
   for off,i in enumerate(range(start,min(count+1,start+9))):
    im=Image.open(renderdir/f'result-{i:02}.png');im.thumbnail((440,312));x=(off%3)*450;y=(off//3)*340
    sheet.paste(im,(x,y+20));draw.text((x+5,y+3),f'{lang} {i}/{count}',fill='black')
   sheet.save(renderdir/f'contact-{start:02}.jpg',quality=90)
  # Native scale footer strips show legibility and numbering for all pages.
  for start in range(1,count+1,15):
   sheet=Image.new('RGB',(1123,45*min(15,count-start+1)),'white');draw=ImageDraw.Draw(sheet)
   for off,i in enumerate(range(start,min(count+1,start+15))):
    im=Image.open(renderdir/f'result-{i:02}.png');sheet.paste(im.crop((0,755,im.width,im.height)),(0,off*45))
   sheet.save(renderdir/f'footers-{start:02}.png')
  results[lang]={'pages':count,'sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'checks':entries}
  print(lang,'PASS',flush=True)
 (a.review_dir/'verification.json').write_text(json.dumps(results,indent=2))
 print('All132pages passed')
if __name__=='__main__':main()
