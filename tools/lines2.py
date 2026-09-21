import xml.etree.ElementTree as ET, json, sys, os, re
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
A='{http://schemas.openxmlformats.org/drawingml/2006/main}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
OPT=re.compile(r'^\s*([АAБВBСCДDЕEФF])\s*[\.\)]\s*')

def rels(base):
    m={}; p=os.path.join(base,'word','_rels','document.xml.rels')
    if os.path.exists(p):
        for e in ET.parse(p).getroot(): m[e.get('Id')]=e.get('Target')
    return m

def extract(base):
    rel=rels(base)
    body=ET.parse(os.path.join(base,'word','document.xml')).getroot().find(W+'body')
    out=[]
    for p in body.iter(W+'p'):
        ppr=p.find(W+'pPr'); numid=None
        if ppr is not None:
            np=ppr.find(W+'numPr')
            if np is not None:
                n=np.find(W+'numId')
                if n is not None: numid=n.get(W+'val')
        segs=[[]]; imgs=[]
        for r in p.iter(W+'r'):
            rpr=r.find(W+'rPr'); b=False
            if rpr is not None:
                be=rpr.find(W+'b')
                if be is not None and be.get(W+'val') not in ('0','false'): b=True
            for ch in r.iter():
                if ch.tag==W+'t': segs[-1].append((ch.text or '', b))
                elif ch.tag==W+'br': segs.append([])
                elif ch.tag==W+'tab': segs[-1].append(('\t', b))
                elif ch.tag==A+'blip':
                    rid=ch.get(R+'embed')
                    if rid and rid in rel: imgs.append(rel[rid])
        for s in segs:
            full=''.join(x[0] for x in s)
            if not full.strip(): continue
            # character-level bold map
            flags=[]
            for t,b in s: flags.extend([b]*len(t))
            m=OPT.match(full)
            start=m.end() if m else 0
            body_flags=[f for ch,f in zip(full[start:],flags[start:]) if ch.strip()]
            all_flags=[f for ch,f in zip(full,flags) if ch.strip()]
            out.append({'t':full.strip(),
                        'bold_any':any(all_flags),
                        'bold_text':bool(body_flags) and all(body_flags),
                        'bold_text_any':any(body_flags),
                        'n':numid,'img':None})
        for im in imgs:
            out.append({'t':'','bold_any':False,'bold_text':False,'bold_text_any':False,'n':None,'img':im})
    return out

if __name__=='__main__':
    lines=extract(sys.argv[1])
    json.dump(lines, open(sys.argv[2],'w'), ensure_ascii=False, indent=0)
    for i,l in enumerate(lines):
        if l['img']: print(f"{i:3d} IMG | {l['img']}"); continue
        tag = 'TXT-BOLD' if l['bold_text'] else ('part' if l['bold_text_any'] else ('letter' if l['bold_any'] else '    '))
        print(f"{i:3d} {tag:8s} | {l['t'][:95]}")
