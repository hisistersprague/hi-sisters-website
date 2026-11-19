# -*- coding: utf-8 -*-
"""Проверка собранного сайта: ссылки, картинки, заголовки, навигация."""
import os, re, io, sys, collections

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, 'site')
problems = collections.Counter()
examples = collections.defaultdict(list)


def fail(kind, detail):
    problems[kind] += 1
    if len(examples[kind]) < 4:
        examples[kind].append(detail)


def exists(url):
    p = url.split('#')[0].split('?')[0]
    if not p.startswith('/'):
        return True
    fs = os.path.join(SITE, p.lstrip('/'))
    return os.path.isfile(fs) or os.path.isfile(os.path.join(fs, 'index.html'))


pages = [os.path.join(dp, f) for dp, _, fs in os.walk(SITE) for f in fs if f.endswith('.html')]
# корневой index.html — это переадресация на язык посетителя, а не страница
pages = [f for f in pages if f[len(SITE):] != '/index.html']
# страницы-перенаправления проверять нечего
pages = [f for f in pages if '/massage/' not in f[len(SITE):]]
pages = [f for f in pages if f[len(SITE):].count('/') != 1 or not f.endswith('.html')]
links = 0
for fp in sorted(pages):
    rel = fp[len(SITE):]
    h = io.open(fp, encoding='utf-8').read()

    for m in re.finditer(r'href="(/[^"]*)"', h):
        links += 1
        if not exists(m.group(1)):
            fail('битая ссылка', '%s → %s' % (rel, m.group(1)))
    for m in re.finditer(r'src="(/[^"]*)"', h):
        if not exists(m.group(1)):
            fail('нет файла картинки/скрипта', '%s → %s' % (rel, m.group(1)))

    for m in re.finditer(r'<(h1|h2|h3)[^>]*>\s*</\1>', h):
        fail('пустой заголовок', '%s <%s>' % (rel, m.group(1)))
    n_h1 = len(re.findall(r'<h1[^>]*>', h))
    if n_h1 != 1:
        fail('не один h1', '%s: %d' % (rel, n_h1))

    nav = re.search(r'<nav class="mainnav">(.*?)</nav>', h, re.S)
    if not nav:
        fail('нет навигации', rel)
    else:
        if len(re.findall(r'<a class="nav-a"', nav.group(1))) != 6:
            fail('в навигации не 6 кнопок', rel)
        cur = len(re.findall(r'aria-current="page"', nav.group(1)))
        # на странице записи своего пункта в шапке нет — подсвечивать нечего
        if cur > 1 or (cur == 0 and '/booking/' not in rel):
            fail('не отмечен текущий раздел', rel)

    if not re.search(r'<title>\S', h):
        fail('пустой title', rel)
    if 'content=""' in h:
        fail('пустое описание', rel)
    for bad in ('None', 'undefined', 'NaN'):
        if re.search(r'>\s*%s\s*<' % bad, h):
            fail('заглушка в тексте: %s' % bad, rel)
    if re.search(r'\{[a-z_]+\[', h) or '{e(' in h:
        fail('незакрытый шаблон', rel)

print('страниц: %d, внутренних ссылок: %d' % (len(pages), links))
if not problems:
    print('замечаний нет')
    sys.exit(0)
for k, n in problems.most_common():
    print('\n%s: %d' % (k, n))
    for x in examples[k]:
        print('   ', x)
