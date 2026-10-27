"""Generate the website's English metadata from one shared JSON source."""
from pathlib import Path
import json,re,datetime
ROOT=Path(__file__).resolve().parents[1]
m=json.loads((ROOT/'guide-metadata.json').read_text())
d=datetime.date.fromisoformat(m['updated'])
months=('January','February','March','April','May','June','July','August','September','October','November','December')
short=f'{d.day} {months[d.month-1][:3]} {d.year}'; full=f'{d.day} {months[d.month-1]} {d.year}'
p=ROOT/'index.html';s=p.read_text()
compact=f'Rev. {m["revision"]} · Upd. {short}'
head=f'<span id="guide-revision" lang="en">{compact}</span>'
if 'id="guide-revision"' in s:s=re.sub(r'<span id="guide-revision"[^>]*>.*?</span>',head,s)
else:s=s.replace('alt="CROBOTP"></div>','alt="CROBOTP">'+head+'</div>',1)
footer=f'''<footer id="guide-metadata" lang="en" aria-label="Guide publication information"><span>Guide Revision: <strong>{m['revision']}</strong></span><span>Last Updated: <time datetime="{m['updated']}">{full}</time></span><span>Reference System Version: <strong>{m['referenceSystemVersion']}</strong></span></footer>'''
if 'id="guide-metadata"' in s:s=re.sub(r'<footer id="guide-metadata".*?</footer>',footer,s)
else:s=s.replace('</main>','</main>'+footer,1)
css='''<style id="guide-metadata-style">
header#top .logos{gap:clamp(5px,1.7vw,12px)}
header#top #guide-revision{margin-left:auto;color:#16475b;font-family:Arial,sans-serif;font-size:clamp(7px,1.9vw,12px);font-weight:400;line-height:1.2;white-space:nowrap;flex:0 0 auto}
#guide-metadata{max-width:1100px;margin:24px auto 0;padding:16px 12px 22px;border-top:1px solid #c7dbe3;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px 24px;color:#496875;font:12px/1.6 Arial,sans-serif}
#guide-metadata strong{font-weight:600}
@media(max-width:420px){header#top .logos img[alt="DENSO"]{width:22%;max-width:66px}header#top .logos img[alt="CROBOTP"]{width:31%;max-width:92px}}
@media(max-width:520px){#guide-metadata{flex-direction:column;gap:4px}}
</style>'''
if 'id="guide-metadata-style"' in s:s=re.sub(r'<style id="guide-metadata-style">.*?</style>',css,s,flags=re.S)
else:s=s.replace('</head>',css+'</head>',1)
p.write_text(s)
print(compact, '\n',footer)
