# -*- coding: utf-8 -*-
"""Контроль качества собранного сайта: переводы, мета, картинки, дубли."""
import os, re, io, collections

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'site')
CYR = re.compile(r'[а-яёіїєА-ЯЁІЇЄ]')
pages = [os.path.join(dp, f) for dp, _, fs in os.walk(SITE) for f in fs if f.endswith('.html')]
pages = [p for p in pages if p[len(SITE):].count('/') > 1]
pages = [p for p in pages if '/admin/' not in p[len(SITE):]]

desc = collections.defaultdict(list)
titles = collections.defaultdict(list)
problems = collections.Counter()
examples = collections.defaultdict(list)


def fail(kind, detail):
    problems[kind] += 1
    if len(examples[kind]) < 5:
        examples[kind].append(detail)


for fp in sorted(pages):
    rel = fp[len(SITE):]
    lang = rel.strip('/').split('/')[0]
    h = io.open(fp, encoding='utf-8').read()
    body = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', h, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', body)

    m = re.search(r'<meta name="description" content="([^"]*)"', h)
    d = m.group(1) if m else ''
    if not d:
        fail('нет описания страницы', rel)
    else:
        desc[d].append(rel)
        if len(d) < 70:
            fail('описание короче 70 знаков', '%s (%d)' % (rel, len(d)))
        if len(d) > 170:
            fail('описание длиннее 170 знаков', '%s (%d)' % (rel, len(d)))
    t = re.search(r'<title>(.*?)</title>', h, re.S)
    if t:
        titles[t.group(1).strip()].append(rel)
        if len(t.group(1)) > 65:
            fail('заголовок длиннее 65 знаков', '%s (%d)' % (rel, len(t.group(1))))

    if lang in ('cs', 'en', 'es') and CYR.search(text):
        bad = CYR.search(text)
        frag = re.sub(r'\s+', ' ', text[max(0, bad.start() - 40):bad.start() + 60])
        fail('кириллица на %s' % lang, '%s: …%s…' % (rel, frag.strip()))

    for img in re.finditer(r'<img\b[^>]*>', h):
        if 'alt=' not in img.group(0):
            fail('картинка без alt', rel)
        if 'loading=' not in img.group(0):
            fail('картинка без lazy', rel)
    if '<h1' in h and not re.search(r'<h1[^>]*>\s*\S', h):
        fail('пустой h1', rel)
    if re.search(r'(\b\w{4,}\b)[ ,]+\1\b', text):
        pass

print('страниц проверено: %d' % len(pages))
dups = {k: v for k, v in desc.items() if len(v) > 1}
if dups:
    print('\nодинаковое описание у нескольких страниц: %d групп' % len(dups))
    for k, v in list(dups.items())[:5]:
        print('   «%s…» → %s' % (k[:60], ', '.join(v[:4])))
tdups = {k: v for k, v in titles.items() if len(v) > 1}
if tdups:
    print('\nодинаковый заголовок: %d групп' % len(tdups))
    for k, v in list(tdups.items())[:5]:
        print('   «%s» → %s' % (k[:60], ', '.join(v[:4])))
if not problems:
    print('\nзамечаний нет')
for k, n in problems.most_common():
    print('\n%s: %d' % (k, n))
    for x in examples[k]:
        print('   ', x)
