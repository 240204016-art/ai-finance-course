"""docx-тен құрылымдалған тест (questions.json) жасайды."""
import json, re, sys, os, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lines2 import extract

OPT   = re.compile(r'^\s*([АAБВBСCДDЕEФF])\s*[\.\)]\s*(.*)$', re.S)
QNUM  = re.compile(r'^\s*\d{1,2}\s*[\.\)]\s*')
PAIR  = re.compile(r'^(.{2,}?)\s*[\-–—]?\s*([АAБВBСCДD])\s*$')
CANON = {'А':'A','A':'A','Б':'B','В':'B','B':'B','С':'C','C':'C',
         'Д':'D','D':'D','Е':'E','E':'E','Ф':'F','F':'F'}
ORDER = ['A','B','C','D','E','F']
norm  = lambda s: re.sub(r'\s+', ' ', s).strip()

def split_blocks(raw):
    blocks = []
    head, opts, imgs = [], [], []
    def flush():
        if head or opts:
            blocks.append({'head': head[:], 'opts': opts[:], 'imgs': imgs[:]})
        head.clear(); opts.clear(); imgs.clear()

    for i, ln in enumerate(raw):
        if ln['img']:
            imgs.append({'src': ln['img'], 'pos': len(head)})
            continue
        m = OPT.match(ln['t'])
        if m:
            letter = CANON[m.group(1)]
            if opts and ORDER.index(letter) <= ORDER.index(opts[-1]['id']):
                flush()
            opts.append({'id': letter, 'text': norm(m.group(2)), 'bold': ln['bold_text']})
            continue
        if opts:
            nxt = None
            for fut in raw[i+1:]:
                if fut['img']:
                    continue
                fm = OPT.match(fut['t'])
                if fm:
                    nxt = CANON[fm.group(1)]
                break
            if nxt and ORDER.index(nxt) > ORDER.index(opts[-1]['id']):
                opts[-1]['text'] = norm(opts[-1]['text'] + ' ' + ln['t'])
                continue
            flush()
        head.append({'t': norm(ln['t']), 'bold': ln['bold_text']})
    flush()
    return [b for b in blocks if b['opts']]

def build(docx_dir, title, slug, asset_dir, asset_url_prefix):
    raw       = extract(docx_dir)
    blocks    = split_blocks(raw)
    questions = []
    warnings  = []
    ctx_carry = None

    for b in blocks:
        heads, opts = b['head'], b['opts']
        pos = {o['id']: k for k, o in enumerate(opts)}
        n   = len(questions) + 1

        stripped = [QNUM.sub('', h['t'], count=1) for h in heads]

        def is_pair(s):
            m = PAIR.match(s)
            return m if (m and CANON.get(m.group(2)) in pos) else None

        start = len(stripped)
        while start > 0 and is_pair(stripped[start - 1]):
            start -= 1
        pair_run = list(range(start, len(stripped)))
        has_hdr  = any('әйкестендір' in h['t'] for h in heads)
        is_match = len(pair_run) >= 2 or has_hdr

        q = {'n': n}
        ctx_lines = []

        if is_match:
            if len(pair_run) < 2 and has_hdr:
                hdr = next(k for k, h in enumerate(heads) if 'әйкестендір' in h['t'])
                pair_run = list(range(hdr + 1, len(stripped)))
            items = []
            for k in pair_run:
                m = is_pair(stripped[k])
                if not m:
                    warnings.append(f"{slug} Q{n}: жұп танылмады: {stripped[k]!r}")
                    continue
                label = re.sub(r'[\s\-–—]+$', '', m.group(1)).strip()
                items.append({'text': label, 'answer': CANON[m.group(2)]})
            if len(items) != 2:
                warnings.append(f"{slug} Q{n}: сәйкестендіруде {len(items)} жұп")
            q.update({'type': 'match', 'q': 'Сәйкестендір', 'items': items, 'points': 2})
        else:
            qline   = heads[-1]['t'] if heads else ''
            correct = [o['id'] for o in opts if o['bold']]
            if not correct:
                warnings.append(f"{slug} Q{n}: дұрыс жауап белгіленбеген — {qline[:60]!r}")
            if len(correct) >= 2:
                q.update({'type': 'multi', 'q': norm(QNUM.sub('', qline, count=1)),
                          'answer': correct, 'points': 2})
            else:
                q.update({'type': 'single', 'q': norm(QNUM.sub('', qline, count=1)),
                          'answer': correct[0] if correct else None, 'points': 1})
            ctx_lines = [h['t'] for h in heads[:-1]]

        q['options'] = [{'id': o['id'], 'text': o['text']} for o in opts]

        q_imgs, c_imgs = [], []
        for im in b['imgs']:
            if ctx_lines and im['pos'] < len(heads) - 1:
                c_imgs.append(im['src'])
            elif ctx_lines and im['pos'] == len(heads) - 1:
                c_imgs.append(im['src'])
            else:
                q_imgs.append(im['src'])

        if ctx_lines:
            ctx_carry = {'title': ctx_lines[0], 'body': ' '.join(ctx_lines[1:]),
                         'images': c_imgs}
        if q['type'] == 'single' and ctx_carry:
            q['context'] = ctx_carry
        elif q['type'] != 'single':
            ctx_carry = None
        if q_imgs:
            q['images'] = q_imgs
        questions.append(q)

    os.makedirs(asset_dir, exist_ok=True)
    mapping = {}

    def relocate(src):
        if src not in mapping:
            ext  = os.path.splitext(src)[1] or '.png'
            name = f"{slug}-{len(mapping) + 1}{ext}"
            shutil.copy(os.path.join(docx_dir, 'word', src.replace('/', os.sep)),
                        os.path.join(asset_dir, name))
            mapping[src] = f"{asset_url_prefix}{name}"
        return mapping[src]

    for q in questions:
        if q.get('images'):
            q['images'] = [relocate(s) for s in q['images']]
        c = q.get('context')
        if c:
            imgs = [relocate(s) for s in c.get('images', [])]
            q['context'] = {'title': c['title'], 'body': c['body']}
            if imgs:
                q['context']['images'] = imgs

    total = sum(q['points'] for q in questions)
    return {'slug': slug, 'title': title, 'total': total, 'questions': questions}, warnings

if __name__ == '__main__':
    doc, title, slug, adir, aurl, out = sys.argv[1:7]
    data, warns = build(doc, title, slug, adir, aurl)
    print(f"--- {slug}: {len(data['questions'])} сұрақ, {data['total']} балл ---")
    for w in warns:
        print("  ⚠ " + w)
    types = {}
    for q in data['questions']:
        types[q['type']] = types.get(q['type'], 0) + 1
    print("  түрлері:", types)
    json.dump(data, open(out, 'w'), ensure_ascii=False, indent=1)
