"""Render synthetic PDF acceptance cases outside the repository (optional QA)."""
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile

import ezdxf
from PIL import Image, ImageOps, ImageDraw
from pypdf import PdfReader

from app.pdf_report import generate_pdf
from app.main import REVIEW_SNAPSHOTS
from app.review_snapshot import StudentMetadata
from tests.test_pdf_export import _approve, _review, _image_xobjects
from tests.test_review_usability_repairs import basic_snapshot, evidence_snapshot


def shaped_snapshot(width, height):
    document = ezdxf.new('R2010')
    document.units = 4
    model = document.modelspace()
    model.add_lwpolyline([(0,0),(width,0),(width,height),(0,height)],close=True)
    for n in range(1,20):
        model.add_line((width*n/20,0),(width*n/20,height))
    stream = io.StringIO()
    document.write(stream)
    data = stream.getvalue().encode()
    _, rubric = _approve(data)
    result = _review(data,data,data={'rubric_id':rubric['rubric_id']})
    assert result.status_code == 200
    return REVIEW_SNAPSHOTS.get(result.json()['review_id'])


def main():
    destination = Path(tempfile.mkdtemp(prefix='draftlens-pdf-qa-'))
    basic = basic_snapshot()
    response = basic.review_response
    response['unsupported_entities'] = {'reference':[], 'student':[
        {'entity_type':'HATCH','source':'student','layer':'SYNTHETIC','handle':f'QA-{n}'} for n in range(20)]}
    response['finding_counts']['unsupported_entities']=20
    warnings = replace(basic,review_response_json=json.dumps(response))
    long_metadata = replace(basic,assignment_title='Synthetic assignment '*8,
                            student_metadata=StudentMetadata('Synthetic student '*7,'QA-'+'x'*60,'Synthetic course '*7))
    cases = [('standard',basic,False),('dense-evidence',evidence_snapshot(),False),
             ('wide',shaped_snapshot(1000,20),False),('tall',shaped_snapshot(20,1000),False),
             ('warnings',warnings,False),('appendix',warnings,True),('long-metadata',long_metadata,False)]
    summaries=[]
    for name,snapshot,appendix in cases:
        data=generate_pdf(snapshot,include_appendix=appendix)
        assert data==generate_pdf(snapshot,include_appendix=appendix)
        reader=PdfReader(io.BytesIO(data))
        assert _image_xobjects(reader)==[]
        text='\n'.join(page.extract_text() for page in reader.pages)
        assert 'Drawing overlay legend' in text
        if name in {'warnings','appendix'}:
            assert 'not automatically assessed' in reader.pages[0].extract_text()
        target=destination/f'{name}.pdf'
        target.write_bytes(data)
        subprocess.run([os.environ.get('DRAFTLENS_PDFTOPPM','pdftoppm'),'-r','90','-png',str(target),str(destination/name)],check=True,stdout=subprocess.DEVNULL)
        pages=sorted(destination.glob(name+'-*.png'),key=lambda p:int(p.stem.rsplit('-',1)[1]))
        for offset in range(0,len(pages),4):
            sheet=Image.new('RGB',(1500,2160),'#cbd5d1')
            draw=ImageDraw.Draw(sheet)
            for idx,page in enumerate(pages[offset:offset+4]):
                with Image.open(page) as image:
                    thumb=ImageOps.contain(image,(740,1040))
                    x=(idx%2)*750;y=(idx//2)*1080
                    draw.text((x+8,y+5),page.name,fill='black')
                    sheet.paste(thumb,(x+5,y+25))
            sheet.save(destination/f'{name}-contact-{offset//4+1}.png')
        summaries.append({'case':name,'pages':len(reader.pages),'vector':True,'deterministic':True})
    print(json.dumps({'directory':str(destination),'cases':summaries},indent=2))


if __name__=='__main__':
    main()
