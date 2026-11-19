# -*- coding: utf-8 -*-
"""Генератор сайта Hi Sisters.

Один проход: content/*.json → site/<язык>/<город>/<раздел>/index.html
Никаких слоёв патчей: весь текст приходит из content/, вся разметка — отсюда.
Страницу рисует генератор, а не яваскрипт: текст виден сразу.

Структура сайта (шесть разделов в шапке):
  /<lang>/<city>/            главная — коротко и с записью
  /<lang>/<city>/services/   все услуги и прайс
  /<lang>/<city>/training/   обучение специалистов
  /<lang>/<city>/cosmetics/  косметика для дома
  /<lang>/<city>/about/      о клинике, принципы, команда
  /<lang>/<city>/contacts/   обе студии
  /<lang>/<city>/<service>/  отдельная услуга
"""
import json, io, os, html, shutil, hashlib, re
from urllib.parse import quote

ROOT = os.path.dirname(os.path.abspath(__file__))
C = os.path.join(ROOT, 'content')
OUT = os.path.join(ROOT, 'site')

L = lambda f: json.load(io.open(os.path.join(C, f), encoding='utf-8'))
ui, prices, services = L('ui.json'), L('prices.json'), L('services.json')
studios, reviews, team = L('studios.json'), L('reviews.json'), L('team.json')
courses, cosm = L('courses.json'), L('cosmetics.json')
equip = L('equipment.json')
advant = L('advantages.json')
svcblocks = L('service-blocks.json')
articles = L('articles.json')
shop_names = L('shop-names.json').get('names', {})
VOL_UNITS = {'uk': {' г': ' г', ' капс.': ' капс.'},
             'cs': {' г': ' g', ' капс.': ' kapslí'},
             'en': {' г': ' g', ' капс.': ' caps'},
             'es': {' г': ' g', ' капс.': ' cáps.'}}
shop_items = L('shop.json')
# DMK в договоре с поставщиком запрещает публиковать цены домашних препаратов
# и продавать их через сайт: показываем товар, но зовём на консультацию
PRICE_HIDDEN_BRANDS = {'dmk'}
top_cfg = L('top.json')


def _is_top(it):
    """Хиты продаж: сколько продано за год по СРМ, плюс правила по брендам."""
    b = (it.get('brand') or '').lower()
    nm = re.sub(r'[^a-z0-9а-яё]', '', it['name'].lower())
    for r in top_cfg.get('names', []):
        if b == r['brand'].lower() and nm == re.sub(r'[^a-z0-9а-яё]', '', r['name'].lower()):
            return r.get('sold', 1)
    for r in top_cfg.get('rules', []):
        if b == r['brand'].lower() and it.get('cat') in r['cat'] and it.get('stock') != 'pre':
            return 1
    return 0
# каталог поставщиков: всё идёт как «под заказ», цены из СРМ имеют приоритет
def _key(it):
    brand = (it.get('brand') or '').lower().split()
    b = re.sub(r'[^a-z0-9]', '', brand[0] if brand else '')
    # в СРМ название идёт с приставкой бренда, в каталоге — без неё
    name = re.sub(r'[^a-z0-9]', '', it['name'].lower())
    if b and name.startswith(b):
        name = name[len(b):]
    vol = re.sub(r'[^a-z0-9]', '', (it.get('volume') or '').lower())
    vol = vol.replace('г', 'g').replace('мл', 'ml')
    return (b, name, vol)


_have = {_key(it) for it in shop_items}
shop_catalog, _extra = [], {}
for it in L('shop-catalog.json'):
    it = dict(it, brand='DSD' if it['brand'] == 'DSD de Luxe' else it['brand'])
    k = _key(it)
    if it.pop('dupe', False) or k in _have:   # товар уже в СРМ: там цена и наличие,
        _extra.setdefault(k, it)              # из каталога берём только состав и фото
        continue
    _have.add(k)
    shop_catalog.append(it)
# состав и фото из каталога поставщика переносим на карточки СРМ
shop_items = [dict(it, **{f: _extra[_key(it)][f]
                          for f in ('ing', 'img')
                          if _extra.get(_key(it), {}).get(f) and not it.get(f)})
              for it in shop_items]
shop_items = [dict(it, priceHidden=True)
              if it.get('brand', '').lower() in PRICE_HIDDEN_BRANDS else it
              for it in shop_items + shop_catalog]
shop_items = [dict(it, top=_is_top(it)) if _is_top(it) else it for it in shop_items]
zones = L('zones.json')
bf = L('blackfriday.json')
svc_reviews = L('service-reviews.json')
procs = L('procedures.json')
PROC_UI, PROC_SUBS, PROC_ITEMS = procs['ui'], procs['subs'], procs['items']
# строка прайса → процедура, чтобы название в прайсе стало ссылкой
PROC_BY_ROW = {}
for _it in PROC_ITEMS:
    for _r in _it['rows']:
        PROC_BY_ROW[(_it['group'], _r)] = _it

LANGS = ['ru', 'uk', 'cs', 'en', 'es']
CITIES = ['prague', 'valencia']
e = lambda s: html.escape(s if isinstance(s, str) else ('' if s is None else str(s)), quote=True)


def pick(block, lang, fallback='ru'):
    """Значение блока на нужном языке, иначе на запасном."""
    if not isinstance(block, dict):
        return block
    return block.get(lang) or block.get(fallback) or {}


# ──────────────────────────── разделы и навигация ────────────────────────────
NAV_ORDER = ['home', 'services', 'training', 'cosmetics', 'about', 'contacts']
REL = {'home': '', 'services': 'services/', 'training': 'training/',
       'cosmetics': 'cosmetics/', 'about': 'about/', 'contacts': 'contacts/',
       'booking': 'booking/'}
NAV_EXTRA = {   # чего нет в старом ui.nav
 'cosmetics': {'ru': 'Косметика', 'uk': 'Косметика', 'cs': 'Kosmetika',
               'en': 'Cosmetics', 'es': 'Cosmética'},
}


def nav_label(key, lang):
    if key in NAV_EXTRA:
        return NAV_EXTRA[key][lang]
    return pick(ui['nav'], lang).get(key) or key



# ───────────────────────────── онлайн-запись ─────────────────────────────
# Запись должна происходить на hi-sisters.clinic, а не уводить на чужой домен.
# Обе системы проверены на встраивание 17.11.2026: iframe не блокируют.
DIKIDI_LOCALE = {'ru': 'ru', 'uk': 'ru', 'cs': 'en', 'en': 'en', 'es': 'es'}
BOOKPAGE = {
 'ru': {'h1': 'Онлайн-запись', 'lead': 'Выберите услугу, специалистку и время — прямо здесь, без перехода на другие сайты.',
        'fallback': 'Если форма не открылась, позвоните или напишите в Instagram — запишем вручную.',
        'newtab': 'Открыть форму в новом окне', 'frame': 'Форма онлайн-записи'},
 'uk': {'h1': 'Онлайн-запис', 'lead': 'Оберіть послугу, спеціалістку та час — просто тут, без переходу на інші сайти.',
        'fallback': 'Якщо форма не відкрилася, зателефонуйте або напишіть в Instagram — запишемо вручну.',
        'newtab': 'Відкрити форму в новому вікні', 'frame': 'Форма онлайн-запису'},
 'cs': {'h1': 'Online rezervace', 'lead': 'Vyberte službu, specialistku a termín — přímo tady, bez přesměrování jinam.',
        'fallback': 'Pokud se formulář nenačte, zavolejte nebo napište na Instagram — objednáme vás ručně.',
        'newtab': 'Otevřít formulář v novém okně', 'frame': 'Formulář online rezervace'},
 'en': {'h1': 'Online booking', 'lead': 'Pick a service, a specialist and a time — right here, with no redirects.',
        'fallback': 'If the form does not load, call us or write on Instagram and we will book you in.',
        'newtab': 'Open the form in a new window', 'frame': 'Online booking form'},
 'es': {'h1': 'Reserva online', 'lead': 'Elige el servicio, la especialista y la hora — aquí mismo, sin salir de la web.',
        'fallback': 'Si el formulario no carga, llámanos o escríbenos por Instagram y te damos cita.',
        'newtab': 'Abrir el formulario en una ventana nueva', 'frame': 'Formulario de reserva online'},
}


# CleverBox открывает саму форму, минуя свою заставку, если в адресе
# пустой третий сегмент пути и параметры cdn + open (найдено в его tags.js).
CBOX_DIRECT = 'https://cbox.mobi/go/?cdn=hi-sisters&open=1'
UTM = '&utm_source=website&utm_medium=site&utm_content=online_booking'


def widget_url(city, lang):
    """Адрес формы записи. DiKiDi умеет язык в пути, CleverBox — нет."""
    if city == 'valencia':
        return 'https://dikidi.app/%s/1743011' % DIKIDI_LOCALE[lang]
    return CBOX_DIRECT + UTM


def book_href(lang, city):
    """Все кнопки «Записаться» ведут на свою страницу, а не на чужой домен."""
    return '/%s/%s/%s' % (lang, city, REL['booking'])




# Начало слогана выделяем золотом — остальное остаётся белым.
SLOGAN_GOLD = {'ru': 'Гладкая и здоровая кожа', 'uk': 'Гладенька і здорова шкіра', 'cs': 'Hladká a zdravá pleť', 'en': 'Smooth, healthy skin', 'es': 'Una piel suave y sana'}


def slogan_html(lang):
    full = HERO[lang]['h1']
    head_ = SLOGAN_GOLD[lang]
    if full.startswith(head_):
        return '<span class="g">%s</span>%s' % (e(head_), e(full[len(head_):]))
    return e(full)


# Город в предложном падеже — для заголовков «… в Праге».
IN_CITY = {
 'prague':   {'ru':'в Праге','uk':'у Празі','cs':'v Praze','en':'in Prague','es':'en Praga'},
 'valencia': {'ru':'в Валенсии','uk':'у Валенсії','cs':'ve Valencii','en':'in Valencia','es':'en Valencia'},
}
# Главный заголовок главной: то, что реально набирают в поиске.
H1_SEO = {
 'prague': {
  'ru':'Лазерная эпиляция и косметология в Праге',
  'uk':'Лазерна епіляція та косметологія у Празі',
  'cs':'Laserová epilace a kosmetologie v Praze',
  'en':'Laser hair removal and skincare in Prague',
  'es':'Depilación láser y cosmetología en Praga'},
 'valencia': {
  'ru':'Лазерная и электроэпиляция в Валенсии',
  'uk':'Лазерна та електроепіляція у Валенсії',
  'cs':'Laserová epilace a elektroepilace ve Valencii',
  'en':'Laser hair removal and electrolysis in Valencia',
  'es':'Depilación láser y eléctrica en Valencia'},
}


# ────────────────────────── тексты первого экрана ──────────────────────────
HERO = {
 'ru': {'kicker':'Эпиляция и косметология', 'h1':'Гладкая и здоровая кожа — не временный эффект, а результат, на который можно положиться',
        'lead':'Волосы уходят за курс и не возвращаются. Уход за лицом подбираем по состоянию кожи, а не по прайсу.',
        'cta':'Записаться','cta2':'Услуги и цены','free':'Первая консультация бесплатно'},
 'uk': {'kicker':'Епіляція та косметологія', 'h1':'Гладенька і здорова шкіра — не тимчасовий ефект, а результат, на який можна покластися',
        'lead':'Волосся йде за курс і не повертається. Догляд за обличчям добираємо за станом шкіри, а не за прайсом.',
        'cta':'Записатися','cta2':'Послуги та ціни','free':'Перша консультація безкоштовна'},
 'cs': {'kicker':'Epilace a kosmetologie', 'h1':'Hladká a zdravá pleť není dočasný efekt, ale výsledek, na který se dá spolehnout',
        'lead':'Chloupky zmizí během kúry a nevrátí se. Péči o pleť volíme podle jejího stavu, ne podle ceníku.',
        'cta':'Objednat se','cta2':'Služby a ceník','free':'První konzultace zdarma'},
 'en': {'kicker':'Hair removal & skincare', 'h1':'Smooth, healthy skin is not a temporary effect — it is a result you can rely on',
        'lead':'The hair is gone within one course and does not come back. Facial care is chosen for your skin, not from a price list.',
        'cta':'Book now','cta2':'Services & prices','free':'First consultation free'},
 'es': {'kicker':'Depilación y cosmetología', 'h1':'Una piel suave y sana no es un efecto pasajero, sino un resultado en el que puedes confiar',
        'lead':'El vello desaparece en un curso y no vuelve. El cuidado facial se elige según tu piel, no según la tarifa.',
        'cta':'Reservar','cta2':'Servicios y precios','free':'Primera consulta gratuita'},
}
# Какие направления показывать и из какой группы брать «от» — зависит от города
DIR_GROUPS = {
 'prague':   [('epil', 'laserWomen'), ('cosm', 'cosmetologyItems')],
 'valencia': [('epil', 'laserWomenEs'), ('electro', 'electroEs')],
}
DIR_TEXT = {
 'ru': {'epil':('Эпиляция','Лазерная эпиляция и электроэпиляция'),
        'cosm':('Косметология','Эстетическая и инъекционная косметология, лечение акне'),
        'electro':('Электроэпиляция','Любой волос, включая светлый и седой')},
 'uk': {'epil':('Епіляція','Лазерна епіляція та електроепіляція'),
        'cosm':('Косметологія','Естетична та ін’єкційна косметологія, лікування акне'),
        'electro':('Електроепіляція','Будь-яке волосся, зокрема світле та сиве')},
 'cs': {'epil':('Epilace','Laserová epilace a elektroepilace'),
        'cosm':('Kosmetologie','Estetická kosmetologie a léčba akné'),
        'electro':('Elektroepilace','Jakýkoli chloupek, i světlý a šedivý')},
 'en': {'epil':('Hair removal','Laser hair removal and electrolysis'),
        'cosm':('Skincare','Aesthetic and injectable skincare, acne treatment'),
        'electro':('Electrolysis','Any hair, including light and grey')},
 'es': {'epil':('Depilación','Depilación láser y electrólisis'),
        'cosm':('Cosmetología','Cosmetología estética e inyectable, tratamiento del acné'),
        'electro':('Electrólisis','Cualquier vello, incluso claro y canoso')},
}

PROOF = {
 'ru': {'reviews': 'отзыва в Google', 'clients': 'довольных клиентов', 'years': 'лет в эпиляции'},
 'uk': {'reviews': 'відгуки в Google', 'clients': 'задоволених клієнток', 'years': 'років в епіляції'},
 'cs': {'reviews': 'recenzí na Google', 'clients': 'spokojených klientek', 'years': 'let v epilaci'},
 'en': {'reviews': 'Google reviews', 'clients': 'happy clients', 'years': 'years in epilation'},
 'es': {'reviews': 'reseñas en Google', 'clients': 'clientas satisfechas', 'years': 'años en depilación'},
}

SECTIONS = {
 'ru': {'prices': 'Цены', 'pricesNote': 'Частые зоны. Полный прайс — на консультации.',
        'revs': 'Что говорят клиентки', 'revsLink': 'Все отзывы в Google',
        'contacts': 'Где мы находимся', 'services': 'Что мы делаем',
        'why': 'Почему к нам возвращаются', 'team': 'Наша команда',
        'allPrices': 'Полный прайс', 'other': 'Другие услуги'},
 'uk': {'prices': 'Ціни', 'pricesNote': 'Часті зони. Повний прайс — на консультації.',
        'revs': 'Що кажуть клієнтки', 'revsLink': 'Усі відгуки в Google',
        'contacts': 'Де ми знаходимось', 'services': 'Що ми робимо',
        'why': 'Чому до нас повертаються', 'team': 'Наша команда',
        'allPrices': 'Повний прайс', 'other': 'Інші послуги'},
 'cs': {'prices': 'Ceník', 'pricesNote': 'Nejčastější zóny. Celý ceník na konzultaci.',
        'revs': 'Co říkají klientky', 'revsLink': 'Všechny recenze na Google',
        'contacts': 'Kde nás najdete', 'services': 'Co děláme',
        'why': 'Proč se k nám klientky vracejí', 'team': 'Náš tým',
        'allPrices': 'Celý ceník', 'other': 'Další služby'},
 'en': {'prices': 'Prices', 'pricesNote': 'Most requested areas. Full price list at the consultation.',
        'revs': 'What clients say', 'revsLink': 'All reviews on Google',
        'contacts': 'Where to find us', 'services': 'What we do',
        'why': 'Why clients come back', 'team': 'Our team',
        'allPrices': 'Full price list', 'other': 'Other services'},
 'es': {'prices': 'Precios', 'pricesNote': 'Zonas más habituales. Precio completo en la consulta.',
        'revs': 'Lo que dicen las clientas', 'revsLink': 'Todas las reseñas en Google',
        'contacts': 'Dónde estamos', 'services': 'Qué hacemos',
        'why': 'Por qué nuestras clientas vuelven', 'team': 'Nuestro equipo',
        'allPrices': 'Precio completo', 'other': 'Otros servicios'},
}

# Блок записи в конце каждой страницы. Без выдуманной спешки — только то, что правда.
CTABAND = {
 'ru': {'h':'Запишитесь сегодня',
        'p':'Первая консультация бесплатная: до начала курса вы знаете число сеансов, стоимость и результат.'},
 'uk': {'h':'Запишіться сьогодні',
        'p':'Перша консультація безкоштовна: до початку курсу ви знаєте кількість сеансів, вартість і результат.'},
 'cs': {'h':'Objednejte se dnes',
        'p':'První konzultace je zdarma: ještě před kúrou víte počet sezení, cenu i výsledek.'},
 'en': {'h':'Book your visit today',
        'p':'The first consultation is free: before the course starts you know the number of sessions, the price and the result.'},
 'es': {'h':'Reserva hoy mismo',
        'p':'La primera consulta es gratuita: antes de empezar sabes cuántas sesiones, cuánto cuesta y qué resultado tendrás.'},
}

OTHER_CITY = {
 'ru': {'label':'Мы также в','switch':'Перейти к студии в'},
 'uk': {'label':'Ми також у','switch':'Перейти до студії в'},
 'cs': {'label':'Jsme také ve','switch':'Přejít na studio ve'},
 'en': {'label':'We are also in','switch':'Go to our studio in'},
 'es': {'label':'También estamos en','switch':'Ir al estudio de'},
}
FOOT = {'ru':'Наши студии','uk':'Наші студії','cs':'Naše studia','en':'Our studios','es':'Nuestros estudios'}
MORE_LABEL = {'ru':'Подробнее','uk':'Детальніше','cs':'Více','en':'Details','es':'Más info'}
BACK = {'ru':'На главную','uk':'На головну','cs':'Zpět na hlavní','en':'Back to home','es':'Volver al inicio'}
LANGNAME = {'ru': 'RU', 'uk': 'UA', 'cs': 'CS', 'en': 'EN', 'es': 'ES'}

KICKER = {
 'prague':   {'ru':'Эпиляция и косметология','uk':'Епіляція та косметологія','cs':'Epilace a kosmetologie',
              'en':'Hair removal & skincare','es':'Depilación y cosmetología'},
 'valencia': {'ru':'Лазерная и электроэпиляция','uk':'Лазерна та електроепіляція','cs':'Laserová a elektroepilace',
              'en':'Laser & electrolysis','es':'Depilación láser y eléctrica'},
}

PRICE_SOURCE = {'prague': 'laserWomen', 'valencia': 'laserWomenEs'}
SERVICE_GROUP = {
 'prague': {'laser':'laserWomen','electro':'electroPackages','cosmetology':'cosmetologyItems',
            'injections':'injections',
            'massage':'faceMassageSessions','microcurrent':'microcurrentSessions',
            'trichology':'trichologyItems'},
 'valencia': {'laser':'laserWomenEs','electro':'electroEs'},
}
# Полный прайс города: заголовок группы берётся из DIR_TEXT либо из PGROUP
# что показываем на странице услуги дополнительными таблицами
SERVICE_EXTRA = {'cosmetology': ['faceMassageSessions', 'microcurrentSessions', 'injections'],
                 'injections': ['botox']}

PGROUPS = {
 'prague': ['laserWomen','laserMen','complexes','electroPackages','intimateWhitening',
            'cosmetologyItems','injections','faceMassageSessions','microcurrentSessions',
            'menFaceItems','menFacePackages','trichologyItems','botox','homeCare'],
 'valencia': ['laserWomenEs','laserMenEs','laserPackagesEs','electroEs','electroExtrasEs',
              'intimatePeelingEs','homeCareEs'],
}
# Инъекции по-чешски не публикуем — такой договорённости держимся во всём прайсе
LANG_SKIP = {'cs': {'injections', 'botox'},
             'en': {'injections', 'botox'},
             'es': {'injections', 'botox'}}


def pgroups(city, lang):
    skip = LANG_SKIP.get(lang, set())
    return [g for g in PGROUPS[city] if g not in skip]
PGROUP_TITLE = {
 'intimateWhitening': {'ru':'Отбеливание интимных зон','uk':'Відбілювання інтимних зон','cs':'Bělení intimních partií','en':'Intimate area whitening','es':'Blanqueamiento íntimo'},
 'intimatePeelingEs': {'ru':'Интимный пилинг','uk':'Інтимний пілінг','cs':'Intimní peeling','en':'Intimate peel','es':'Peeling íntimo'},
 'botox': {'ru':'Ботулинотерапия','uk':'Ботулінотерапія','cs':'—','en':'—','es':'—'},
 'injections': {'ru':'Инъекционная косметология','uk':'Ін’єкційна косметологія','cs':'Injekce','en':'Injectables','es':'Cosmetología inyectable'},
 'laserWomen': {'ru':'Лазерная эпиляция · женщины','uk':'Лазерна епіляція · жінки','cs':'Laserová epilace · ženy','en':'Laser hair removal · women','es':'Depilación láser · mujeres'},
 'laserMen': {'ru':'Лазерная эпиляция · мужчины','uk':'Лазерна епіляція · чоловіки','cs':'Laserová epilace · muži','en':'Laser hair removal · men','es':'Depilación láser · hombres'},
 'complexes': {'ru':'Комплексы зон','uk':'Комплекси зон','cs':'Balíčky zón','en':'Area packages','es':'Combos de zonas'},
 'electroPackages': {'ru':'Электроэпиляция','uk':'Електроепіляція','cs':'Elektroepilace','en':'Electrolysis','es':'Electrólisis'},
 'cosmetologyItems': {'ru':'Косметология','uk':'Косметологія','cs':'Kosmetologie','en':'Skincare','es':'Cosmetología'},
 'faceMassageSessions': {'ru':'Массаж лица','uk':'Масаж обличчя','cs':'Masáž tváře','en':'Facial massage','es':'Masaje facial'},
 'microcurrentSessions': {'ru':'Микротоки','uk':'Мікроструми','cs':'Mikroproudy','en':'Microcurrent','es':'Microcorrientes'},
 'menFaceItems': {'ru':'Уход за лицом · мужчины','uk':'Догляд за обличчям · чоловіки','cs':'Péče o tvář · muži','en':'Facial care · men','es':'Cuidado facial · hombres'},
 'menFacePackages': {'ru':'Курсы для мужчин','uk':'Курси для чоловіків','cs':'Kúry pro muže','en':'Courses for men','es':'Cursos para hombres'},
 'massageSessions': {'ru':'Лимфодренажный массаж','uk':'Лімфодренажний масаж','cs':'Lymfodrenážní masáž','en':'Lymphatic drainage massage','es':'Drenaje linfático'},
 'trichologyItems': {'ru':'Трихология','uk':'Трихологія','cs':'Trichologie','en':'Trichology','es':'Tricología'},
 'homeCare': {'ru':'Косметика для дома','uk':'Косметика для дому','cs':'Kosmetika pro domácí péči','en':'Home care','es':'Cosmética para casa'},
 'homeCareEs': {'ru':'Косметика для дома','uk':'Косметика для дому','cs':'Kosmetika pro domácí péči','en':'Home care','es':'Cosmética para casa'},
 'laserWomenEs': {'ru':'Лазерная эпиляция · женщины','uk':'Лазерна епіляція · жінки','cs':'Laserová epilace · ženy','en':'Laser hair removal · women','es':'Depilación láser · mujeres'},
 'laserMenEs': {'ru':'Лазерная эпиляция · мужчины','uk':'Лазерна епіляція · чоловіки','cs':'Laserová epilace · muži','en':'Laser hair removal · men','es':'Depilación láser · hombres'},
 'laserPackagesEs': {'ru':'Комплексы зон','uk':'Комплекси зон','cs':'Balíčky zón','en':'Area packages','es':'Combos de zonas'},
 'electroEs': {'ru':'Электроэпиляция','uk':'Електроепіляція','cs':'Elektroepilace','en':'Electrolysis','es':'Electrólisis'},
 'electroExtrasEs': {'ru':'Расходные материалы','uk':'Витратні матеріали','cs':'Spotřební materiál','en':'Consumables','es':'Material desechable'},
}
PRICE_FROM = {'ru':'от','uk':'від','cs':'od','en':'from','es':'desde'}
PRICE_UNIT = {'ru':'за зону','uk':'за зону','cs':'za zónu','en':'per area','es':'por zona'}


# ──────────────────────────────── о клинике ────────────────────────────────
ABOUT = {
 'ru': {'h1':'Мы делаем эпиляцию иначе',
        'lead':'Две студии, два метода эпиляции и одно правило: курс заканчивается результатом, а не продлением абонемента.',
        'paras':[
          'Hi Sisters начинались в 2019 году как студия эпиляции Анны Ничипорук. Сегодня это две клиники — в Праге и в Валенсии, команда из семи специалистов и больше 8000 клиентов.',
          'Мы работаем двумя методами сразу. Лазер быстро снимает основную массу волос, а электроэпиляция закрывает то, что лазер не берёт: светлый, седой и пушковый волос. Именно поэтому курс можно закончить, а не продлевать бесконечно.',
          'На больших и сложных зонах с клиентом работают сразу несколько специалистов — от 4 до 10 рук одновременно. Зона, на которую в одиночку уходит несколько часов, закрывается в разы быстрее.',
          'Кроме приёма мы учим специалистов: курсы лазерной эпиляции и электроэпиляции с практикой на моделях, европейским диплом и поддержкой после обучения.'],
        'stats':[('7+','лет в эпиляции'),('8000+','клиентов'),('2','студии в Европе')]},
 'uk': {'h1':'Ми робимо епіляцію інакше',
        'lead':'Дві студії, два методи епіляції та одне правило: курс завершується результатом, а не продовженням абонемента.',
        'paras':[
          'Hi Sisters почалися 2019 року як студія епіляції Анни Ничипорук. Сьогодні це дві клініки — у Празі та Валенсії, команда із семи спеціалістів і понад 8000 клієнтів.',
          'Ми працюємо двома методами одразу. Лазер швидко знімає основну масу волосся, а електроепіляція закриває те, чого лазер не бере: світле, сиве й пушкове волосся. Саме тому курс можна завершити, а не продовжувати безкінечно.',
          'На великих і складних зонах із клієнтом працюють одразу кілька спеціалістів — від 4 до 10 рук одночасно. Зона, на яку поодинці йде кілька годин, закривається значно швидше.',
          'Крім прийому ми навчаємо спеціалістів: курси лазерної епіляції та електроепіляції з практикою на моделях, європейським дипломом і підтримкою після навчання.'],
        'stats':[('7+','років в епіляції'),('8000+','клієнтів'),('2','студії в Європі')]},
 'cs': {'h1':'Epilaci děláme jinak',
        'lead':'Dvě studia, dvě metody epilace a jedno pravidlo: kúra končí výsledkem, ne prodloužením předplatného.',
        'paras':[
          'Hi Sisters začaly v roce 2019 jako epilační studio Anny Nichyporuk. Dnes jsou to dvě kliniky — v Praze a ve Valencii, tým sedmi specialistek a více než 8000 klientek.',
          'Pracujeme oběma metodami zároveň. Laser rychle odstraní hlavní množství chloupků, elektroepilace pak dokončí to, na co laser nestačí: světlé, šedivé a jemné chloupky. Právě proto se kúra dá dokončit, a ne jen prodlužovat.',
          'Na velkých a náročných zónách pracuje s klientkou několik specialistek současně — 4 až 10 rukou najednou. Zóna, která by jedné trvala několik hodin, je hotová mnohem rychleji.',
          'Kromě ošetření také školíme: kurzy laserové epilace a elektroepilace s praxí na modelech, evropským diplomem a podporou i po kurzu.'],
        'stats':[('7+','let v epilaci'),('8000+','klientek'),('2','studia v Evropě')]},
 'en': {'h1':'We do hair removal differently',
        'lead':'Two studios, two hair-removal methods and one rule: a course ends with a result, not with another subscription.',
        'paras':[
          'Hi Sisters started in 2019 as Anna Nichyporuk’s hair-removal studio. Today it is two clinics — in Prague and in Valencia, a team of seven specialists and more than 8,000 clients.',
          'We use both methods together. The laser quickly clears the bulk of the hair, while electrolysis finishes what the laser cannot take: light, grey and fine hair. That is why a course can actually be completed instead of endlessly extended.',
          'On large and difficult areas several specialists work on you at once — 4 to 10 hands at the same time. An area that takes hours with one specialist is finished far faster.',
          'Besides treatments we also train: laser and electrolysis courses with hands-on practice on models, a European diploma and support after the course.'],
        'stats':[('7+','years in epilation'),('8,000+','clients'),('2','studios in Europe')]},
 'es': {'h1':'Hacemos la depilación de otra manera',
        'lead':'Dos estudios, dos métodos de depilación y una regla: el curso termina con un resultado, no con otro bono.',
        'paras':[
          'Hi Sisters nació en 2019 como el estudio de depilación de Anna Nichyporuk. Hoy son dos clínicas — en Praga y en Valencia, un equipo de siete especialistas y más de 8000 clientas.',
          'Trabajamos con los dos métodos a la vez. El láser retira rápido la mayor parte del vello y la electrólisis termina lo que el láser no puede: el vello claro, canoso y fino. Por eso un curso se puede terminar en lugar de alargarlo sin fin.',
          'En las zonas grandes y difíciles trabajan varias especialistas a la vez — de 4 a 10 manos al mismo tiempo. Una zona que con una sola especialista llevaría horas se termina mucho más rápido.',
          'Además de atender, formamos: cursos de depilación láser y electrólisis con práctica en modelos, diploma europeo y apoyo después del curso.'],
        'stats':[('7+','años en depilación'),('8000+','clientas'),('2','estudios en Europa')]},
}

MAIL_LBL = {'ru':'Почта','uk':'Пошта','cs':'E-mail','en':'Email','es':'Correo'}

CONTACTS_PAGE = {
 'ru': {'h1':'Контакты','lead':'Две студии — в Праге и Валенсии. Записаться можно онлайн, по телефону или в Instagram.',
        'book':'Записаться онлайн','route':'Проложить маршрут','hours':'Часы работы'},
 'uk': {'h1':'Контакти','lead':'Дві студії — у Празі та Валенсії. Записатися можна онлайн, телефоном або в Instagram.',
        'book':'Записатися онлайн','route':'Прокласти маршрут','hours':'Години роботи'},
 'cs': {'h1':'Kontakty','lead':'Dvě studia — v Praze a ve Valencii. Objednat se můžete online, telefonicky nebo na Instagramu.',
        'book':'Objednat se online','route':'Navigovat','hours':'Otevírací doba'},
 'en': {'h1':'Contacts','lead':'Two studios — in Prague and Valencia. Book online, by phone or on Instagram.',
        'book':'Book online','route':'Get directions','hours':'Opening hours'},
 'es': {'h1':'Contacto','lead':'Dos estudios — en Praga y Valencia. Reserva online, por teléfono o por Instagram.',
        'book':'Reservar online','route':'Cómo llegar','hours':'Horario'},
}

SERVICES_PAGE = {
 'ru': {'h1':'Услуги и цены','lead':'Эпиляция, косметология и уход. Ниже — все услуги студии и полный прайс.'},
 'uk': {'h1':'Послуги та ціни','lead':'Епіляція, косметологія та догляд. Нижче — усі послуги студії та повний прайс.'},
 'cs': {'h1':'Služby a ceník','lead':'Epilace, kosmetologie a péče. Níže najdete všechny služby studia a celý ceník.'},
 'en': {'h1':'Services & prices','lead':'Hair removal, skincare and treatments. Below are all our services and the full price list.'},
 'es': {'h1':'Servicios y precios','lead':'Depilación, cosmetología y cuidados. Abajo están todos los servicios y la tarifa completa.'},
}

TEASER = {'ru': ('Для специалистов', 'Обучаем лазерной и электроэпиляции: практика на моделях, европейский диплом, поддержка после курса.', 'Смотреть курсы'), 'uk': ('Для спеціалістів', 'Навчаємо лазерної та електроепіляції: практика на моделях, європейський диплом, підтримка після курсу.', 'Дивитися курси'), 'cs': ('Pro specialistky', 'Školíme laserovou epilaci a elektroepilaci: praxe na modelech, evropský diplom, podpora i po kurzu.', 'Zobrazit kurzy'), 'en': ('For specialists', 'We train laser and electrolysis: hands-on practice, a European diploma and support after the course.', 'See the courses'), 'es': ('Para profesionales', 'Formamos en depilación láser y electrólisis: práctica con modelos, diploma europeo y apoyo tras el curso.', 'Ver los cursos')}

TRAIN = {
 'ru': {'kicker':'Обучение','h1':'Обучаем один раз и на всю жизнь',
        'lead':'Курсы лазерной эпиляции и электроэпиляции: теория, практика на моделях, европейский диплом и поддержка после обучения.',
        'cta':'Записаться на курс'},
 'uk': {'kicker':'Навчання','h1':'Навчаємо один раз і на все життя',
        'lead':'Курси лазерної епіляції та електроепіляції: теорія, практика на моделях, європейський диплом і підтримка після навчання.',
        'cta':'Записатися на курс'},
 'cs': {'kicker':'Školení','h1':'Naučíme vás jednou a na celý život',
        'lead':'Kurzy laserové epilace a elektroepilace: teorie, praxe na modelech, evropský diplom a podpora i po kurzu.',
        'cta':'Přihlásit se na kurz'},
 'en': {'kicker':'Training','h1':'We teach you once, for good',
        'lead':'Laser and electrolysis courses: theory, hands-on practice on models, a European diploma and support after the course.',
        'cta':'Apply for a course'},
 'es': {'kicker':'Formación','h1':'Te enseñamos una vez, para siempre',
        'lead':'Cursos de depilación láser y electrólisis: teoría, práctica con modelos, diploma europeo y apoyo tras el curso.',
        'cta':'Solicitar plaza'},
}



# ───────────────────── отзывы Google: цифры берём из studios.json ─────────────────────
REVFORMS = {
 'ru': ('отзыв', 'отзыва', 'отзывов'),
 'uk': ('відгук', 'відгуки', 'відгуків'),
 'cs': ('recenze', 'recenze', 'recenzí'),
 'en': ('review', 'reviews', 'reviews'),
 'es': ('reseña', 'reseñas', 'reseñas'),
}
GOOGLE_IN = {'ru': 'в Google', 'uk': 'в Google', 'cs': 'na Google', 'en': 'on Google', 'es': 'en Google'}
RATING_LINE = {   # скобки, а не «из N», — иначе число не согласуется по падежу
 'ru': 'Оценка в Google: {pc} — {pr} ({pn} {pw}), {vc} — {vr} ({vn} {vw}).',
 'uk': 'Оцінка в Google: {pc} — {pr} ({pn} {pw}), {vc} — {vr} ({vn} {vw}).',
 'cs': 'Hodnocení na Google: {pc} — {pr} ({pn} {pw}), {vc} — {vr} ({vn} {vw}).',
 'en': 'Google rating: {pc} — {pr} ({pn} {pw}), {vc} — {vr} ({vn} {vw}).',
 'es': 'Valoración en Google: {pc} — {pr} ({pn} {pw}), {vc} — {vr} ({vn} {vw}).',
}


def rev_word(n, lang):
    f = REVFORMS[lang]
    if lang in ('ru', 'uk'):
        if n % 10 == 1 and n % 100 != 11:
            return f[0]
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return f[1]
        return f[2]
    if lang == 'cs':
        return f[0] if n == 1 else (f[1] if 2 <= n <= 4 else f[2])
    return f[0] if n == 1 else f[1]


def rating(city, lang):
    """Английский пишет 5.0, остальные — 5,0."""
    r = studios[city].get('rating', '')
    return r.replace(',', '.') if lang == 'en' else r


def reviews_line(city, lang):
    n = studios[city].get('reviews', 0)
    return '%d %s %s' % (n, rev_word(n, lang), GOOGLE_IN[lang])


def rating_sentence(lang):
    """Одна честная фраза про обе студии — цифры разные, прятать их незачем."""
    pr, vl = studios['prague'], studios['valencia']
    return RATING_LINE[lang].format(
        pc=pr['city'].get(lang, pr['city']['en']), pr=rating('prague', lang),
        pn=pr['reviews'], pw=rev_word(pr['reviews'], lang),
        vc=vl['city'].get(lang, vl['city']['en']), vr=rating('valencia', lang),
        vn=vl['reviews'], vw=rev_word(vl['reviews'], lang))


# ───────────────────────────── цены: помощники ─────────────────────────────
def _num(r):
    v = r.get('now') or r.get('price')
    if isinstance(v, str):
        d = ''.join(ch for ch in v if ch.isdigit())
        return int(d) if d else None
    return int(v) if isinstance(v, (int, float)) else None


def group_from(group, city, lang):
    """«от N валюта» по группе цен; None, если по городу данных нет."""
    grp = prices['groups'].get(group) or {}
    vals = [n for n in (_num(r) for r in (grp.get(lang) or grp.get('ru') or [])) if n]
    if not vals:
        return None
    return '%s %d %s' % (PRICE_FROM[lang], min(vals), studios[city]['currency'])


def hero_price(city, lang):
    """Минимальная цена по городу. Если данных нет — не выдумываем."""
    grp = prices['groups'].get(PRICE_SOURCE.get(city))
    if not grp:
        return None
    vals = [n for n in (_num(r) for r in (grp.get(lang) or grp.get('ru') or [])) if n]
    if not vals:
        return None
    return '%s %d %s %s' % (PRICE_FROM[lang], min(vals), studios[city]['currency'], PRICE_UNIT[lang])


def row_val(r, city):
    v = r.get('now') or r.get('price')
    return v if isinstance(v, str) else '%s %s' % (v, studios[city]['currency'])


def price_rows(group, city, lang, limit=None, order=True, link=None):
    """Готовые строки прайса <div class="prow">.

    link='anchor' — название ведёт к описанию на этой же странице,
    link='page'   — на отдельную страницу процедуры."""
    g = prices['groups'].get(group) or {}
    rr = [(i, r) for i, r in enumerate(g.get(lang) or g.get('ru') or []) if _num(r) is not None]
    if order:
        rr = sorted(rr, key=lambda ir: _num(ir[1]) or 0)
    if limit:
        rr = rr[:limit]
    return ''.join('<div class="prow"><span>%s</span><span>%s</span></div>'
                   % (row_label(group, i, r, city, lang, link), e(row_val(r, city)))
                   for i, r in rr)


def zone_for(group, i, city):
    """Зона лазера для строки прайса — у зоны есть своя страница."""
    if group != ZONE_GROUP.get(city):
        return None
    for zk, z in zones.items():
        if i in (z['rows'].get(city) or []):
            return zk
    return None


def row_label(group, i, r, city, lang, link=None):
    """Название строки прайса: ссылкой, если у процедуры есть описание."""
    t = e(r['label'])
    it = PROC_BY_ROW.get((group, i))
    if link and not it:
        zk = zone_for(group, i, city)
        if zk:
            return '<a class="prow-a" href="/%s/%s/laser/%s/">%s</a>' % (lang, city, zk, t)
    if not link or not it or not (it.get('title') or {}).get(lang):
        return t
    if link == 'anchor':
        href = '#p-' + it['slug']
    else:
        if not any(x['slug'] == it['slug'] for x in proc_list(it['service'], city, lang)):
            return t
        href = '/%s/%s/%s' % (lang, city, proc_rel(it))
    return '<a class="prow-a" href="%s">%s</a>' % (href, t)


def proc_rel(it):
    return '%s/%s/' % (it['service'], it['slug'])


def proc_price(it, city, lang):
    """Цена процедуры: точная для одной строки, «от» — если строк несколько."""
    g = prices['groups'].get(it['group']) or {}
    rr = g.get(lang) or g.get('ru') or []
    vals = [_num(rr[i]) for i in it['rows'] if i < len(rr) and _num(rr[i]) is not None]
    if not vals:
        return None
    cur = studios[city]['currency']
    return ('%d %s' % (vals[0], cur) if len(vals) == 1
            else '%s %d %s' % (PRICE_FROM[lang], min(vals), cur))


def proc_list(service, city, lang):
    """Процедуры раздела, у которых есть описание на этом языке и цена в городе."""
    out = []
    for it in PROC_ITEMS:
        if it.get('service') != service or not (it.get('title') or {}).get(lang):
            continue
        if it['group'] in LANG_SKIP.get(lang, set()):
            continue
        g = prices['groups'].get(it['group']) or {}
        if not (g.get(lang) or g.get('ru')):
            continue
        if proc_price(it, city, lang) is None:
            continue
        out.append(it)
    order = {s['key']: n for n, s in enumerate(PROC_SUBS)}
    return sorted(out, key=lambda it: (order.get(it['sub'], 99), it['rows'][0]))


def service_groups(key, city, lang):
    """Все группы прайса, которые показываем на странице услуги."""
    gg = [SERVICE_GROUP.get(city, {}).get(key, '')] + list(SERVICE_EXTRA.get(key) or [])
    skip = LANG_SKIP.get(lang, set())
    return [g for g in gg if g and g not in skip and prices['groups'].get(g)]


def proc_price_tables(key, city, lang):
    """Прайс раздела по подразделам ТЗ; строки без описания остаются в своей группе."""
    groups = service_groups(key, city, lang)
    mine = {g: [(i, r) for i, r in enumerate(prices['groups'][g].get(lang)
                                             or prices['groups'][g].get('ru') or [])
                if _num(r) is not None] for g in groups}
    used = set()
    out = ''
    for sub in PROC_SUBS:
        title = (sub.get('title') or {}).get(lang)
        if not title:
            continue
        body = ''
        for it in proc_list(key, city, lang):
            if it['sub'] != sub['key'] or it['group'] not in mine:
                continue
            rows = [(i, r) for i, r in mine[it['group']] if i in it['rows']]
            if not rows:
                continue
            multi = len(rows) > 1
            # если название процедуры совпадает с названием подраздела, не дублируем
            if multi and it['title'][lang].strip().lower() != title.strip().lower():
                body += ('<div class="prow prow-h"><span><a class="prow-a" href="#p-%s">%s</a></span>'
                         '<span></span></div>'
                         % (it['slug'], e(it['title'][lang])))
            for i, r in rows:
                used.add((it['group'], i))
                lab = e(r['label']) if multi else row_label(it['group'], i, r, city, lang, 'anchor')
                body += ('<div class="prow"><span>%s</span><span>%s</span></div>'
                         % (lab, e(row_val(r, city))))
        if body:
            out += '<h3 class="ptab-h">%s</h3><div class="ptable">%s</div>' % (e(title), body)
    # остальное — как было, под названием своей группы
    for g in groups:
        rest = [(i, r) for i, r in mine[g] if (g, i) not in used]
        if not rest:
            continue
        body = ''.join('<div class="prow"><span>%s</span><span>%s</span></div>'
                       % (row_label(g, i, r, city, lang, 'page'), e(row_val(r, city)))
                       for i, r in rest)
        out += ('<h3 class="ptab-h">%s</h3><div class="ptable">%s</div>'
                % (e((PGROUP_TITLE.get(g) or {}).get(lang, g)), body))
    return out


def proc_body(it, lang, h='h4'):
    """Текст процедуры: абзацы, кому подходит, как проходит, после, как часто."""
    u = PROC_UI[lang]
    out = ''.join('<p>%s</p>' % e(x) for x in (it.get('body') or {}).get(lang, []))
    for fld, tag in (('who', 'ul'), ('how', 'ol'), ('after', 'ul')):
        xs = (it.get(fld) or {}).get(lang) or []
        if xs:
            out += ('<%s>%s</%s><%s>%s</%s>'
                    % (h, e(u[fld]), h, tag,
                       ''.join('<li>%s</li>' % e(x) for x in xs), tag))
    fr = (it.get('freq') or {}).get(lang)
    if fr:
        out += '<p class="note"><b>%s.</b> %s</p>' % (e(u['freq']), e(fr))
    return out


def proc_meta(it, city, lang):
    u = PROC_UI[lang]
    bits = []
    if it.get('duration'):
        bits.append('%d %s' % (it['duration'], u['min']))
    pr = proc_price(it, city, lang)
    if pr:
        bits.append(pr)
    return ' · '.join(bits)


def proc_blocks(key, city, lang):
    """Описания процедур раздела — с собственными ссылками на каждую."""
    u = PROC_UI[lang]
    items = proc_list(key, city, lang)
    if not items:
        return ''
    out = ''
    for sub in PROC_SUBS:
        part = [it for it in items if it['sub'] == sub['key']]
        title = (sub.get('title') or {}).get(lang)
        if not part or not title:
            continue
        out += '<h3 class="proc-sub">%s</h3>' % e(title)
        for it in part:
            out += ('<div class="proc" id="p-%s"><h2>%s</h2>'
                    '<p class="proc-meta">%s</p><p class="lead">%s</p>%s'
                    '<div class="more-list"><a href="%s" data-book>%s</a>'
                    '<a href="%s" target="_blank" rel="noopener" data-wa>%s</a>'
                    '<a href="/%s/%s/%s">%s</a></div></div>'
                    % (it['slug'], e(it['title'][lang]), e(proc_meta(it, city, lang)),
                       e((it.get('lead') or {}).get(lang, '')), proc_body(it, lang),
                       book_href(lang, city), e(HERO[lang]['cta']),
                       wa_book(lang, city, it['title'][lang]), e(WA_BOOK[lang]['btn']),
                       lang, city, proc_rel(it), e(u['own'])))
    return ('<section class="alt"><div class="wrap arts">'
            '<div class="sec-head"><h2>%s</h2></div>%s</div></section>'
            % (e(u['descTitle']), out))


def css():
    return """
:root{
  --navy:#130B56; --navy-deep:#0A0738; --navy-light:#1E1670;
  --gold:#D6B57D; --gold-light:#F2DDD0; --gold-dark:#A8895A;
  --accent:#F2B5E8;            /* розовый из сторис — на кнопках и активных элементах */
  --accent-ink:#2B0F55;
  --gold-ui:#E8C6B0;           /* розовое золото: тёплое, но без желтизны */
  --blush:#FBF1F8;             /* светло-розовый фон для чередования секций */
  --lilac:#F3F0FB;             /* светло-сиреневый фон */
  --rose:#F8EDE6;              /* бежево-розовый фон секций */
  --rose-line:rgba(212,184,150,.48);
  --cream:#FAF6EF; --cream-deep:#F1EADC;
  --ink:#1A1530; --muted:#6B6580; --line:#E4DCCB;
  --line-gold:rgba(212,184,150,.55);
  --max:1120px;
}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{font-family:'Jost',system-ui,sans-serif;color:var(--ink);background:var(--cream);
     font-size:17px;line-height:1.55;-webkit-font-smoothing:antialiased}
h1,h2,h3{font-family:'Cormorant Garamond',Georgia,serif;font-weight:600;line-height:1.12;letter-spacing:-.01em}
a{color:inherit}
img{max-width:100%}
.wrap{max-width:var(--max);margin:0 auto;padding:0 20px}

/* ─── шапка: верхняя строка + строка навигации ─── */
.top{position:sticky;top:0;z-index:50;background:var(--navy);color:#fff;
     border-bottom:1px solid rgba(226,193,120,.4)}
.top-in{display:flex;align-items:center;gap:14px;height:62px}
/* логотип рисуем двумя слоями одной маски: имя золотом, подпись белым */
.brand{position:relative;display:block;width:100px;height:47px;flex-shrink:0;text-decoration:none}
.brand span{position:absolute;left:0;width:100%;
            -webkit-mask:url(/assets/logo.svg) no-repeat 0 0/100% auto;
            mask:url(/assets/logo.svg) no-repeat 0 0/100% auto}
.brand .brand-top{top:0;height:35px;background:var(--gold)}
.brand .brand-sub{top:35px;height:12px;background:#fff;
           -webkit-mask-position:0 -35px;mask-position:0 -35px}
.top-sp{flex:1}
.langs{display:flex;gap:2px}
.langs a{display:block;padding:5px 8px;font-size:12.5px;letter-spacing:.06em;
         text-decoration:none;color:#CFC9E6;border-radius:5px}
.langs a[aria-current]{background:var(--gold-ui);color:var(--navy-deep)}
.socs{display:flex;align-items:center;gap:3px}
.soc{display:flex;align-items:center;justify-content:center;width:30px;height:30px;
   border-radius:9px;color:var(--gold-ui);transition:.15s}
.soc svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.6;
   stroke-linecap:round;stroke-linejoin:round}
.soc:hover{background:rgba(255,255,255,.12);color:#fff}
.soc-whatsapp:hover{color:#5BD066}
.soc-viber:hover{color:#B49CE6}
.soc-telegram:hover{color:#5CC2F0}
.soc-instagram:hover{color:var(--accent)}
@media(max-width:860px){.soc{width:27px;height:27px}.soc svg{width:17px;height:17px}}
.top-tel{font-size:14.5px;text-decoration:none;white-space:nowrap;color:#fff}
.nav-row{border-top:1px solid rgba(226,193,120,.35)}
.mainnav{display:flex;flex-wrap:wrap;gap:2px}
.mainnav::-webkit-scrollbar{display:none}
.mainnav a{padding:12px 14px;font-size:15.5px;text-decoration:none;white-space:nowrap;
           color:#fff;border-bottom:2px solid transparent;transition:color .15s}
.mainnav a:hover{color:var(--gold-ui)}
.mainnav a[aria-current]{border-bottom-color:var(--gold-ui);font-weight:500}
.city-sw{padding:5px 11px;border:1px solid var(--gold-ui);border-radius:999px;
         font-size:13px;text-decoration:none;white-space:nowrap;background:transparent;
         color:var(--gold-ui)}
.city-sw span{color:var(--gold-dark)}

.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;
     padding:13px 24px;border-radius:7px;border:1.5px solid var(--navy);background:var(--navy);
     color:#fff;font:inherit;font-size:15.5px;text-decoration:none;cursor:pointer;
     transition:opacity .15s}
.btn:hover{opacity:.87}
.btn-sm{padding:9px 16px;font-size:14px}
.btn-ghost{background:transparent;color:var(--navy);border-color:var(--accent)}
.hero .btn-ghost{border-color:var(--gold-ui)}
.btn-ghost:hover{border-color:var(--navy);opacity:1}
.btn-gold{background:var(--navy);border-color:var(--navy);color:#fff}
.top .btn{background:var(--gold-ui);border-color:var(--gold-ui);color:var(--navy-deep)}
.dark .btn-gold{background:var(--accent);border-color:var(--accent);
                                color:var(--accent-ink)}
.band .btn-gold:hover,.top .btn:hover{opacity:.9}

/* ─── первый экран: тёмный, в цвет логотипа ─── */
.hero{position:relative;overflow:hidden;padding:56px 0 46px;color:#fff;
      background-color:var(--navy);
      background-image:linear-gradient(168deg,rgba(30,22,112,.62) 0%,rgba(19,11,86,.72) 46%,
        rgba(10,7,56,.90) 100%),url(/assets/photos/hero-bg.jpg);
      background-size:cover,cover;background-position:center,58% 34%;
      background-repeat:no-repeat,no-repeat}
@media(max-width:720px){
  .hero{background-image:linear-gradient(176deg,rgba(19,11,86,.80) 0%,rgba(19,11,86,.72) 34%,
          rgba(10,7,56,.52) 72%,rgba(10,7,56,.60) 100%),url(/assets/photos/hero-bg-m.jpg);
        background-position:center,center 28%}
}
.hero::before{content:'';position:absolute;top:-240px;right:-180px;width:620px;height:620px;
      border-radius:50%;pointer-events:none;
      background:radial-gradient(circle,rgba(212,184,150,.26) 0%,rgba(212,184,150,0) 68%)}
.hero::after{content:'';position:absolute;left:0;right:0;bottom:0;height:2px;background:var(--gold)}
.hero .wrap{position:relative;z-index:1}
.hero-grid{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:clamp(24px,4vw,48px);
   align-items:center}
.hero-pic{margin:0;position:relative;display:flex;flex-direction:column;align-items:center;
   justify-content:center;gap:18px;padding:clamp(18px,3vw,30px) 8px}
.hero-mark{position:relative;width:260px;height:123px}
.hero-mark span{position:absolute;left:0;width:100%;
   -webkit-mask:url(/assets/logo.svg) no-repeat 0 0/100% auto;
   mask:url(/assets/logo.svg) no-repeat 0 0/100% auto}
.hero-mark .m-top{top:0;height:91px;background:var(--gold-ui)}
.hero-mark .m-sub{top:91px;height:32px;background:#fff;
   -webkit-mask-position:0 -91px;mask-position:0 -91px}
.hero-pic figcaption{font-size:13.5px;letter-spacing:.18em;text-transform:uppercase;
   color:var(--gold-ui);text-align:center}
@media(max-width:980px){.hero-grid{grid-template-columns:1fr}
   .hero-pic{max-width:420px;margin-inline:auto;order:2}}
@media(min-width:981px){
  .hero-grid{grid-template-columns:1fr;justify-items:center;text-align:center;gap:10px}
  .hero-pic{order:-1;padding:0 0 6px}
  .hero-mark{width:208px;height:98px}
  .hero-mark .m-top{height:73px}
  .hero-mark .m-sub{top:73px;height:25px;-webkit-mask-position:0 -73px;mask-position:0 -73px}
  .hero-grid>div{max-width:50em;width:100%}
  .hero .h1-seo,.hero .slogan,.hero .lead{margin-inline:auto}
  .hero .cta-row,.hero .proof,.hero .where{justify-content:center;text-align:center}
  .hero .proof{flex-direction:column;gap:12px}
}
@media(max-width:420px){.hero-mark{width:200px;height:95px}
   .hero-mark .m-top{height:70px}
   .hero-mark .m-sub{top:70px;height:25px;-webkit-mask-position:0 -70px;mask-position:0 -70px}}
.hero-sm{padding:42px 0 30px}
.kicker{font-size:12.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--gold-ui);
        margin-bottom:14px}
.kicker a{color:var(--gold-ui)}
.hero h1{font-size:clamp(30px,6vw,52px);margin-bottom:18px;max-width:17em;color:#fff}
.hero-sm h1{font-size:clamp(34px,7vw,56px)}
.hero .h1-seo{font-family:'Jost',sans-serif;font-size:15px;font-weight:500;letter-spacing:.14em;
        text-transform:uppercase;color:var(--gold-ui);margin-bottom:16px;max-width:30em;
        line-height:1.55}
.hero .slogan{font-family:'Cormorant Garamond',Georgia,serif;font-weight:600;line-height:1.14;
        letter-spacing:-.01em;font-size:clamp(27px,4.2vw,40px);margin-bottom:18px;max-width:20em;color:#fff}
.hero .slogan .g{color:var(--gold-ui)}
.hero .lead{font-size:clamp(17px,2.4vw,20px);color:#CFC9E6;max-width:32em;margin-bottom:26px}
.hero .free{color:var(--gold-ui)}
.hero .btn-gold{background:var(--gold-ui);border-color:var(--gold-ui);color:var(--navy-deep)}
.hero .btn-ghost{background:transparent;color:var(--gold-ui);border-color:var(--gold-ui)}
.hero .btn-ghost:hover{background:rgba(212,184,150,.14)}
.fact{display:flex;align-items:baseline;gap:7px;padding:9px 15px;background:#fff;
      border:1px solid var(--line);border-radius:999px;font-size:14.5px}
.fact b{font-family:'Cormorant Garamond',serif;font-size:19px;font-weight:600}
.cta-row{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:26px}
.free{font-size:14px;color:var(--muted)}
.proof{display:flex;flex-wrap:wrap;align-items:center;gap:18px 26px;
       padding-top:22px;border-top:1px solid rgba(212,184,150,.3)}
.stars{color:var(--gold-dark);letter-spacing:.08em}
.hero-badge{display:inline-flex;align-items:center;gap:13px;padding:10px 22px 10px 12px;
            background:rgba(255,255,255,.1);backdrop-filter:blur(12px);
            border:1px solid var(--gold-ui);border-radius:60px;
            box-shadow:0 10px 30px rgba(10,7,40,.35)}
.hero-badge-avatars{display:flex;flex-shrink:0}
.hero-badge-avatars img{width:38px;height:38px;border-radius:50%;object-fit:cover;
            border:2px solid var(--gold-light);margin-left:-12px;background:var(--navy-light)}
.hero-badge-avatars img:first-child{margin-left:0}
.hero-badge-text{line-height:1.12}
.hero-badge-num{display:block;font-family:'Cormorant Garamond',serif;font-size:30px;
            font-weight:600;color:var(--gold-ui)}
.hero-badge-lbl{display:block;font-size:12.5px;color:#E7E2FB;letter-spacing:.02em}
.proof-side{display:flex;flex-direction:column;gap:7px}
.proof-years{font-size:14px;color:#CFC9E6}
.proof-years b{font-family:'Cormorant Garamond',serif;font-size:21px;color:var(--gold-ui)}
.rev-trust{display:inline-flex;align-items:center;gap:10px;text-decoration:none}
.rev-trust-stars{color:var(--gold);letter-spacing:2px;font-size:17px}
.rev-trust-text{color:var(--navy);font-size:14.5px;font-weight:500;
            border-bottom:1px solid var(--navy)}
.hero .rev-trust-text{color:#fff;border-bottom-color:var(--gold-ui)}
.sec-head+.rev-trust{margin:-14px 0 22px}
.alt .rev-trust-text{color:var(--navy)}
.where{margin-top:20px;font-size:14.5px;color:#CFC9E6}
.where a{color:var(--gold-ui);text-underline-offset:3px}
.dirs{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-bottom:26px}
.dir{padding:16px 18px;background:rgba(255,255,255,.07);border:1px solid rgba(212,184,150,.45);
     border-radius:12px;text-decoration:none;display:block;transition:border-color .15s,background .15s}
.dir:hover{border-color:var(--gold);background:rgba(255,255,255,.12)}
.dir b{display:block;font-family:'Cormorant Garamond',serif;font-size:24px;font-weight:600;color:#fff}
.dir span{display:block;font-size:14px;color:#CFC9E6;margin:3px 0 8px}
.dir em{font-style:normal;font-size:15.5px;color:var(--gold)}

/* ─── секции ─── */
section{padding:50px 0}
.sec-head{margin-bottom:26px}
.sec-head h2{font-size:clamp(28px,5vw,40px);margin-bottom:8px}
.sec-head h2::before{content:'';display:block;width:38px;height:2px;
                     background:var(--gold-ui);margin-bottom:14px}
.dark .sec-head h2::before{background:var(--accent)}
.band h2::before{background:var(--gold-ui)}
.sec-head p{color:var(--muted);max-width:34em}
.alt{background:#fff;border-block:1px solid var(--line)}
.tint{background:var(--blush);border-block:1px solid rgba(242,181,232,.4)}
.tint .card,.tint .ptable,.tint .studio,.tint .prod,.tint .mate,.tint .svc-card,
.tint .offer,.tint .course{background:#fff}
.lilac{background:var(--lilac);border-block:1px solid rgba(120,100,200,.14)}
.rose{background:var(--rose);border-block:1px solid var(--rose-line)}
.rose .card,.rose .offer,.rose .rev,.rose .studio{background:#fff}
.rose .rev{border-color:var(--rose-line)}
.rose .btn-gold{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.rose .btn-ghost{color:var(--navy);border-color:var(--navy)}
.rose-photo{position:relative;background-color:var(--rose)}
.rose-photo::before{content:'';position:absolute;inset:0;pointer-events:none;
   background-image:linear-gradient(180deg,rgba(248,237,230,.88),rgba(248,237,230,.93)),
     url(/assets/photos/why-bg.jpg);
   background-size:cover,cover;background-position:center,center 22%;
   background-repeat:no-repeat,no-repeat}
.rose-photo>.wrap{position:relative;z-index:1}
.lilac .card,.lilac .ptable,.lilac .studio,.lilac .prod,.lilac .mate,.lilac .svc-card,
.lilac .offer,.lilac .course{background:#fff}

/* шаги */
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:16px}
.step{padding:22px;background:var(--cream);border:1px solid var(--line);border-radius:12px}
.step-n{font-family:'Cormorant Garamond',serif;font-size:30px;color:var(--gold-dark);line-height:1}
.step h3{font-size:19px;margin:10px 0 7px}
.step p{font-size:14.5px;color:var(--muted)}

/* услуги */
.svc{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}
.svc-card{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;
          display:flex;flex-direction:column}
.alt .svc-card{background:var(--cream)}
.svc-card img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;background:var(--navy-light)}
.svc-body{padding:20px;display:flex;flex-direction:column;flex:1}
.svc-body h3{font-size:22px;margin-bottom:8px}
.svc-body p{font-size:14.5px;color:var(--muted);flex:1}
.svc-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:16px}
.svc-price{font-family:'Cormorant Garamond',serif;font-size:21px}
.more-list{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}
.more-list span.more-flat{padding:8px 15px;background:#fff;border:1px solid var(--line);
   border-radius:999px;font-size:14.5px;color:var(--muted)}
.more-list a{padding:8px 15px;background:#fff;border:1px solid var(--line);border-radius:999px;
             font-size:14.5px;text-decoration:none}

/* цены */
.ptable{background:#fff;border:1px solid var(--line-gold);border-radius:14px;overflow:hidden}
.alt .ptable{background:var(--cream)}
.prow{display:flex;justify-content:space-between;gap:16px;padding:13px 18px;
      border-bottom:1px solid var(--cream-deep);font-size:15.5px}
.prow:last-child{border-bottom:0}
.prow span:last-child{font-family:'Cormorant Garamond',serif;font-size:19px;white-space:nowrap}

/* на телефоне карточка услуги — строка со значком, а не экран на каждую */
@media(max-width:720px){
  .svc{gap:10px}
  .svc-card{flex-direction:row;align-items:stretch;border-radius:12px}
  .svc-card img{width:104px;min-width:104px;height:auto;aspect-ratio:auto;align-self:stretch}
  .svc-body{padding:13px 14px}
  .svc-body h3{font-size:18.5px;margin-bottom:4px;line-height:1.15}
  .svc-body p{font-size:13.5px;line-height:1.45;flex:none;display:-webkit-box;
     -webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
  .svc-body{justify-content:center}
  .svc-foot{margin-top:10px;gap:8px}
  .svc-price{font-size:18px}
  .svc-foot .btn-sm{padding:7px 12px;font-size:13px}
}
.pcols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}
.pcol h3{font-size:22px;margin-bottom:12px}

/* отзывы */
.revs{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}
.rev{padding:22px;background:var(--cream);border:1px solid var(--line);border-radius:12px}
.rev p{font-size:15.5px;margin:10px 0 12px}
.rev cite{font-style:normal;font-size:13.5px;color:var(--muted)}

/* FAQ */
.faq{max-width:760px}
.faq details{border-bottom:1px solid var(--line)}
.faq summary{padding:17px 0;cursor:pointer;font-size:17px;list-style:none;
             display:flex;justify-content:space-between;gap:16px;align-items:center}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:'+';color:var(--gold-dark);font-size:22px;line-height:1}
.faq details[open] summary::after{content:'–'}
.faq .ans{padding:0 0 17px;color:var(--muted);font-size:15.5px}

/* контакты */
.studios{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}
.studio{background:#fff;border:1px solid var(--line-gold);border-radius:14px;padding:26px}
.alt .studio{background:var(--cream)}
.studio h3{font-size:24px;margin-bottom:14px}
.studio dl{display:grid;grid-template-columns:auto 1fr;gap:9px 16px;font-size:15px;margin-bottom:20px}
.studio dt{color:var(--muted)}
.studio a{text-underline-offset:3px}
.studio-cta{display:flex;flex-wrap:wrap;gap:10px}

/* блок записи */
.band{background:var(--navy);color:#fff;border:0}
.band h2{font-size:clamp(28px,5vw,42px);margin-bottom:10px}
.band p{color:#CFC9E6;max-width:34em;margin-bottom:22px}
.band .btn-gold{background:var(--gold-ui);border-color:var(--gold-ui);color:var(--navy-deep)}
.band .btn-ghost{color:var(--gold-ui);border-color:var(--gold-ui)}
.band h2{color:var(--gold-light)}
.band .b-meta{margin-top:20px;font-size:14.5px;color:#CFC9E6;line-height:1.9}
.band .b-meta a{color:var(--gold-ui)}

/* фото-полоса: студийный кадр под навью, золото сверху текста */
.photo-band{position:relative;background:var(--navy-deep);color:#fff;border:0;overflow:hidden}
.photo-band::before{content:"";position:absolute;inset:0;background-image:var(--pb-img);
   background-size:cover;background-position:center 28%;
   filter:grayscale(.2) contrast(1.06) brightness(.72) saturate(.92);opacity:.62}
.photo-band::after{content:"";position:absolute;inset:0;
   background:linear-gradient(104deg,var(--navy-deep) 6%,rgba(10,7,56,.88) 42%,rgba(10,7,56,.30) 100%)}
.photo-band>.wrap{position:relative;z-index:2;padding-block:clamp(58px,8vw,92px)}
.pb-in{max-width:34em}
.pb-kicker{font-size:12.5px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;
   color:var(--gold-ui);margin-bottom:12px}
.photo-band h2{font-family:'Cormorant Garamond',serif;font-weight:600;
   font-size:clamp(28px,4.6vw,42px);line-height:1.12;color:#fff;margin-bottom:12px}
.photo-band p{color:#E4DFF3;margin-bottom:22px}
.photo-band .btn-gold{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.photo-band .free{color:#CFC9E6}
@media(max-width:700px){.photo-band::before{background-position:62% 22%;opacity:.5}
   .photo-band::after{background:linear-gradient(180deg,rgba(10,7,56,.80),rgba(10,7,56,.94))}}

/* текст + фото в две колонки */
.split{display:grid;grid-template-columns:1.02fr .98fr;gap:clamp(24px,4vw,44px);align-items:center}
.split-rev .split-txt{order:2}
.split-img{margin:0}
.split-img img{display:block;width:100%;height:auto;max-height:540px;object-fit:cover;
   border-radius:16px;border:1px solid var(--line-gold);box-shadow:0 18px 46px rgba(19,11,86,.14)}
.split-txt h2{font-family:'Cormorant Garamond',serif;font-weight:600;
   font-size:clamp(25px,3.6vw,34px);line-height:1.15;margin-bottom:12px}
.split-txt p{margin-bottom:12px}
.split-txt ul{list-style:none;margin:16px 0 0;padding:0}
.split-txt li{position:relative;padding-left:20px;margin-bottom:9px;line-height:1.6}
.split-txt li::before{content:"";position:absolute;left:0;top:10px;width:8px;height:8px;
   border-radius:50%;background:var(--accent)}
.dark .split-txt h2{color:#fff}
.dark .split-txt p,.dark .split-txt li{color:#E4DFF3}
.dark .split-txt li::before{background:var(--gold-ui)}
@media(max-width:820px){.split{grid-template-columns:1fr}.split-rev .split-txt{order:0}}

/* перечень услуг на главной */
.svc-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
@media(min-width:1024px){.svc-list{grid-template-columns:none;grid-auto-flow:column;
   grid-auto-columns:minmax(0,1fr);gap:10px}
  .svc-list b{font-size:19px}
  .svc-list a,.svc-list div{padding:14px 15px}}
.dark-photo{position:relative;background-color:var(--navy)}
.dark-photo::before{content:'';position:absolute;inset:0;pointer-events:none;
   background-image:linear-gradient(170deg,rgba(19,11,86,.84),rgba(10,7,56,.90)),
     url(/assets/photos/what-bg.jpg);
   background-size:cover,cover;background-position:center,30% 32%;
   background-repeat:no-repeat,no-repeat}
.dark-photo>.wrap{position:relative;z-index:1}
.svc-list a,.svc-list div{display:block;padding:16px 18px;background:#fff;border:1px solid var(--line-gold);
   border-radius:12px;text-decoration:none;transition:border-color .15s}
.svc-list a:hover{border-color:var(--navy)}
.svc-list b{display:block;font-family:'Cormorant Garamond',serif;font-size:21px;font-weight:600;
   margin-bottom:4px}
.svc-list span{display:block;font-size:14px;color:var(--muted);line-height:1.45}
/* на синем: названия белым, подписи сиреневым, рамки розовым */
.dark .svc-list a,.dark .svc-list div{background:rgba(255,255,255,.06);
   border-color:rgba(242,181,232,.4)}
.dark .svc-list a:hover{border-color:var(--accent);background:rgba(255,255,255,.11)}
.dark .svc-list b{color:#fff}
.dark .svc-list span{color:#CFC9E6}

/* выгодные предложения: розовое с синим */
.lilac .offer{border-top:3px solid var(--accent)}
.lilac .offer h3{color:var(--navy)}
.lilac .o-price b{color:var(--navy)}

/* тёмная секция в фирменном синем */
.dark{background:var(--navy);color:#fff;border:0}
.dark .sec-head h2{color:#fff}
.dark .sec-head p{color:#CFC9E6}
.dark .mini{background:rgba(255,255,255,.07);border-color:rgba(255,255,255,.16)}
.dark .mini h3{color:#fff}
.dark .mini .role{color:var(--gold-ui)}
.dark .ava{background:var(--navy-light)}
.dark .ava-let{background:var(--navy-light);color:var(--accent)}
.dark .more-list a{background:transparent;border-color:var(--accent);color:var(--accent)}
.dark .more-list a:hover{border-color:var(--gold);color:var(--gold)}

/* специалисты и аппараты на главной */
.team-mini{display:grid;grid-template-columns:repeat(auto-fit,minmax(172px,1fr));gap:12px}
.mini{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.15);border-radius:14px;
   padding:0;overflow:hidden;display:flex;flex-direction:column;transition:border-color .15s}
.mini:hover{border-color:var(--accent)}
.alt .mini{background:var(--cream)}
.mini .ava{width:100%;height:auto;aspect-ratio:1/1;border-radius:0;object-fit:cover;
   display:block;margin:0}
.mini .ava-let{font-size:40px;aspect-ratio:1/1;width:100%;height:auto;border-radius:0}
.mini-body{padding:12px 13px 14px;display:flex;flex-direction:column;flex:1}
.mini h3{font-size:18px;margin-bottom:4px;line-height:1.15}
.mini .role{font-size:11px;letter-spacing:.08em;text-transform:uppercase;line-height:1.35;
   font-weight:600;color:var(--accent)}
.mini p{font-size:12.5px;line-height:1.45;margin-top:8px;color:#CFC9E6;
   display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
@media(max-width:520px){.team-mini{grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:10px}
   .mini h3{font-size:16.5px}.mini p{-webkit-line-clamp:2}}
.eq .eq-tag{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--gold-dark);margin-bottom:6px}
.eq h3{font-family:'Jost',sans-serif;font-weight:500;letter-spacing:.01em}
.eq-link{display:inline-block;margin-top:12px;font-size:14.5px;color:var(--navy);text-underline-offset:3px}

/* страница записи */
.bookwrap{display:flex;justify-content:center}
.bookframe{width:100%;max-width:540px;height:760px;border:1px solid var(--line);
           border-radius:14px;background:#fff;display:block;
           /* форма чужая, её цвета задаёт CleverBox/DiKiDi — уводим синий
              в наш индиго, не убивая читаемость */
           filter:hue-rotate(-24deg) saturate(.78) brightness(1.02)}
.booknote{margin:18px auto 0;max-width:680px;text-align:center}
.booknote a{color:var(--navy)}
@media(max-width:720px){.bookframe{height:640px;border-radius:10px}}

/* Black Friday — по макету сторис: индиго, розовые акценты */
.bf{--bf-pink:#F2B5E8; --bf-lilac:#C9C3EF;
    background:linear-gradient(170deg,#241680 0%,#190F6B 55%,#150C5E 100%);
    color:#fff;border:0;overflow:hidden;position:relative}
.bf .wrap{position:relative;z-index:1}
/* две ленты крест-накрест, как в сторис */
.bf-tapes{position:absolute;inset:0;overflow:hidden;
          pointer-events:none;user-select:none;z-index:2}
.bf-pair{position:absolute;left:0;right:0;height:132px}
.bf-tape{position:absolute;left:-10%;width:120%;display:block;white-space:nowrap;
         font-family:'Jost',sans-serif;font-weight:700;font-size:21px;letter-spacing:.1em;
         color:#fff;padding:7px 0;text-align:center}
.bf-tape-dark{top:34px;transform:rotate(-7deg);background:#12121A;
              box-shadow:0 2px 12px rgba(0,0,0,.35)}
.bf-tape-pink{top:62px;transform:rotate(7deg);background:var(--bf-pink);color:#fff;
              box-shadow:0 2px 12px rgba(0,0,0,.2)}
/* ленты ниже первой — тише, чтобы не спорить с текстом */
.bf-pair:not(:first-child){opacity:.3}
.bf-pair:not(:first-child) .bf-tape{font-size:18px}
.bf .wrap{padding-top:124px;position:relative;z-index:3}
@media(max-width:720px){
  .bf-pair{height:112px}
  .bf-tape{font-size:16px;padding:6px 0}
  .bf-pair:not(:first-child) .bf-tape{font-size:14px}
  .bf-tape-dark{top:28px}
  .bf-tape-pink{top:52px}
  .bf .wrap{padding-top:104px}
}
.bf-head{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:26px}
.bf-dates{background:var(--bf-pink);color:#2B0F55;font-size:14px;font-weight:500;
          padding:7px 18px;border-radius:999px;white-space:nowrap}
.bf-brand{font-style:italic;letter-spacing:.14em;font-size:13px;color:var(--bf-pink)}
.bf-title{margin-bottom:28px}
.bf-label{display:block;font-family:'Jost',sans-serif;font-size:13px;letter-spacing:.3em;
          text-transform:uppercase;color:var(--bf-pink);margin-bottom:10px}
.bf h2{font-family:'Jost',sans-serif;font-weight:500;text-transform:uppercase;line-height:1.2;
       font-size:clamp(22px,3.6vw,32px);color:#fff;max-width:20em;letter-spacing:.01em}
.bf h2::before{display:none}
.bf-rows{border-top:1px solid rgba(242,181,232,.28);background:rgba(10,7,56,.62);
   border-radius:16px;padding:0 18px;backdrop-filter:blur(2px)}
.bf-row{display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:12px 24px;
        padding:20px 0;border-bottom:1px solid rgba(242,181,232,.28)}
.bf-main{flex:1 1 300px}
.bf-row h3{font-family:'Jost',sans-serif;font-weight:500;text-transform:uppercase;font-size:17px;
           letter-spacing:.02em;color:#fff;margin-bottom:7px}
.bf-row p{font-size:14.5px;color:var(--bf-lilac);max-width:46em}
.bf-list{margin:10px 0 0 16px;padding:0}
.bf-list li{font-size:13.5px;color:var(--bf-pink);margin-bottom:3px}
.bf-price{flex:0 0 auto;text-align:right;min-width:150px}
.bf-price b{display:block;font-family:'Jost',sans-serif;font-weight:600;font-size:clamp(24px,3.4vw,30px);
            color:var(--bf-pink);line-height:1.1}
.bf-price s{display:block;font-size:14px;color:rgba(242,181,232,.65);margin-top:2px}
.bf-save{display:inline-block;margin-top:7px;font-size:12.5px;color:#2B0F55;
         background:var(--bf-pink);padding:2px 10px;border-radius:999px}
.bf-terms{margin:22px 0 24px;padding:18px 20px;border:1px solid rgba(242,181,232,.3);
          border-radius:12px;background:rgba(255,255,255,.04)}
.bf-terms h3{font-family:'Jost',sans-serif;font-weight:500;text-transform:uppercase;
             font-size:13px;letter-spacing:.18em;color:var(--bf-pink);margin-bottom:10px}
.bf-terms ul{margin:0;padding-left:18px}
.bf-terms li{font-size:13.5px;color:var(--bf-lilac);margin-bottom:5px}
.bf-cta{background:var(--bf-pink);border-color:var(--bf-pink);color:#2B0F55}
.bf-gal-btn{background:transparent;border-color:var(--bf-pink);color:var(--bf-pink);
            margin-right:12px;margin-bottom:10px}
.bf-gal-btn:hover{background:rgba(242,181,232,.14)}
.bf-gal{border:0;border-radius:14px;padding:0;max-width:min(96vw,1000px);width:100%;
        background:#150C5E;color:#fff}
.bf-gal::backdrop{background:rgba(10,7,40,.82)}
.bf-gal form{display:flex;justify-content:flex-end;padding:12px 12px 0}
.bf-gal-close{background:var(--bf-pink);color:#2B0F55;border:0;border-radius:999px;
              padding:7px 16px;font:inherit;font-size:14px;cursor:pointer}
.bf-gal-strip{display:flex;gap:12px;overflow-x:auto;padding:14px;scroll-snap-type:x mandatory}
.bf-gal-strip img{flex:0 0 auto;width:min(82vw,420px);border-radius:10px;scroll-snap-align:center}
.bf-cta:hover{opacity:.9}
@media(max-width:720px){
  .bf-row{padding:18px 0}
  .bf-price{text-align:left;min-width:0}
}

/* топ-предложения */
.offers{display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));gap:16px}
.offer{padding:22px;background:#fff;border:1px solid var(--line-gold);border-radius:12px;
       display:flex;flex-direction:column}
.offer h3{font-size:20px;margin-bottom:10px}
.offer p{font-size:14.5px;color:var(--muted);flex:1;margin-bottom:12px}
.offer-trial{border-color:var(--gold)}
.o-price{display:flex;align-items:baseline;flex-wrap:wrap;gap:10px;margin:auto 0 16px}
.o-price b{font-family:'Cormorant Garamond',serif;font-size:30px;font-weight:600;line-height:1}
.o-price s{color:var(--muted);font-size:15px}
.o-price .off{padding:3px 9px;border-radius:999px;background:var(--accent);
              color:var(--accent-ink);font-size:12.5px;font-weight:500}

/* принципы и команда */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}
.card{padding:24px;background:#fff;border:1px solid var(--line-gold);border-radius:12px;
       border-left:3px solid var(--gold-ui)}
.dark .card,.band .card{border-left-color:var(--accent)}
.alt .card{background:var(--cream)}
.card-ico{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;
   justify-content:center;margin-bottom:14px;background:linear-gradient(135deg,#FDF3E4,#F8E3F4);
   border:1px solid var(--line-gold)}
.card-ico svg{width:22px;height:22px;stroke:var(--navy);stroke-width:1.7;fill:none;
   stroke-linecap:round;stroke-linejoin:round}
.dark .card-ico{background:rgba(255,255,255,.1);border-color:rgba(226,193,120,.45)}
.dark .card-ico svg{stroke:var(--gold-ui)}
.card h3{font-size:21px;margin-bottom:8px}
.card p{font-size:15px;color:var(--muted)}
.stats{display:flex;flex-wrap:wrap;gap:30px;margin:26px 0}
.stats div{font-size:14.5px;color:var(--muted)}
.stats b{display:block;font-family:'Cormorant Garamond',serif;font-size:42px;color:var(--ink);
         font-weight:600;line-height:1}
.team{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.mate{padding:22px;background:#fff;border:1px solid var(--line-gold);border-radius:12px}
.alt .mate{background:var(--cream)}
.ava{display:block;border-radius:50%;object-fit:cover;background:var(--navy-light)}
.ava-let{display:flex;align-items:center;justify-content:center;background:var(--navy);
         color:var(--gold);font-family:'Cormorant Garamond',serif;line-height:1}
.mate .ava{width:84px;height:84px;margin-bottom:14px}
.mate .ava-let{font-size:34px}
.mate h3{font-size:20px;margin-bottom:3px}
.mate .role{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:#B0509B;margin-bottom:9px}
.mate p{font-size:14.5px;color:var(--muted)}

/* косметика */
.prods{display:grid;grid-template-columns:repeat(auto-fit,minmax(265px,1fr));gap:14px}
.prod-pic{margin:0;aspect-ratio:4/3;border-radius:10px;overflow:hidden;background:var(--cream-deep);
   display:flex;align-items:center;justify-content:center;border:1px solid var(--line-gold)}
.prod-pic img{width:100%;height:100%;object-fit:cover;display:block}
.prod-pic .prod-ph{font-family:'Cormorant Garamond',serif;font-size:30px;color:var(--gold-dark);
   letter-spacing:.04em}
.prod-for{font-size:14.5px;color:var(--muted);flex:1;margin-top:8px}
.prod-ing{margin-top:10px;border-top:1px solid var(--line);padding-top:9px}
.prod-ing summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--navy);
   letter-spacing:.03em;list-style:none}
.prod-ing summary::-webkit-details-marker{display:none}
.prod-ing summary::before{content:"+ ";color:var(--accent);font-weight:700}
.prod-ing[open] summary::before{content:"– "}
.prod-ing p{font-size:13.5px;line-height:1.65;color:var(--muted);margin-top:7px}
.prod-order{margin-top:12px;width:100%;background:var(--accent);border-color:var(--accent);
   color:var(--accent-ink)}
.prod-note{font-size:12.5px;color:var(--muted);margin-top:7px}
.prod-stock{position:absolute;top:10px;right:10px;z-index:3;padding:4px 10px;border-radius:999px;
   font-family:'Jost',system-ui,sans-serif;font-size:11px;line-height:1.3;font-weight:500;
   letter-spacing:.03em;white-space:nowrap;max-width:50%;overflow:hidden;text-overflow:ellipsis}
.prod-stock.is-in{background:#E8F5EC;border:1px solid #9FCCAE;color:#1F6B3A}
.prod-stock.is-pre{background:#FBF1F8;border:1px solid var(--accent);color:#8A3C7C}
.prod[data-stock="pre"] .prod-order{background:transparent;border-color:var(--navy);color:var(--navy)}
.prod-cat{position:absolute;top:10px;left:10px;z-index:2;padding:4px 10px;border-radius:999px;
   background:rgba(255,255,255,.94);border:1px solid var(--line-gold);
   font-family:'Jost',system-ui,sans-serif;font-size:11px;line-height:1.3;font-weight:500;
   letter-spacing:.03em;color:var(--navy);white-space:nowrap;max-width:46%;
   overflow:hidden;text-overflow:ellipsis}
.prod[data-stock=""] .prod-cat{max-width:calc(100% - 20px)}
.prod{position:relative}

/* панель фильтров каталога */
.nav-i{position:relative;display:inline-flex;align-items:center}
.nav-x{display:none;width:26px;height:26px;margin-left:-2px;border:0;background:none;cursor:pointer;
  position:relative}
.nav-x::after{content:"";position:absolute;left:8px;top:9px;width:6px;height:6px;
  border-right:1.6px solid currentColor;border-bottom:1.6px solid currentColor;
  transform:rotate(45deg);color:#fff;opacity:.75}
.nav-sub{position:absolute;left:0;top:100%;z-index:40;display:none;min-width:232px;padding:8px 0;
  background:#fff;border:1px solid var(--line-gold);border-radius:12px;
  box-shadow:0 18px 40px rgba(19,11,86,.18)}
.nav-sub a{display:block;padding:9px 16px;font-size:14px;color:var(--navy);white-space:nowrap;border-bottom:0}
.nav-sub a:hover{background:var(--cream)}
.nav-sub a.is-on{color:var(--gold-dark);font-weight:500}
.has-sub:hover .nav-sub,.has-sub:focus-within .nav-sub,.has-sub.is-open .nav-sub{display:block}
/* мышь должна доезжать до меню, не проваливаясь в пустоту */
.has-sub::after{content:"";position:absolute;left:0;right:0;top:100%;height:12px}
@media(max-width:900px){
  .nav-x{display:inline-block}
  .nav-sub{position:static;min-width:0;width:100%;flex:1 0 100%;margin:4px 0 6px;box-shadow:none;
    background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.18)}
  .has-sub{width:100%}
  .nav-sub a{color:#fff;padding:8px 12px}
  .nav-sub a:hover{background:rgba(255,255,255,.12)}
  .has-sub:hover .nav-sub{display:none}
  .has-sub.is-open .nav-sub{display:block}
  .nav-i{align-items:flex-start}
  .has-sub{flex-wrap:wrap}
}
.shop-brands{margin-top:10px;font-size:14px;color:var(--muted)}
.shop-find{flex-direction:row;align-items:center;gap:10px}
.shop-toggle{display:none}
@media(max-width:767px){
  .shop-rows{display:none}
  .shop-rows.is-open{display:block}
  .shop-toggle{display:inline-flex;flex:none}
  .shop-find input{flex:1 1 auto}
}
.shop-find input{width:100%;max-width:420px;padding:11px 14px;border-radius:12px;
  border:1px solid var(--rose-line);background:#fff;font:inherit;font-size:15px;color:var(--navy)}
.shop-find input:focus{outline:2px solid var(--gold-ui);outline-offset:1px}
.art-grid{display:grid;gap:22px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.art-item h3{font-family:'Cormorant Garamond',serif;font-size:21px;font-weight:600;
  color:var(--navy);margin-bottom:8px}
.art-item p{font-size:15px;line-height:1.65}
.prod-top{position:absolute;left:10px;top:42px;z-index:2;padding:3px 10px;border-radius:999px;
  background:var(--gold);color:#2B1C0B;font-size:11px;letter-spacing:.06em;text-transform:uppercase}
.pm-ask{font-style:normal;font-size:13px;color:var(--gold-dark);text-align:right}
.shop-bar{display:flex;flex-direction:column;gap:12px;margin-bottom:18px;padding:18px 20px;
   background:#fff;border:1px solid var(--line-gold);border-radius:14px}
.shop-row{display:flex;flex-wrap:wrap;align-items:center;gap:9px}
.shop-lbl{min-width:104px;font-size:12.5px;font-weight:700;letter-spacing:.1em;
   text-transform:uppercase;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{padding:7px 15px;border-radius:999px;border:1px solid var(--line-gold);background:transparent;
   font:inherit;font-size:14px;color:var(--navy);cursor:pointer;transition:.15s}
.chip:hover{border-color:var(--navy)}
.chip.is-on{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);font-weight:600}
.shop-sort{padding:8px 13px;border-radius:999px;border:1px solid var(--line-gold);background:#fff;
   font:inherit;font-size:14px;color:var(--navy);cursor:pointer}
.shop-count{font-size:13.5px;color:var(--muted);margin-bottom:12px}

/* прайс: группа — кнопка, раскрывается таблицей */
.ptab-h{font-family:'Cormorant Garamond',serif;font-size:23px;font-weight:600;
   margin:30px 0 10px;padding-top:22px;border-top:1px solid var(--line-gold)}
.svc-blocks{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}
.svc-block{background:#fff;border:1px solid var(--line-gold);border-radius:14px;padding:22px 22px 18px;
   border-top:3px solid var(--accent);display:flex;flex-direction:column}
.svc-block h3{font-size:22px;margin-bottom:9px}
.svc-block p{font-size:15px;color:var(--muted);margin-bottom:12px}
.svc-block ul{list-style:none;margin:0 0 14px;padding:0}
.svc-block li{position:relative;padding-left:19px;margin-bottom:8px;font-size:14.5px;line-height:1.5}
.svc-block li::before{content:"";position:absolute;left:0;top:9px;width:7px;height:7px;
   border-radius:50%;background:var(--gold-ui);border:1px solid var(--gold-dark)}
.svc-block-foot{margin-top:auto;display:flex;align-items:center;justify-content:space-between;gap:12px}
.pslides{display:flex;gap:14px;overflow-x:auto;scroll-snap-type:x mandatory;
   padding:4px 0 14px;scrollbar-width:thin;-webkit-overflow-scrolling:touch}
.pslides::-webkit-scrollbar{height:6px}
.pslides::-webkit-scrollbar-thumb{background:var(--line-gold);border-radius:999px}
.pslide{flex:0 0 min(88%,345px);scroll-snap-align:center;border-radius:18px;overflow:hidden;
   position:relative;background:var(--navy-deep);color:#fff;
   border:1px solid rgba(239,217,180,.32);display:flex;flex-direction:column}
.pslide::before{content:'';position:absolute;inset:0;
   background-image:linear-gradient(168deg,rgba(19,11,86,.80),rgba(10,7,56,.93)),
     url(/assets/photos/hero-bg.jpg);
   background-size:cover,cover;background-position:center,58% 34%}
.pslide-in{position:relative;z-index:1;padding:22px 20px 24px;display:flex;flex-direction:column;flex:1}
.pslide-kick{font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--gold-ui);
   margin-bottom:6px}
.pslide h3{font-family:'Cormorant Garamond',serif;font-size:27px;font-weight:600;line-height:1.1;
   color:#fff;margin-bottom:14px}
.pslide .prow{display:flex;justify-content:space-between;gap:12px;padding:8px 0;font-size:14px;
   border-bottom:1px solid rgba(255,255,255,.13);background:none;color:#E4DFF3}
.pslide .prow:last-child{border-bottom:0}
.pslide .prow span:last-child{font-family:'Jost',sans-serif;font-size:14.5px;font-weight:600;
   color:var(--gold-ui);white-space:nowrap}
.pslide-cta{margin-top:auto;padding-top:16px}
.pslide-cta .btn{width:100%;background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.pnav{display:flex;align-items:center;gap:10px;margin-top:2px}
.pnav button{width:38px;height:38px;border-radius:50%;border:1px solid var(--line-gold);
   background:#fff;color:var(--navy);cursor:pointer;font-size:17px;line-height:1;transition:.15s}
.pnav button:hover{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.pnav-hint{font-size:13.5px;color:var(--muted)}
.pacc{display:grid;gap:10px}
.pgroup{background:#fff;border:1px solid var(--line-gold);border-radius:14px;overflow:hidden}
.pgroup[open]{border-color:var(--accent);box-shadow:0 10px 28px rgba(19,11,86,.07)}
.pgroup>summary{display:flex;align-items:center;gap:12px;padding:17px 20px;cursor:pointer;
   list-style:none;user-select:none}
.pgroup>summary::-webkit-details-marker{display:none}
.pgroup>summary:hover{background:var(--rose)}
.pg-name{font-family:'Cormorant Garamond',serif;font-size:21px;font-weight:600;color:var(--ink);
   flex:1;line-height:1.2}
.pg-from{font-size:14px;color:var(--muted);white-space:nowrap}
.pg-sign{width:26px;height:26px;flex-shrink:0;border-radius:50%;border:1px solid var(--line-gold);
   position:relative;transition:.15s}
.pg-sign::before,.pg-sign::after{content:"";position:absolute;left:50%;top:50%;background:var(--navy);
   transform:translate(-50%,-50%);transition:.18s}
.pg-sign::before{width:11px;height:1.6px}
.pg-sign::after{width:1.6px;height:11px}
.pgroup[open] .pg-sign{background:var(--accent);border-color:var(--accent)}
.pgroup[open] .pg-sign::after{height:0}
.pgroup>.ptable{padding:0 20px 18px;border-top:1px solid var(--line)}
@media(max-width:560px){.pg-name{font-size:18.5px}.pg-from{font-size:13px}}
.shop-empty{padding:28px 0;color:var(--muted)}
@media(max-width:620px){.shop-lbl{min-width:100%}}
.prod{padding:20px;background:#fff;border:1px solid var(--line-gold);border-radius:12px;
      display:flex;flex-direction:column}
.alt .prod{background:var(--cream)}
.prod .brand{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--gold-dark)}
.prod h3{font-size:21px;margin:5px 0 6px}
.prod p{font-size:14.5px;color:var(--muted);flex:1}
.prod .pm{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-top:14px;
          font-size:14px;color:var(--muted)}
.prod .pm b{font-family:'Cormorant Garamond',serif;font-size:21px;color:var(--ink);font-weight:600}
.note{padding:14px 18px;background:#fff;border:1px solid var(--line);border-radius:10px;
      color:var(--muted);font-size:15px}
.alt .note{background:var(--cream)}

/* текстовые страницы */
.btn-wa{background:#fff;color:var(--ink);border:1px solid var(--line-gold)}
.btn-wa:hover{border-color:#25D366;color:#128C4A}
.prow-a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--line-gold)}
.prow-a:hover{color:var(--accent);border-color:var(--accent)}
.prow-h{background:var(--cream);font-weight:600}
.prow-h span:first-child{font-size:16px}
.proc-sub{font-family:'Cormorant Garamond',serif;font-size:26px;font-weight:600;
  margin:38px 0 14px;color:var(--accent)}
.proc-sub:first-child{margin-top:0}
.proc{padding:22px 0 8px;border-top:1px solid var(--line);scroll-margin-top:24px}
.proc h2{font-size:24px;margin:0 0 6px}
.proc h4{font-family:'Cormorant Garamond',serif;font-size:19px;font-weight:600;margin:20px 0 8px}
.proc-meta{font-size:14.5px;color:var(--gold-dark);letter-spacing:.04em;margin:0 0 12px}
.proc ul,.proc ol{margin:0 0 6px;padding-left:20px}
.proc li{margin-bottom:6px;font-size:15.5px;line-height:1.6}
.arts{max-width:760px}
.art{margin-bottom:30px}
.art h2{font-size:clamp(24px,4vw,32px);margin-bottom:12px}
.art p{margin-bottom:12px}
.art ul,.art ol{margin:0 0 12px 20px}
.art li{margin-bottom:7px}
.art .note{margin-top:4px}
.prose{max-width:34em}
.prose p{margin-bottom:14px}

/* обучение */
.teaser{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:20px}
.teaser h2{font-size:clamp(26px,4vw,34px);margin-bottom:8px}
.teaser p{color:var(--muted);max-width:40em}
.courses{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}
.course{background:var(--cream);border:1px solid var(--line);border-radius:14px;padding:24px}
.course h3{font-size:23px;margin-bottom:10px}
.c-meta{display:flex;justify-content:space-between;gap:12px;align-items:baseline;margin-bottom:10px;font-size:14.5px;color:var(--muted)}
.c-meta b{font-family:'Cormorant Garamond',serif;font-size:20px;color:var(--ink)}
.c-desc{font-size:15px;color:var(--muted);margin-bottom:12px}
.course details{border-top:1px solid var(--line);margin:12px 0}
.course summary{padding:12px 0;cursor:pointer;font-size:15px;list-style:none;color:var(--gold-dark)}
.course summary::-webkit-details-marker{display:none}
.c-prog h4{font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:var(--gold-dark);margin:12px 0 6px}
.c-prog ul{margin:0 0 8px 18px}
.c-prog li{font-size:14.5px;margin-bottom:6px}
.c-lead{font-size:15px;margin-bottom:8px}

/* подвал */
footer{background:var(--navy-deep);color:#CFC9E6;padding:40px 0 30px;font-size:14.5px}
footer a{color:#fff;text-decoration:none}
.foot-in{display:flex;flex-wrap:wrap;gap:26px;justify-content:space-between}
.foot-title{font-family:'Cormorant Garamond',serif;font-size:21px;color:var(--gold-ui);margin-bottom:16px}
.foot-title::after{content:'';display:block;width:38px;height:2px;background:var(--gold-ui);margin-top:12px}
.foot-studio{line-height:1.75}
.foot-studio b{color:#fff;font-weight:500}
.foot-nav{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:24px;
          padding-top:20px;border-top:1px solid rgba(212,184,150,.32)}
.foot-nav a{text-decoration:none;opacity:.85}

/* липкая кнопка на телефоне */
.sticky{position:fixed;left:0;right:0;bottom:0;z-index:60;padding:10px 16px calc(10px + env(safe-area-inset-bottom));
        background:rgba(255,255,255,.96);backdrop-filter:blur(10px);border-top:1px solid var(--line-gold);display:none}
.sticky .btn-gold{background:var(--navy);border-color:var(--navy);color:#fff;font-weight:500}
.sticky .btn{width:100%}
@media(max-width:720px){
  body{font-size:16px;overflow-x:hidden}
  .top-in{height:56px;gap:10px}
  .brand{width:82px;height:39px}
  .brand .brand-top{height:29px}
  .brand .brand-sub{top:29px;height:10px;-webkit-mask-position:0 -29px;mask-position:0 -29px}
  .hero{padding:32px 0 28px}
  .hero-sm{padding:26px 0 20px}
  .top-tel{display:none}
  .top-in>.btn{display:none}        /* кнопка живёт в липкой панели внизу */
  .langs a{padding:5px 6px;font-size:12px}
  .city-sw{padding:4px 8px;font-size:12px}
  .city-sw span{display:none}
  .top{position:static}              /* на телефоне шапка не липнет: внизу есть кнопка */
  .mainnav{flex-wrap:wrap;overflow:visible;gap:0;padding-bottom:3px}
  .mainnav a{padding:9px 10px;font-size:14.5px}
  .sticky{display:block}
  section{padding:40px 0}
  footer{padding-bottom:84px}
  .proof{gap:16px}
  .stats{gap:22px}
  .stats b{font-size:34px}
  .where{word-break:break-word}
}
"""



# ───────────────────────────── микроразметка ─────────────────────────────
BASE = 'https://hi-sisters.clinic'
SCHEMA_TYPE = {'ru': 'HealthAndBeautyBusiness'}


def jld(obj):
    return ('<script type="application/ld+json">%s</script>'
            % json.dumps(obj, ensure_ascii=False, separators=(',', ':')))


def biz_schema(lang, city):
    """Клиника: адрес, координаты, часы, телефон, соцсети, вилка цен.
    Рейтинг Google здесь не указываем — размечать чужие отзывы нельзя."""
    st = studios[city]
    name = 'Hi Sisters Clinic %s' % st['city'].get(lang, st['city']['en'])
    hours = [{'@type': 'OpeningHoursSpecification',
              'dayOfWeek': ['https://schema.org/' + {'Mo':'Monday','Tu':'Tuesday','We':'Wednesday',
                            'Th':'Thursday','Fr':'Friday','Sa':'Saturday','Su':'Sunday'}[d]
                            for d in st['days'].split(',')],
              'opens': st['opens'], 'closes': st['closes']}]
    return {
        '@context': 'https://schema.org', '@type': 'HealthAndBeautyBusiness',
        '@id': '%s/%s/%s/#business' % (BASE, lang, city),
        'name': name, 'url': '%s/%s/%s/' % (BASE, lang, city),
        'image': BASE + '/assets/laser.jpg',
        'telephone': st['phone'], 'email': st.get('email', ''), 'priceRange': '$$',
        'currenciesAccepted': 'CZK' if city == 'prague' else 'EUR',
        'address': {'@type': 'PostalAddress', 'streetAddress': st['street'],
                    'addressLocality': st['city_en'], 'postalCode': st['zip'],
                    'addressCountry': st['country']},
        'geo': {'@type': 'GeoCoordinates', 'latitude': st['lat'], 'longitude': st['lng']},
        'openingHoursSpecification': hours,
        'sameAs': ['https://instagram.com/' + h for h in st.get('instagram', [])]
                  + ([st['maps']] if st.get('maps') else []),
        'hasMap': st.get('maps', ''),
        'makesOffer': [
            {'@type': 'Offer', 'itemOffered': {'@type': 'Service',
             'name': (services[k]['card'].get(lang) or services[k]['card']['ru'])['title']}}
            for k in services if city in services[k]['cities'] and services[k]['card'].get(lang)],
    }


def faq_schema(items):
    if not items:
        return ''
    return jld({'@context': 'https://schema.org', '@type': 'FAQPage',
                'mainEntity': [{'@type': 'Question', 'name': f['q'],
                                'acceptedAnswer': {'@type': 'Answer', 'text': f['a']}}
                               for f in items]})


def crumbs(lang, city, trail):
    """trail: [(название, путь), …] — путь относительно /<язык>/<город>/."""
    items = [{'@type': 'ListItem', 'position': 1,
              'name': 'Hi Sisters Clinic', 'item': '%s/%s/%s/' % (BASE, lang, city)}]
    for i, (nm, rel) in enumerate(trail, start=2):
        items.append({'@type': 'ListItem', 'position': i, 'name': nm,
                      'item': '%s/%s/%s/%s' % (BASE, lang, city, rel)})
    return jld({'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': items})


def service_schema(lang, city, key, price_from):
    st = studios[city]
    card = services[key]['card'].get(lang) or services[key]['card']['ru']
    pg = services[key]['page'].get(lang) or {}
    obj = {'@context': 'https://schema.org', '@type': 'Service',
           'name': pg.get('title') or card['title'],
           'description': (pg.get('intro') or card['desc'])[:300],
           'serviceType': card['title'],
           'provider': {'@id': '%s/%s/%s/#business' % (BASE, lang, city)},
           'areaServed': st['city_en'],
           'url': '%s/%s/%s/%s/' % (BASE, lang, city, key)}
    if price_from:
        obj['offers'] = {'@type': 'Offer', 'price': price_from,
                         'priceCurrency': 'CZK' if city == 'prague' else 'EUR',
                         'availability': 'https://schema.org/InStock'}
    return jld(obj)


def price_min(group, lang):
    grp = prices['groups'].get(group) or {}
    vals = [n for n in (_num(r) for r in (grp.get(lang) or grp.get('ru') or [])) if n]
    return min(vals) if vals else None


# ─────────────────────────── общий каркас страницы ───────────────────────────

# Версия стилей в адресе: браузер и прокси не держат старый файл после правок.
CSSVER = hashlib.md5(css().encode('utf-8')).hexdigest()[:8]

OG_LOCALE = {'ru': 'ru_RU', 'uk': 'uk_UA', 'cs': 'cs_CZ', 'en': 'en_GB', 'es': 'es_ES'}


def head(lang, city, title, desc, rel='', langs=None):
    base = 'https://hi-sisters.clinic'
    ls_ = langs or LANGS
    alts = '\n'.join('  <link rel="alternate" hreflang="%s" href="%s/%s/%s/%s">' % (l, base, l, city, rel)
                     for l in ls_)
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{base}/{lang}/{city}/{rel}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Hi Sisters Clinic">
<meta property="og:locale" content="{OG_LOCALE[lang]}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{base}/{lang}/{city}/{rel}">
<meta property="og:image" content="{base}/assets/og.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{base}/assets/og.jpg">
<meta name="twitter:card" content="summary_large_image">
{alts}
  <link rel="alternate" hreflang="x-default" href="{base}/{'cs' if 'cs' in ls_ else ls_[0]}/prague/{rel}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600&family=Jost:wght@300;400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/app.css?v={CSSVER}">
<link rel="icon" href="/favicon.svg">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-K921K357QH"></script>
<script>
window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}
gtag('js',new Date());gtag('config','AW-18276095826');gtag('config','G-K921K357QH');
addEventListener('click',function(ev){{
  var a=ev.target.closest('[data-book]'); if(!a) return;
  gtag('event','booking_click',{{studio:a.dataset.book||document.body.dataset.city,lang:document.documentElement.lang}});
}},true);
</script>
</head>
<body data-city="{city}">"""



# Формулировки старого сайта — Анне они нравились, оставляем дословно.
CLIENTS_LBL = {'ru': 'довольных клиентов', 'uk': 'задоволених клієнтів',
               'cs': 'spokojených klientů', 'en': 'happy clients',
               'es': 'clientes satisfechos'}
GOOGLE_ON = {'ru': 'на Google', 'uk': 'на Google', 'cs': 'na Googlu',
             'en': 'on Google', 'es': 'en Google'}


def trust_text(city, lang):
    """«5,0 на Google · 211 отзывов» — как было на старом сайте."""
    n = studios[city].get('reviews', 0)
    return '%s %s · %d %s' % (rating(city, lang), GOOGLE_ON[lang], n, rev_word(n, lang))


def trust_link(city, lang, cls='rev-trust'):
    maps = studios[city].get('maps', '#')
    return ('<a class="%s" href="%s" target="_blank" rel="noopener">'
            '<span class="rev-trust-stars">★★★★★</span>'
            '<span class="rev-trust-text">%s</span></a>'
            % (cls, maps, e(trust_text(city, lang))))


def clients_badge(lang):
    """Плашка с аватарами и числом клиентов."""
    # стоковые портреты, не наши мастерицы: это плашка про клиенток
    avas = ''.join('<img src="/assets/clients/c%d.jpg" alt="" loading="lazy" '
                   'width="220" height="220">' % n for n in (1, 2, 3))
    return ('<div class="hero-badge"><div class="hero-badge-avatars">%s</div>'
            '<div class="hero-badge-text"><span class="hero-badge-num">+8000</span>'
            '<span class="hero-badge-lbl">%s</span></div></div>'
            % (avas, e(CLIENTS_LBL[lang])))


CLIENTS_SHORT = {'ru': 'клиентов', 'uk': 'клієнток', 'cs': 'klientek',
                 'en': 'clients', 'es': 'clientas'}


SOCIAL_SVG = {
 'whatsapp': '<path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5.1-1.3A10 10 0 1 0 12 2Z"/>'
             '<path d="M8.9 7.6c.2-.4.4-.4.6-.4h.5c.2 0 .4 0 .6.5l.8 1.9c.1.2 0 .4-.1.5l-.4.5c-.1.2-.3.3-.1.6'
             '.2.3.8 1.3 1.7 2.1 1.2 1 2.1 1.4 2.4 1.5.3.1.5.1.6-.1l.7-.8c.2-.2.4-.2.6-.1l1.8.9c.2.1.4.2.4.3'
             '0 .2 0 .9-.3 1.3-.3.4-1.1.9-1.6.9-1.3.1-2.5-.3-4.6-1.5-2.4-1.4-3.9-4-4-4.2-.1-.2-.9-1.3-.9-2.5'
             '0-1.2.6-1.8.8-2.1Z"/>',
 'viber': '<path d="M12 2.5c-4.6 0-8.3 2.9-8.3 7.6 0 2.4 1 4.4 2.7 5.7v4.2l3-2c.8.2 1.7.3 2.6.3'
          ' 4.6 0 8.3-2.9 8.3-7.6S16.6 2.5 12 2.5Z"/>'
          '<path d="M9.2 7.9c.2-.3.4-.3.6-.3h.4c.2 0 .3 0 .5.4l.6 1.5c.1.2 0 .3-.1.4l-.3.4c-.1.1-.2.2-.1.4'
          '.2.3.6 1 1.3 1.6.9.8 1.6 1.1 1.8 1.2.2 0 .3 0 .5-.1l.5-.6c.1-.2.3-.2.5-.1l1.4.7c.1.1.3.2.3.3'
          ' 0 .2 0 .7-.2 1-.3.3-.9.7-1.3.7-1 .1-1.9-.2-3.5-1.1-1.8-1.1-3-3.1-3.1-3.2-.1-.2-.7-1-.7-1.9'
          ' 0-.9.4-1.3.6-1.5Z"/><path d="M12.8 6.4a3.9 3.9 0 0 1 3.6 3.6"/>',
 'telegram': '<path d="M21.6 4.3 2.9 11.5c-.9.4-.9.9-.2 1.1l4.6 1.4 1.8 5.4c.2.6.4.8 1 .4l2.5-1.9 4.5 3.3'
             'c.8.5 1.4.2 1.6-.8l3-13.9c.3-1.3-.5-1.8-1.1-1.2Z"/>'
             '<path d="m8 14.3 9.6-6-7.4 7.2-.3 3.4"/>',
 'instagram': '<rect x="3" y="3" width="18" height="18" rx="5.4"/>'
              '<circle cx="12" cy="12" r="4.1"/><circle cx="17.3" cy="6.7" r="1.1"/>',
}

SOCIAL_SVG_EXTRA = {
 'tiktok': '<path fill="currentColor" d="M16.6 5.8a4.3 4.3 0 0 1-1.1-2.8h-2.9v11.6a2.4 2.4 0 1 1-2-2.4V9.2a5.3 5.3 0 1 0 4.9 5.3V9.1a7 7 0 0 0 4 1.3V7.5a4.3 4.3 0 0 1-2.9-1.7z"/>',
 'threads': '<path fill="currentColor" d="M12.2 21c-2.6 0-4.6-.8-5.9-2.5C5 16.9 4.4 14.8 4.4 12s.6-4.9 1.9-6.5C7.6 3.8 9.6 3 12.2 3c1.8 0 3.3.4 4.5 1.2 1.1.8 1.9 1.9 2.4 3.3l-1.9.6c-.7-2.1-2.3-3.2-4.9-3.2-1.9 0-3.3.6-4.2 1.8-.9 1.2-1.4 2.9-1.4 5.3s.5 4.1 1.4 5.3c.9 1.2 2.3 1.8 4.2 1.8 1.6 0 2.8-.3 3.6-1 .8-.6 1.2-1.4 1.2-2.3 0-.8-.3-1.4-.9-1.9a4 4 0 0 0-1.3-.7c-.2 1.3-.7 2.3-1.4 2.9-.7.6-1.6.9-2.7.9-1 0-1.9-.3-2.5-.9-.6-.6-.9-1.3-.9-2.2 0-1 .4-1.8 1.2-2.4.8-.6 1.9-.9 3.3-.9.5 0 1 0 1.5.1-.1-1.3-.8-2-2.1-2-.8 0-1.5.3-2.1.9l-1.3-1.3c.9-.9 2.1-1.4 3.4-1.4 2.6 0 4 1.4 4.1 4.2 1.9.7 2.9 2 2.9 3.9 0 1.5-.6 2.7-1.8 3.7-1.2.9-2.9 1.4-5 1.4zm.3-7.2c-1.7 0-2.6.5-2.6 1.4 0 .8.6 1.2 1.6 1.2 1.4 0 2.2-.9 2.4-2.5-.5-.1-.9-.1-1.4-.1z"/>',
}

SOCIAL_LBL = {
 'tiktok': 'TikTok', 'threads': 'Threads','whatsapp': 'WhatsApp', 'viber': 'Viber',
              'telegram': 'Telegram', 'instagram': 'Instagram'}


def social_links(city):
    """Мессенджеры по телефону студии, Instagram — свой у каждого города."""
    st = studios[city]
    digits = re.sub(r'[^0-9]', '', st['phone'])
    ig = (st.get('instagram') or [''])[0]
    out = [('whatsapp', 'https://wa.me/%s' % digits),
           ('viber', 'viber://chat?number=%%2B%s' % digits),
           ('telegram', 'https://t.me/+%s' % digits)]
    if ig:
        out.append(('instagram', 'https://instagram.com/%s' % ig))
    if st.get('tiktok'):
        out.append(('tiktok', 'https://www.tiktok.com/@%s' % st['tiktok'].lstrip('@')))
    if st.get('threads'):
        out.append(('threads', 'https://www.threads.net/@%s' % st['threads'].lstrip('@')))
    return ''.join(
        '<a class="soc soc-%s" href="%s" target="_blank" rel="noopener" '
        'aria-label="%s" title="%s"><svg viewBox="0 0 24 24" aria-hidden="true">%s</svg></a>'
        % (k, u, SOCIAL_LBL.get(k, k), SOCIAL_LBL.get(k, k),
           SOCIAL_SVG.get(k) or SOCIAL_SVG_EXTRA.get(k, '')) for k, u in out)


NAV_ALL = {"ru": "Все услуги", "uk": "Усі послуги", "cs": "Všechny služby", "en": "All services", "es": "Todos los servicios"}
# порядок пунктов подменю «Услуги» — как в техзадании
NAV_SUB = ['cosmetology', 'laser', 'electro', 'trichology', 'injections']


def nav_submenu(lang, city, rel):
    """Выпадающее меню услуг: направления города плюс ссылка на весь список."""
    out = []
    for k in NAV_SUB:
        svc = services.get(k) or {}
        if city not in svc.get('cities', []) or not (svc.get('page') or {}).get(lang):
            continue
        out.append((k + '/', svc['page'][lang]['title']))
    out.append((REL['services'], NAV_ALL[lang]))
    # отметку текущего раздела несёт верхний пункт, в подменю только подсветка
    return ''.join('<a href="/%s/%s/%s"%s>%s</a>'
                   % (lang, city, r, ' class="is-on"' if r == rel else '', e(t))
                   for r, t in out)


def header(lang, city, rel, current, other_rel=None, langs=None):
    st = studios[city]
    other = 'valencia' if city == 'prague' else 'prague'
    cityname = st['city'].get(lang, st['city']['en'])
    othername = studios[other]['city'].get(lang, studios[other]['city']['en'])
    orel = rel if other_rel is None else other_rel
    ls_ = langs or LANGS
    # страница есть не на всех языках: с недостающего ведём на список услуг
    langs = ''.join('<a href="/%s/%s/%s"%s>%s</a>'
                    % (l, city, rel if l in ls_ else REL['services'],
                       ' aria-current="true"' if l == lang else '', LANGNAME[l])
                    for l in LANGS)
    sub = nav_submenu(lang, city, rel)
    items = ''
    for k in NAV_ORDER:
        a = ('<a class="nav-a" href="/%s/%s/%s"%s>%s</a>'
             % (lang, city, REL[k], ' aria-current="page"' if k == current else '',
                e(nav_label(k, lang))))
        if k == 'services' and sub:
            items += ('<span class="nav-i has-sub">' + a +
                      '<button class="nav-x" type="button" aria-expanded="false" '
                      'aria-label="' + e(nav_label(k, lang)) + '"></button>'
                      '<span class="nav-sub">' + sub + '</span></span>')
        else:
            items += '<span class="nav-i">' + a + '</span>' 
    return f"""
<header class="top">
  <div class="wrap top-in">
    <a class="brand" href="/{lang}/{city}/" aria-label="Hi Sisters Clinic"><span class="brand-top"></span><span class="brand-sub"></span></a>
    <a class="city-sw" href="/{lang}/{other}/{orel}" title="{e(OTHER_CITY[lang]['switch'])} {e(othername)}">{e(cityname)} <span>· {e(othername)}</span></a>
    <span class="top-sp"></span>
    <nav class="langs" aria-label="Language">{langs}</nav>
    <div class="socs">{social_links(city)}</div>
    <a class="top-tel" href="tel:{st['phone'].replace(' ','')}">{e(st['phone'])}</a>
    <a class="btn btn-sm" href="{book_href(lang, city)}" data-book>{e(HERO[lang]['cta'])}</a>
  </div>
  <div class="nav-row"><div class="wrap"><nav class="mainnav">{items}</nav></div></div>
</header>"""


def band(lang, city):
    """Блок записи: один и тот же призыв в конце каждой страницы."""
    st = studios[city]
    b = CTABAND[lang]
    cityname = st['city'].get(lang, st['city']['en'])
    hours = (st.get('hours') or {}).get(lang, '')
    return f"""
<section class="band"><div class="wrap">
  <h2>{e(b['h'])}</h2>
  <p>{e(b['p'])}</p>
  <div class="cta-row">
    <a class="btn btn-gold" href="{book_href(lang, city)}" data-book>{e(HERO[lang]['cta'])}</a>
    <a class="btn btn-ghost" href="tel:{st['phone'].replace(' ','')}">{e(st['phone'])}</a>
  </div>
  <div class="b-meta">
    {e(cityname)} · <a href="{st.get('maps','#')}" target="_blank" rel="noopener">{e(st['address'])}</a><br>
    {e(hours)}
  </div>
</div></section>"""


def footer(lang, city):
    st = studios[city]
    other = 'valencia' if city == 'prague' else 'prague'
    cityname = st['city'].get(lang, st['city']['en'])
    othername = studios[other]['city'].get(lang, studios[other]['city']['en'])
    ot = studios[other]
    nav = ''.join('<a href="/%s/%s/%s">%s</a>' % (lang, city, REL[k], e(nav_label(k, lang)))
                  for k in NAV_ORDER)
    return f"""
<footer><div class="wrap">
  <div class="foot-title">{e(FOOT[lang])}</div>
  <div class="foot-in">
    <div class="foot-studio">
      <b>{e(cityname)}</b><br>
      <a href="{st.get('maps','#')}" target="_blank" rel="noopener">{e(st['address'])}</a><br>
      <a href="tel:{st['phone'].replace(' ','')}">{e(st['phone'])}</a><br>
      <a href="mailto:{st.get('email','')}">{e(st.get('email',''))}</a><br>
      {e((st.get('hours') or {}).get(lang,''))}
    </div>
    <div class="foot-studio">
      <b><a href="/{lang}/{other}/">{e(othername)}</a></b><br>
      {e(ot['address'])}<br>
      <a href="tel:{ot['phone'].replace(' ','')}">{e(ot['phone'])}</a><br>
      {e((ot.get('hours') or {}).get(lang,''))}
    </div>
  </div>
  <nav class="foot-nav">{nav}</nav>
</div></footer>"""


def with_city(title, desc, lang, city):
    """У Праги и Валенсии разные страницы — заголовок и описание не должны совпадать."""
    nm = studios[city]['city'].get(lang, studios[city]['city']['en'])
    low = nm.lower()
    if low not in title.lower():
        if ' — Hi Sisters' in title:
            title = title.replace(' — Hi Sisters', ', %s — Hi Sisters' % nm, 1)
        else:
            title = '%s, %s' % (title, nm)
    tail = desc.rstrip().rstrip('.').lower()
    if not tail.endswith(low):
        room = 166 - len(nm)
        base = desc.rstrip()
        if len(base) > room:
            base = base[:room].rsplit(' ', 1)[0]
        desc = '%s %s.' % (base.rstrip(' ,.;:—-'), nm)
    return title, desc


def doc(lang, city, rel, current, title, desc, main, cta=None, other_rel=None,
        with_band=True, schema='', langs=None, add_city=True):
    if add_city:
        title, desc = with_city(title, desc, lang, city)
    label = cta or HERO[lang]['cta']
    sticky = ('<div class="sticky"><a class="btn btn-gold" href="%s" data-book>%s</a></div>'
              % (book_href(lang, city), e(label))) if with_band else ''
    return (head(lang, city, title, desc, rel, langs=langs)
            + header(lang, city, rel, current, other_rel, langs=langs)
            + '\n<main>' + main + (band(lang, city) if with_band else '') + '</main>'
            + footer(lang, city)
            + sticky + schema + '<script>' + NAV_JS + '</script>'
            + '\n</body></html>')



# ───────────────────── топ-предложения на главной ─────────────────────
OFFER_GROUP = {'prague': 'complexes', 'valencia': 'laserPackagesEs'}
OFFERS = {
 'ru': {'h': 'Выгодные предложения', 'p': 'Комплексы зон стоят меньше, чем те же зоны по отдельности.',
        'trialT': 'Пробная электроэпиляция', 'all': 'Весь прайс',
        'trialD': '{n} минут на теле, чтобы попробовать метод. Одноразовые иглы — в стоимости.'},
 'uk': {'h': 'Вигідні пропозиції', 'p': 'Комплекси зон коштують менше, ніж ті самі зони окремо.',
        'trialT': 'Пробна електроепіляція', 'all': 'Весь прайс',
        'trialD': '{n} хвилин на тілі, щоб спробувати метод. Одноразові голки — у вартості.'},
 'cs': {'h': 'Výhodné nabídky', 'p': 'Balíčky zón vyjdou levněji než stejné zóny zvlášť.',
        'trialT': 'Zkušební elektroepilace', 'all': 'Celý ceník',
        'trialD': '{n} minut na těle, abyste metodu vyzkoušeli. Jednorázové jehly jsou v ceně.'},
 'en': {'h': 'Best offers', 'p': 'Area packages cost less than the same areas booked separately.',
        'trialT': 'Try electrolysis', 'all': 'Full price list',
        'trialD': '{n} minutes on the body to test the method. Single-use needles included.'},
 'es': {'h': 'Mejores ofertas', 'p': 'Los combos de zonas salen más baratos que esas mismas zonas por separado.',
        'trialT': 'Electrólisis de prueba', 'all': 'Precio completo',
        'trialD': '{n} minutos en el cuerpo para probar el método. Agujas desechables incluidas.'},
}


def offers_block(city, lang):
    """Пакеты зон со старой ценой и пробная электроэпиляция — всё из данных."""
    st = studios[city]; o = OFFERS[lang]; cur = st['currency']
    g = prices['groups'].get(OFFER_GROUP.get(city)) or {}
    cards = ''
    for r in (g.get(lang) or g.get('ru') or []):
        now, was = r.get('now') or r.get('price'), r.get('was')
        if now is None:
            continue
        off = ''
        if isinstance(was, (int, float)) and isinstance(now, (int, float)) and was > now:
            off = '<span class="off">−%d%%</span>' % round((was - now) * 100.0 / was)
            old = '<s>%s %s</s>' % (was, cur)
        else:
            old = ''
        cards += ('<article class="offer"><h3>%s</h3>'
                  '<div class="o-price"><b>%s %s</b>%s%s</div>'
                  '<a class="btn btn-sm btn-gold" href="%s" data-book>%s</a>'
                  '</article>'
                  % (e(r['label']), e(now), e(cur), old, off, book_href(lang, city), e(HERO[lang]['cta'])))

    tr = st.get('trial')
    if tr:
        cards += ('<article class="offer offer-trial"><h3>%s</h3>'
                  '<p>%s</p><div class="o-price"><b>%s %s</b></div>'
                  '<a class="btn btn-sm btn-gold" href="%s" data-book>%s</a>'
                  '</article>'
                  % (e(o['trialT']), e(o['trialD'].format(n=tr['minutes'])),
                     e(tr['price']), e(cur), book_href(lang, city), e(HERO[lang]['cta'])))
    if not cards:
        return ''
    return ('<section class="rose"><div class="wrap">'
            '<div class="sec-head"><h2>%s</h2><p>%s</p></div>'
            '<div class="offers">%s</div>'
            '<div class="more-list"><a href="/%s/%s/services/#prices">%s</a></div>'
            '</div></section>' % (e(o['h']), e(o['p']), cards, lang, city, e(o['all'])))



# ─────────────── специалисты и аппараты: короткие блоки на главной ───────────────
TEAM_MINI = {
 'ru': {'h': 'Наши специалисты', 'p': 'Семь специалистов: эпиляция, косметология, трихология и врач-дерматолог.',
        'p1': 'В студии в Валенсии приём ведёт основательница клиники.', 'more': 'Подробнее о команде'},
 'uk': {'h': 'Наші спеціалістки', 'p': 'Сім спеціалісток: епіляція, косметологія, трихологія та лікарка-дерматологиня.',
        'p1': 'У студії у Валенсії приймає засновниця клініки.', 'more': 'Детальніше про команду'},
 'cs': {'h': 'Naše specialistky', 'p': 'Sedm specialistek: epilace, kosmetologie, trichologie a lékařka dermatoložka.',
        'p1': 'Ve studiu ve Valencii ošetřuje zakladatelka kliniky.', 'more': 'Více o týmu'},
 'en': {'h': 'Our specialists', 'p': 'Seven specialists: hair removal, skincare, trichology and a dermatologist.',
        'p1': 'At the Valencia studio you are seen by the founder of the clinic.', 'more': 'More about the team'},
 'es': {'h': 'Nuestras especialistas', 'p': 'Siete especialistas: depilación, cosmetología, tricología y una médica dermatóloga.',
        'p1': 'En el estudio de Valencia te atiende la fundadora de la clínica.', 'more': 'Más sobre el equipo'},
}


def city_team(city):
    """Специалисты именно этого города: в Валенсии принимает только Анна."""
    return [m for m in team if city in (m.get('cities') or ['prague'])]


def team_mini(lang, city):
    """Лица и специализации — коротко, подробности на странице «О нас»."""
    t = TEAM_MINI[lang]
    mates_ = city_team(city)
    sub = t['p'] if len(mates_) > 1 else t['p1']
    cards = ''
    for m in mates_:
        nm = m['name'].get(lang) or m['name']['ru']
        img = m.get('img')
        ava = ('<img class="ava" src="/assets/team/%s" alt="%s" loading="lazy" width="200" height="200">'
               % (e(img), e(nm))) if img else \
              ('<div class="ava ava-let" aria-hidden="true">%s</div>' % e(nm.strip()[:1]))
        d_ = (m.get('desc') or {}).get(lang) or (m.get('desc') or {}).get('ru', '')
        cards += ('<article class="mini">%s<div class="mini-body">'
                  '<h3>%s</h3><div class="role">%s</div>%s</div></article>'
                  % (ava, e(nm), e(m['role'].get(lang) or m['role']['ru']),
                     ('<p>%s</p>' % e(d_)) if d_ else ''))
    return ('<section class="dark"><div class="wrap">'
            '<div class="sec-head"><h2>%s</h2><p>%s</p></div>'
            '<div class="team-mini">%s</div>'
            '<div class="more-list"><a href="/%s/%s/about/">%s</a></div>'
            '</div></section>' % (e(t['h']), e(sub), cards, lang, city, e(t['more'])))



def advantages_block(lang, city):
    """Интервалы, гарантия и подбор параметров — настоящие отличия студии.
    Про аппараты тут намеренно нет: клиенту они ни о чём не говорят."""
    cards = icon_cards([(i['title'][lang], i['desc'][lang]) for i in advant['items']], ICO_ADVANT)
    return ('<section class="rose"><div class="wrap">'
            '<div class="sec-head"><h2>%s</h2></div><div class="cards">%s</div>'
            '</div></section>' % (e(advant['title'][lang]), cards))


def equip_block(lang, city):
    """Аппараты, на которых работаем. Показываем только то, что есть в городе."""
    items = [i for i in equip['items'] if city in i['cities']]
    if not items:
        return ''
    cards = ''
    for i in items:
        key = i.get('service')
        link = ''
        if key and key in services and city in services[key]['cities'] and services[key]['page'].get(lang):
            link = '<a class="eq-link" href="/%s/%s/%s/">%s</a>' % (lang, city, key, e(MORE_LABEL[lang]))
        cards += ('<article class="card eq"><div class="eq-tag">%s</div><h3>%s</h3><p>%s</p>%s</article>'
                  % (e(i['tag'][lang]), e(i['title'][lang]), e(i['desc'][lang]), link))
    return ('<section class="alt"><div class="wrap">'
            '<div class="sec-head"><h2>%s</h2></div>'
            '<div class="cards">%s</div>'
            '</div></section>' % (e(equip['sectionTitle'][lang]), cards))



SVC_LIST = {
 'ru': {'h': 'Что мы делаем', 'all': 'Все услуги и цены'},
 'uk': {'h': 'Що ми робимо', 'all': 'Усі послуги та ціни'},
 'cs': {'h': 'Co děláme', 'all': 'Všechny služby a ceník'},
 'en': {'h': 'What we do', 'all': 'All services and prices'},
 'es': {'h': 'Qué hacemos', 'all': 'Todos los servicios y precios'},
}


def services_list(lang, city):
    """Полные названия всех услуг города — по ним нас ищут в поиске."""
    t = SVC_LIST[lang]
    rows = ''
    for k, v in services.items():
        if city not in v['cities']:
            continue
        c = v['card'].get(lang)
        if not c:
            continue
        name, desc = c.get('title', ''), (c.get('desc') or '')
        if len(desc) > 90:
            desc = desc[:88].rsplit(' ', 1)[0] + '…'
        inner = '<b>%s</b><span>%s</span>' % (e(name), e(desc))
        rows += ('<a href="/%s/%s/%s/">%s</a>' % (lang, city, k, inner)
                 if v['page'].get(lang) else '<div>%s</div>' % inner)
    if not rows:
        return ''
    return ('<section class="dark dark-photo"><div class="wrap">'
            '<div class="sec-head"><h2>%s</h2></div>'
            '<div class="svc-list">%s</div>'
            '<div class="more-list"><a href="/%s/%s/services/">%s</a></div>'
            '</div></section>' % (e(t['h']), rows, lang, city, e(t['all'])))



# ─────────────────────────── Black Friday ───────────────────────────

def bf_gallery(lang):
    """Кнопка и лайтбокс со слайдами акции: до/после и отзывы."""
    files = bf.get('gallery') or []
    if not files:
        return ''
    u = bf['ui'][lang]
    slides = ''.join('<img src="/assets/bf/%s" alt="" loading="lazy">' % e(f) for f in files)
    return ('<button class="btn bf-gal-btn" type="button" '
            'onclick="document.getElementById(\'bf-gal\').showModal()">%s</button>'
            '<dialog id="bf-gal" class="bf-gal">'
            '<form method="dialog"><button class="bf-gal-close">%s</button></form>'
            '<div class="bf-gal-strip">%s</div></dialog>'
            % (e(u.get('gallery', '')), e(u.get('close', '')), slides))


def bf_block(lang, city):
    """Акция на главной. Выключается одной строкой active в blackfriday.json."""
    if not bf.get('active') or city not in bf.get('cities', []):
        return ''
    u = bf['ui'][lang]; cur = bf['currency']
    rows = ''
    for o in bf['offers']:
        if lang not in o.get('langs', LANGS):
            continue
        save = o['was'] - o['now']
        bullets = (o.get('bullets') or {}).get(lang) or []
        rows += ('<article class="bf-row">'
                 '<div class="bf-main"><h3>%s</h3><p>%s</p>%s</div>'
                 '<div class="bf-price"><b>%s %s</b><s>%s %s</s>'
                 '<span class="bf-save">%s %s %s</span></div>'
                 '</article>'
                 % (e(o['title'][lang]), e(o['desc'][lang]),
                    ('<ul class="bf-list">%s</ul>' % ''.join('<li>%s</li>' % e(b) for b in bullets)) if bullets else '',
                    e('{:,}'.format(o['now']).replace(',', ' ')), e(cur),
                    e('{:,}'.format(o['was']).replace(',', ' ')), e(cur),
                    e(u['save']), e('{:,}'.format(save).replace(',', ' ')), e(cur)))
    if not rows:
        return ''
    run = 'BLACK FRIDAY&nbsp;&nbsp;·&nbsp;&nbsp;' * 16
    pairs = ''.join('<div class="bf-pair" style="top:%dpx">'
                    '<span class="bf-tape bf-tape-dark">%s</span>'
                    '<span class="bf-tape bf-tape-pink">%s</span></div>'
                    % (n * 430, run, run) for n in range(9))
    tapes = '<div class="bf-tapes" aria-hidden="true">%s</div>' % pairs
    return ('<section class="bf">' + tapes + '<div class="wrap">'
            '<div class="bf-head"><span class="bf-dates">%s</span>'
            '<span class="bf-brand">HI SISTERS</span></div>'
            '<div class="bf-title"><span class="bf-label">%s</span><h2>%s</h2></div>'
            '<div class="bf-rows">%s</div>'
            '<div class="bf-terms"><h3>%s</h3><ul>%s</ul></div>'
            '%s'
            '<a class="btn bf-cta" href="%s" data-book>%s</a>'
            '</div></section>'
            % (e(u['dates']), e(u['label']), e(u['title']), rows,
               e(u.get('terms', '')),
               ''.join('<li>%s</li>' % e(x) for x in (bf.get('terms') or {}).get(lang, [])),
               bf_gallery(lang),
               book_href(lang, city), e(u['cta'])))


DIR_LINK = {'epil': 'laser', 'cosm': 'cosmetology', 'electro': 'electro'}


def reviews_block(lang, n=3, alt=False, city='prague'):
    sec = SECTIONS[lang]
    revs = ''.join(f"""
      <figure class="rev"><div class="stars">★★★★★</div><p>{e(r['q'])}</p><cite>{e(r['name'])}</cite></figure>"""
                   for r in (reviews.get(lang) or reviews['ru'])[:n])
    return f"""
<section class="rose"><div class="wrap">
  <div class="sec-head"><h2>{e(sec['revs'])}</h2></div>
  {trust_link(city, lang)}
  <div class="revs">{revs}</div>
</div></section>"""


# ───────────────────────────────── главная ─────────────────────────────────
# ─────────────────── иконки карточек ───────────────────
# Простые линейные иконки: по одной на карточку принципов и отличий.
ICONS = {
 'target': '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.4"/><path d="M12 1.8v2.6M12 19.6v2.6M1.8 12h2.6M19.6 12h2.6"/>',
 'talk':   '<path d="M20.5 12.3c0 3.8-3.6 6.9-8 6.9-1 0-2-.2-2.9-.5L4.5 20.5l1.3-3.4c-1.3-1.2-2.1-2.9-2.1-4.8 0-3.8 3.6-6.9 8-6.9s8.8 3.1 8.8 6.9Z"/><path d="M8.8 12h.01M12 12h.01M15.2 12h.01"/>',
 'badge':  '<path d="M12 2.6l2.6 1.9 3.2-.2.6 3.1 2.4 2.1-1.6 2.8 1.6 2.8-2.4 2.1-.6 3.1-3.2-.2L12 21.4l-2.6-1.9-3.2.2-.6-3.1L3.2 14.5l1.6-2.8-1.6-2.8 2.4-2.1.6-3.1 3.2.2Z"/><path d="M9.2 12.1l1.9 1.9 3.7-3.9"/>',
 'clock':  '<circle cx="12" cy="12" r="8.6"/><path d="M12 7.2V12l3.2 2"/>',
 'shield': '<path d="M12 2.8l7.2 2.7v5.8c0 4.3-3 8.1-7.2 9.4-4.2-1.3-7.2-5.1-7.2-9.4V5.5Z"/><path d="M9 12.1l2 2.1 4.2-4.4"/>',
 'tune':   '<path d="M4.5 7.5h10M17 7.5h2.5M4.5 16.5h3M10 16.5h9.5"/><circle cx="15.5" cy="7.5" r="2.2"/><circle cx="8.5" cy="16.5" r="2.2"/>',
}
ICO_VALUES = ('target', 'talk', 'badge')      # «Почему к нам возвращаются»
ICO_ADVANT = ('clock', 'shield', 'tune')      # «Чем мы отличаемся»


def ico(key):
    """Кружок с линейной иконкой; неизвестный ключ просто ничего не рисует."""
    body = ICONS.get(key)
    if not body:
        return ''
    return ('<div class="card-ico" aria-hidden="true"><svg viewBox="0 0 24 24">%s</svg></div>' % body)


def icon_cards(items, keys):
    """Карточки «иконка — заголовок — текст» из списка пар (title, desc)."""
    out = ''
    for n, (t_, d_) in enumerate(items):
        out += ('<div class="card">%s<h3>%s</h3><p>%s</p></div>'
                % (ico(keys[n % len(keys)]), e(t_), e(d_)))
    return out


# ─────────────────── фото-блоки ───────────────────
PHOTO_BAND = {
 'ru': ('Hi Sisters Clinic',
        'Курс считаем под ваши параметры, а не по шаблону',
        'Перед первым сеансом смотрим тип волоса, фототип кожи и гормональный фон. От этого зависят '
        'мощность, интервалы между процедурами и само число сеансов — поэтому мы не обещаем «пять '
        'процедур всем», а считаем курс лично для вас и честно говорим, сколько он займёт.'),
 'uk': ('Hi Sisters Clinic',
        'Курс рахуємо під ваші параметри, а не за шаблоном',
        'Перед першим сеансом дивимось тип волосся, фототип шкіри та гормональний фон. Від цього залежать '
        'потужність, інтервали між процедурами і саме число сеансів — тому ми не обіцяємо «п’ять процедур '
        'усім», а рахуємо курс особисто для вас і чесно кажемо, скільки він триватиме.'),
 'cs': ('Hi Sisters Clinic',
        'Kurz počítáme podle vašich parametrů, ne podle šablony',
        'Před prvním sezením se díváme na typ chloupků, fototyp pleti a hormonální pozadí. Na tom závisí '
        'výkon, intervaly mezi procedurami i samotný počet sezení — proto neslibujeme „pět procedur pro '
        'všechny“, ale kurz počítáme přímo pro vás a na rovinu řekneme, jak dlouho potrvá.'),
 'en': ('Hi Sisters Clinic',
        'Your course is calculated for you, not from a template',
        'Before the first session we look at your hair type, skin phototype and hormonal background. Power, '
        'the intervals between sessions and the number of sessions all follow from that — so we never promise '
        '“five sessions for everyone”. We calculate the course for you and tell you honestly how long it takes.'),
 'es': ('Hi Sisters Clinic',
        'El curso se calcula según tus parámetros, no según una plantilla',
        'Antes de la primera sesión valoramos el tipo de vello, el fototipo de la piel y el fondo hormonal. '
        'De ahí dependen la potencia, los intervalos entre sesiones y el número de sesiones: por eso no '
        'prometemos «cinco sesiones para todas», calculamos el curso para ti y te decimos con honestidad '
        'cuánto durará.'),
}


def photo_band(lang, city, img='/assets/photos/band-gold.jpg'):
    """Широкая полоса со студийным кадром под затемнением и призывом записаться."""
    kick, head_, text = PHOTO_BAND[lang]
    h = HERO[lang]
    return f"""
<section class="photo-band" style="--pb-img:url('{img}')"><div class="wrap">
  <div class="pb-in">
    <div class="pb-kicker">{e(kick)}</div>
    <h2>{e(head_)}</h2>
    <p>{e(text)}</p>
    <div class="cta-row">
      <a class="btn btn-gold" href="{book_href(lang, city)}" data-book>{e(h['cta'])}</a>
      <span class="free">{e(h['free'])}</span>
    </div>
  </div>
</div></section>"""


def split_block(img, alt, head_, paras, points=(), sec_class='alt', rev=False):
    """Текст и фотография в две колонки: фото справа, если не указано иначе."""
    ps = ''.join('<p>%s</p>' % e(x) for x in paras)
    li = ''.join('<li>%s</li>' % e(x) for x in points)
    pic = ('<figure class="split-img"><img src="%s" alt="%s" loading="lazy" width="1100" height="780">'
           '</figure>' % (e(img), e(alt)))
    txt = ('<div class="split-txt"><h2>%s</h2>%s%s</div>'
           % (e(head_), ps, ('<ul>%s</ul>' % li) if li else ''))
    inner = (pic + txt) if rev else (txt + pic)
    return ('\n<section class="%s"><div class="wrap"><div class="split%s">%s</div></div></section>'
            % (sec_class, ' split-rev' if rev else '', inner))


# Тексты к фотографиям: по блоку на «О нас», обучение и косметологию.
SPLIT_ABOUT = {
 'ru': ('Мы работаем с кожей, а не с прайсом',
        ['Hi Sisters — это две студии: в Праге и в Валенсии. Начинали мы с эпиляции и остались в ней '
         'главными, а рядом выросли косметология, трихология и уход за кожей головы.',
         'Нам важно, чтобы человек уходил с планом, а не с абонементом: сколько сеансов нужно именно '
         'вам, через какие промежутки и что происходит между ними.'],
        ['Семь специалисток в Праге, включая врача-дерматолога',
         'Параметры подбираем на каждом сеансе заново',
         'Консультация перед первой процедурой — бесплатно']),
 'uk': ('Ми працюємо зі шкірою, а не з прайсом',
        ['Hi Sisters — це дві студії: у Празі та у Валенсії. Починали ми з епіляції й лишилися в ній '
         'головними, а поруч виросли косметологія, трихологія та догляд за шкірою голови.',
         'Нам важливо, щоб людина йшла з планом, а не з абонементом: скільки сеансів потрібно саме вам, '
         'через які проміжки і що відбувається між ними.'],
        ['Сім спеціалісток у Празі, включно з лікаркою-дерматологинею',
         'Параметри добираємо на кожному сеансі заново',
         'Консультація перед першою процедурою — безкоштовно']),
 'cs': ('Pracujeme s pletí, ne s ceníkem',
        ['Hi Sisters jsou dvě studia: v Praze a ve Valencii. Začínali jsme epilací a ta zůstala naší '
         'hlavní službou, vedle ní vyrostla kosmetologie, trichologie a péče o pokožku hlavy.',
         'Záleží nám na tom, aby klientka odcházela s plánem, ne s předplatným: kolik sezení potřebuje '
         'právě ona, v jakých rozestupech a co se děje mezi nimi.'],
        ['Sedm specialistek v Praze včetně lékařky dermatoložky',
         'Parametry nastavujeme znovu při každém sezení',
         'Konzultace před první procedurou je zdarma']),
 'en': ('We work with your skin, not with a price list',
        ['Hi Sisters is two studios: in Prague and in Valencia. We started with hair removal and it is '
         'still what we are known for, with skincare, trichology and scalp care growing alongside it.',
         'What matters to us is that you leave with a plan rather than a subscription: how many sessions '
         'you personally need, how far apart, and what happens in between.'],
        ['Seven specialists in Prague, including a dermatologist',
         'Settings are chosen afresh at every session',
         'The consultation before your first treatment is free']),
 'es': ('Trabajamos con tu piel, no con una lista de precios',
        ['Hi Sisters son dos estudios: en Praga y en Valencia. Empezamos con la depilación y sigue siendo '
         'lo nuestro; junto a ella crecieron la cosmetología, la tricología y el cuidado del cuero cabelludo.',
         'Nos importa que salgas con un plan y no con un bono: cuántas sesiones necesitas tú, con qué '
         'intervalos y qué ocurre entre una y otra.'],
        ['Siete especialistas en Praga, incluida una médica dermatóloga',
         'Los parámetros se ajustan en cada sesión',
         'La consulta antes del primer tratamiento es gratuita']),
}

SPLIT_TRAIN = {
 'ru': ('Учат те, кто каждый день работает в клинике',
        ['Курсы ведут мастера Hi Sisters — на тех же аппаратах и по тем же протоколам, что и с клиентами. '
         'Поэтому разговор идёт не про идеальные случаи из учебника, а про то, что реально приходит в кабинет.',
         'Программа каждого курса расписана ниже: видно, что разбираем в теории и что отрабатываем руками.']),
 'uk': ('Навчають ті, хто щодня працює в клініці',
        ['Курси ведуть майстрині Hi Sisters — на тих самих апаратах і за тими самими протоколами, що й з '
         'клієнтами. Тому мова йде не про ідеальні випадки з підручника, а про те, що реально приходить у кабінет.',
         'Програма кожного курсу розписана нижче: видно, що розбираємо в теорії і що відпрацьовуємо руками.']),
 'cs': ('Učí ty, které v klinice pracují každý den',
        ['Kurzy vedou specialistky Hi Sisters — na stejných přístrojích a podle stejných protokolů jako '
         's klientkami. Nejde tedy o ideální případy z učebnice, ale o to, co do ordinace opravdu chodí.',
         'Program každého kurzu je rozepsaný níže: je vidět, co probíráme v teorii a co si osaháte rukama.']),
 'en': ('Taught by the people who work in the clinic every day',
        ['The courses are run by Hi Sisters specialists, on the same machines and the same protocols they '
         'use with clients. So the conversation is about what actually walks into the room, not textbook cases.',
         'The programme of every course is listed below: you can see what we cover in theory and what you '
         'practise with your own hands.']),
 'es': ('Enseñan quienes trabajan en la clínica cada día',
        ['Los cursos los imparten las especialistas de Hi Sisters, con los mismos equipos y protocolos que '
         'usan con las clientas. Por eso hablamos de lo que llega de verdad a la cabina, no de casos de manual.',
         'El programa de cada curso está detallado abajo: se ve qué vemos en teoría y qué se practica a mano.']),
}

SPLIT_COSM = {
 'ru': ('Протокол подбираем под состояние кожи',
        ['Перед процедурой смотрим на состояние кожи, а не на список популярных услуг: от этого зависит, '
         'что подойдёт именно сейчас, а что лучше отложить на потом.',
         'Препараты и концентрации подбираем под задачу — и честно говорим, если за одну процедуру нужного '
         'эффекта не будет.']),
 'uk': ('Протокол добираємо під стан шкіри',
        ['Перед процедурою дивимось на стан шкіри, а не на список популярних послуг: від цього залежить, '
         'що підійде саме зараз, а що краще відкласти.',
         'Препарати й концентрації добираємо під задачу — і чесно кажемо, якщо за одну процедуру потрібного '
         'ефекту не буде.']),
 'cs': ('Protokol volíme podle stavu pleti',
        ['Před procedurou se díváme na stav pleti, ne na seznam oblíbených služeb: podle toho se pozná, '
         'co se hodí právě teď a co je lepší odložit.',
         'Přípravky a koncentrace volíme podle cíle — a na rovinu řekneme, když jedna procedura na '
         'požadovaný výsledek stačit nebude.']),
 'en': ('The protocol follows the condition of your skin',
        ['Before a treatment we look at the state of your skin rather than at a list of popular services: '
         'that is what decides what suits you now and what is better postponed.',
         'Products and concentrations are chosen for the goal — and we say honestly when one session will '
         'not get you the result you want.']),
 'es': ('El protocolo se elige según el estado de la piel',
        ['Antes del tratamiento miramos el estado de la piel y no una lista de servicios populares: de ahí '
         'depende qué conviene ahora y qué es mejor dejar para más adelante.',
         'Los productos y las concentraciones se eligen según el objetivo, y decimos con honestidad cuando '
         'una sola sesión no dará el resultado buscado.']),
}


def build_home(lang, city):
    """Коротко: кто мы, сколько стоит, что говорят — и кнопка записи."""
    st = studios[city]
    h = HERO[lang]; pf = PROOF[lang]; sec = SECTIONS[lang]
    cityname = st['city'].get(lang, st['city']['en'])
    price = hero_price(city, lang)
    hours = (st.get('hours') or {}).get(lang, '')

    dirs = ''
    for dkey, grp in DIR_GROUPS[city]:
        dt, dd = DIR_TEXT[lang][dkey]
        pf_ = group_from(grp, city, lang)
        tgt = DIR_LINK[dkey]
        href = ('/%s/%s/%s/' % (lang, city, tgt)
                if tgt in services and city in services[tgt]['cities'] and services[tgt]['page'].get(lang)
                else '/%s/%s/services/' % (lang, city))
        dirs += ('<a class="dir" href="%s"><b>%s</b><span>%s</span>%s</a>'
                 % (href, e(dt), e(dd), '<em>%s</em>' % e(pf_) if pf_ else ''))

    vals = (pick(ui['about'], lang).get('values') or [])[:3]
    why = icon_cards([(v['title'], v['desc']) for v in vals], ICO_VALUES)

    title = '%s %s — Hi Sisters Clinic' % (KICKER[city][lang], cityname)
    desc = '%s %s%s.' % (h['lead'], (price + '. ') if price else '', st['address'])

    main = f"""
<section class="hero"><div class="wrap"><div class="hero-grid"><div>
  <h1 class="h1-seo">{e(H1_SEO[city][lang])}</h1>
  <p class="slogan">{slogan_html(lang)}</p>
  <p class="lead">{e(h['lead'])}</p>
  <div class="dirs">{dirs}</div>
  <div class="cta-row">
    <a class="btn btn-gold" href="{book_href(lang, city)}" data-book>{e(h['cta'])}</a>
    <a class="btn btn-ghost" href="/{lang}/{city}/services/">{e(h['cta2'])}</a>
    <span class="free">{e(h['free'])}</span>
  </div>
  <div class="proof">
    {clients_badge(lang)}
    <div class="proof-side">
      {trust_link(city, lang)}
      <div class="proof-years"><b>7+</b> {e(pf['years'])}</div>
    </div>
  </div>
  <p class="where">{e(cityname)} · <a href="{st.get('maps','#')}" target="_blank" rel="noopener">{e(st['address'])}</a>{' · ' + e(hours) if hours else ''}</p>
</div>
  <figure class="hero-pic">
    <div class="hero-mark" role="img" aria-label="Hi Sisters Clinic">
      <span class="m-top"></span><span class="m-sub"></span>
    </div>
    <figcaption>{e(studios['prague']['city'].get(lang, 'Praha'))} · {e(studios['valencia']['city'].get(lang, 'Valencia'))}</figcaption>
  </figure>
</div></div></section>
{bf_block(lang, city)}
{services_list(lang, city)}
<section class="rose rose-photo"><div class="wrap">
  <div class="sec-head"><h2>{e(sec['why'])}</h2></div>
  <div class="cards">{why}</div>
</div></section>
{team_mini(lang, city)}
{advantages_block(lang, city)}
{photo_band(lang, city)}
""" + reviews_block(lang, 3, city=city)
    return doc(lang, city, '', 'home', title, desc, main, schema=jld(biz_schema(lang, city)))


# ──────────────────────────────── услуги ────────────────────────────────
SLIDE_UI = {
 'ru': {'kick': 'Прайс', 'hint': 'Листайте вбок', 'prev': 'Назад', 'next': 'Вперёд'},
 'uk': {'kick': 'Прайс', 'hint': 'Гортайте вбік', 'prev': 'Назад', 'next': 'Вперед'},
 'cs': {'kick': 'Ceník', 'hint': 'Posouvejte do strany', 'prev': 'Zpět', 'next': 'Dál'},
 'en': {'kick': 'Price list', 'hint': 'Swipe sideways', 'prev': 'Back', 'next': 'Next'},
 'es': {'kick': 'Tarifa', 'hint': 'Desliza a un lado', 'prev': 'Atrás', 'next': 'Siguiente'},
}

SLIDES_JS = """
(function(){
  var box=document.getElementById('pslides'); if(!box) return;
  function step(d){
    var c=box.querySelector('.pslide'); if(!c) return;
    box.scrollBy({left:d*(c.offsetWidth+14),behavior:'smooth'});
  }
  var p=document.getElementById('pprev'), n=document.getElementById('pnext');
  if(p) p.addEventListener('click',function(){step(-1);});
  if(n) n.addEventListener('click',function(){step(1);});
})();
"""


def price_slides(lang, city):
    """Прайс карточками, которые листаются вбок: одна услуга — один слайд."""
    u = SLIDE_UI[lang]
    h = HERO[lang]
    cards = ''
    for grp in pgroups(city, lang):
        rows = price_rows(grp, city, lang, order=False)
        if not rows:
            continue
        t_ = (PGROUP_TITLE.get(grp) or {}).get(lang, grp)
        cards += ('<article class="pslide"><div class="pslide-in">'
                  '<div class="pslide-kick">%s</div><h3>%s</h3>%s'
                  '<div class="pslide-cta"><a class="btn btn-sm" href="%s" data-book>%s</a></div>'
                  '</div></article>'
                  % (e(u['kick']), e(t_), rows, book_href(lang, city), e(h['cta'])))
    if not cards:
        return ''
    return ('<div class="pslides" id="pslides">%s</div>'
            '<div class="pnav"><button id="pprev" type="button" aria-label="%s">\u2039</button>'
            '<button id="pnext" type="button" aria-label="%s">\u203a</button>'
            '<span class="pnav-hint">%s</span></div>'
            '<script>%s</script>'
            % (cards, e(u['prev']), e(u['next']), e(u['hint']), SLIDES_JS))


def service_blocks(lang, city):
    """Короткий разбор каждой услуги: кому, как идёт курс, чего ждать."""
    t = svcblocks['title'][lang]
    more = svcblocks['more'][lang]
    out = ''
    for it in svcblocks['items']:
        key = it['key']
        if key not in services or city not in services[key]['cities']:
            continue
        d = it.get(lang) or it['ru']
        price = group_from(SERVICE_GROUP.get(city, {}).get(key, ''), city, lang)
        link = ('<a class="btn btn-sm btn-ghost" href="/%s/%s/%s/">%s</a>'
                % (lang, city, key, e(more))) if services[key]['page'].get(lang) else ''
        out += ('<article class="svc-block"><h3>%s</h3><p>%s</p><ul>%s</ul>'
                '<div class="svc-block-foot">%s%s</div></article>'
                % (e(d['h']), e(d['p']),
                   ''.join('<li>%s</li>' % e(x) for x in d['li']),
                   ('<span class="svc-price">%s</span>' % e(price)) if price else '',
                   link))
    if not out:
        return ''
    return ('<section class="lilac"><div class="wrap">'
            '<div class="sec-head"><h2>%s</h2></div>'
            '<div class="svc-blocks">%s</div></div></section>' % (e(t), out))


def build_services(lang, city):
    """Все услуги города и полный прайс одной страницей."""
    st = studios[city]
    h = HERO[lang]; sec = SECTIONS[lang]; sp = SERVICES_PAGE[lang]
    cityname = st['city'].get(lang, st['city']['en'])
    u_faq = pick(ui['faq'], lang)

    cards = ''
    flat = []
    for k, s in services.items():
        if city not in s['cities']:
            continue
        c = s['card'].get(lang)
        if not c:
            continue
        if not s['page'].get(lang):
            flat.append(c.get('title', ''))
            continue
        svc_price = group_from(SERVICE_GROUP.get(city, {}).get(k, ''), city, lang)
        img = s['image'] or ''
        imgtag = ('<img src="/assets/%s" alt="%s" loading="lazy" width="520" height="390">'
                  % (e(img.split('/')[-1]), e(c['title']))) if img else ''
        cards += f"""
      <article class="svc-card">{imgtag}
        <div class="svc-body">
          <h3>{e(c['title'])}</h3>
          <p>{e(c['desc'])}</p>
          <div class="svc-foot">
            <span class="svc-price">{e(svc_price or '')}</span>
            <a class="btn btn-sm btn-ghost" href="/{lang}/{city}/{k}/">{e(MORE_LABEL[lang])}</a>
          </div>
        </div>
      </article>"""
    more = ''.join('<span class="more-flat">%s</span>' % e(t) for t in flat)

    blocks = price_slides(lang, city)

    faqs = ''.join('<details><summary>%s</summary><div class="ans">%s</div></details>'
                   % (e(f['q']), e(f['a'])) for f in u_faq.get('faq', []))

    main = f"""
<section class="hero hero-sm"><div class="wrap">
  <div class="kicker">{e(nav_label('services', lang))} · {e(cityname)}</div>
  <h1>{e(sp['h1'])}</h1>
  <p class="lead">{e(sp['lead'])}</p>
  <div class="cta-row">
    <a class="btn btn-gold" href="{book_href(lang, city)}" data-book>{e(h['cta'])}</a>
    <span class="free">{e(h['free'])}</span>
  </div>
</div></section>

<section class="alt"><div class="wrap">
  <div class="sec-head"><h2>{e(sec['services'])}</h2></div>
  <div class="svc">{cards}</div>
  {'<div class="more-list">' + more + '</div>' if more else ''}
</div></section>

<section id="prices" class="tint"><div class="wrap">
  <div class="sec-head"><h2>{e(sec['allPrices'])}</h2><p>{e(sec['pricesNote'])}</p></div>
  {blocks}
</div></section>

{service_blocks(lang, city)}
{'<section class="alt"><div class="wrap"><div class="sec-head"><h2>' + e(u_faq.get('title','')) + '</h2></div><div class="faq">' + faqs + '</div></div></section>' if faqs else ''}
"""
    title = '%s — %s, Hi Sisters Clinic' % (sp['h1'], cityname)
    sch = (jld(biz_schema(lang, city)) + faq_schema(u_faq.get('faq', []))
           + crumbs(lang, city, [(sp['h1'], REL['services'])]))
    return doc(lang, city, REL['services'], 'services', title, sp['lead'], main, schema=sch)


# ──────────────────────────────── косметика ────────────────────────────────
COSM_NOTE_ES = {
 'ru': 'Линейка для тела есть в студии в Валенсии. Косметика для волос и кожи головы — в пражской клинике.',
 'uk': 'Лінійка для тіла є в студії у Валенсії. Косметика для волосся та шкіри голови — у празькій клініці.',
 'cs': 'Tělová řada je k dostání ve studiu ve Valencii. Kosmetika na vlasy a pokožku hlavy je v pražské klinice.',
 'en': 'The body line is available at the Valencia studio. Hair and scalp care is stocked at the Prague clinic.',
 'es': 'La línea corporal está disponible en el estudio de Valencia. La cosmética para el cabello y el cuero cabelludo está en la clínica de Praga.',
}


SHOP_CATS = ['hair-loss', 'hair-wash', 'hair-care', 'face', 'body', 'intimate']
SHOP_CAT_NAME = {
 'ru': {'hair-loss':'Против выпадения волос','hair-wash':'Шампуни и очищение',
        'hair-care':'Уход за волосами','face':'Уход за лицом','body':'Уход за телом',
        'intimate':'Интимный уход'},
 'uk': {'hair-loss':'Проти випадіння волосся','hair-wash':'Шампуні та очищення',
        'hair-care':'Догляд за волоссям','face':'Догляд за обличчям','body':'Догляд за тілом',
        'intimate':'Інтимний догляд'},
 'cs': {'hair-loss':'Proti vypadávání vlasů','hair-wash':'Šampony a čištění',
        'hair-care':'Péče o vlasy','face':'Péče o pleť','body':'Péče o tělo',
        'intimate':'Intimní péče'},
 'en': {'hair-loss':'Against hair loss','hair-wash':'Shampoos and cleansing',
        'hair-care':'Hair care','face':'Facial care','body':'Body care',
        'intimate':'Intimate care'},
 'es': {'hair-loss':'Anticaída del cabello','hair-wash':'Champús y limpieza',
        'hair-care':'Cuidado del cabello','face':'Cuidado facial','body':'Cuidado corporal',
        'intimate':'Cuidado íntimo'},
}
SHOP_CAT_SHORT = {
 'ru': {'hair-loss':'Против выпадения','hair-wash':'Шампуни','hair-care':'Волосы',
        'face':'Лицо','body':'Тело','intimate':'Интим'},
 'uk': {'hair-loss':'Проти випадіння','hair-wash':'Шампуні','hair-care':'Волосся',
        'face':'Обличчя','body':'Тіло','intimate':'Інтим'},
 'cs': {'hair-loss':'Proti vypadávání','hair-wash':'Šampony','hair-care':'Vlasy',
        'face':'Pleť','body':'Tělo','intimate':'Intim'},
 'en': {'hair-loss':'Hair loss','hair-wash':'Shampoos','hair-care':'Hair',
        'face':'Face','body':'Body','intimate':'Intimate'},
 'es': {'hair-loss':'Anticaída','hair-wash':'Champús','hair-care':'Cabello',
        'face':'Rostro','body':'Cuerpo','intimate':'Íntimo'},
}

CAT_SHORT = {
 'ru': {'loss':'Против выпадения','scalp':'Шампуни','care':'Уход','body':'Тело'},
 'uk': {'loss':'Проти випадіння','scalp':'Шампуні','care':'Догляд','body':'Тіло'},
 'cs': {'loss':'Proti vypadávání','scalp':'Šampony','care':'Péče','body':'Tělo'},
 'en': {'loss':'Hair loss','scalp':'Shampoos','care':'Care','body':'Body'},
 'es': {'loss':'Anticaída','scalp':'Champús','care':'Cuidado','body':'Cuerpo'},
}

SHOP_UI = {
 'ru': {'title':'Каталог','brand':'Бренд','cat':'Назначение','all':'Все','sort':'Сортировка',
        'def':'По подбору','asc':'Сначала дешевле','desc':'Сначала дороже',
        'count':'Товаров: ','empty':'По этим фильтрам ничего нет — снимите один из них.',
        'body':'Уход за телом'},
 'uk': {'title':'Каталог','brand':'Бренд','cat':'Призначення','all':'Усі','sort':'Сортування',
        'def':'За добором','asc':'Спочатку дешевші','desc':'Спочатку дорожчі',
        'count':'Товарів: ','empty':'За цими фільтрами нічого немає — зніміть один із них.',
        'body':'Догляд за тілом'},
 'cs': {'title':'Katalog','brand':'Značka','cat':'Určení','all':'Vše','sort':'Řazení',
        'def':'Dle výběru','asc':'Od nejlevnějšího','desc':'Od nejdražšího',
        'count':'Produktů: ','empty':'S těmito filtry nic nenajdeme — jeden z nich zrušte.',
        'body':'Péče o tělo'},
 'en': {'title':'Catalogue','brand':'Brand','cat':'Purpose','all':'All','sort':'Sort',
        'def':'Recommended','asc':'Price, low to high','desc':'Price, high to low',
        'count':'Products: ','empty':'Nothing matches these filters — clear one of them.',
        'body':'Body care'},
 'es': {'title':'Catálogo','brand':'Marca','cat':'Para qué','all':'Todos','sort':'Orden',
        'def':'Recomendado','asc':'Precio, de menor a mayor','desc':'Precio, de mayor a menor',
        'count':'Productos: ','empty':'Nada coincide con estos filtros: quita uno.',
        'body':'Cuidado corporal'},
}

NAV_JS = """(function(){
  var subs=[].slice.call(document.querySelectorAll('.has-sub'));
  subs.forEach(function(el){
    var btn=el.querySelector('.nav-x');
    if(!btn) return;
    btn.addEventListener('click',function(ev){
      ev.preventDefault();
      var open=el.classList.toggle('is-open');
      btn.setAttribute('aria-expanded',open?'true':'false');
    });
  });
  document.addEventListener('click',function(ev){
    subs.forEach(function(el){
      if(!el.contains(ev.target)) el.classList.remove('is-open');
    });
  });
})();"""

SHOP_JS = """
(function(){
  var grid=document.getElementById('shop-grid'); if(!grid) return;
  var cards=[].slice.call(grid.children);
  var nEl=document.getElementById('shop-n');
  var empty=document.getElementById('shop-empty');
  var sel=document.getElementById('shop-sort');
  var f={brand:'',cat:'',stock:'',top:'',q:[]};
  cards.forEach(function(c){
    var a=c.querySelector('.prod-order'); if(!a) return;
    var tpl=grid.dataset[c.dataset.stock==='pre'?'msgpre':'msg']||'{p}';
    a.href=a.getAttribute('href')+'?text='+encodeURIComponent(tpl.replace('{p}',a.dataset.p));
  });
  var more=document.getElementById('shop-more'), rowsEl=document.getElementById('shop-rows');
  if(more&&rowsEl){ more.addEventListener('click',function(){
    var open=rowsEl.classList.toggle('is-open');
    more.setAttribute('aria-expanded',open?'true':'false');
    more.classList.toggle('is-on',open); }); }
  var q=document.getElementById('shop-q');
  function stem(w){ return w.length>5?w.slice(0,w.length-2):(w.length>3?w.slice(0,w.length-1):w); }
  function terms(v){
    return v.toLowerCase().replace(/[^0-9a-zа-яёіїєáčďéěíňóřšťúůýžäöüñ]+/g,' ')
            .split(' ').filter(function(w){return w.length>1;}).map(stem);
  }
  if(q){ var t; q.addEventListener('input',function(){
    clearTimeout(t); t=setTimeout(function(){ f.q=terms(q.value); apply(); },150); }); }
  function apply(){
    var n=0;
    cards.forEach(function(c){
      var ok=(!f.brand||c.dataset.brand===f.brand)&&(!f.cat||c.dataset.cat===f.cat)
             &&(!f.stock||c.dataset.stock===f.stock)&&(!f.top||c.dataset.top==='1')
             &&(!f.q||!f.q.length||f.q.every(function(w){
                 return (c.querySelector('.prod-pic').dataset.q||'').indexOf(w)>=0; }));
      c.hidden=!ok; if(ok) n++;
    });
    if(nEl) nEl.textContent=n;
    if(empty) empty.hidden=n>0;
  }
  function sort(){
    var v=sel?sel.value:'def';
    var a=cards.slice();
    if(v==='asc') a.sort(function(x,y){return x.dataset.price-y.dataset.price;});
    else if(v==='desc') a.sort(function(x,y){return y.dataset.price-x.dataset.price;});
    else a.sort(function(x,y){return x.dataset.ord-y.dataset.ord;});
    a.forEach(function(c){grid.appendChild(c);});
  }
  [].forEach.call(document.querySelectorAll('.chips'),function(box){
    box.addEventListener('click',function(ev){
      var b=ev.target.closest('.chip'); if(!b) return;
      [].forEach.call(box.children,function(x){x.classList.remove('is-on');});
      b.classList.add('is-on');
      f[box.dataset.f]=b.dataset.v||'';
      apply();
    });
  });
  if(sel) sel.addEventListener('change',sort);
  apply();
})();
"""


def shop_block(lang, city, cur):
    """Каталог с фильтрами по бренду и назначению и сортировкой по цене."""
    u = SHOP_UI[lang]
    cu = cosm['ui'][lang]
    cat_name = dict(cu['cats'])
    cat_name['body'] = u['body']
    short = dict(CAT_SHORT[lang])

    if city == 'prague':
        order = {c: n for n, c in enumerate(SHOP_CATS)}
        items = sorted(shop_items, key=lambda it: (0 if it.get('top') else 1,
                                                   -(it.get('top') or 0),
                                                   order.get(it['cat'], 9), it['brand'],
                                                   it['price']))
        cat_name = dict(SHOP_CAT_NAME[lang])
        short = dict(SHOP_CAT_SHORT[lang])
    else:
        items = [dict(p, cat='body') for p in cosm['body'].get(city, [])]
        cat_name['body'] = SHOP_CAT_NAME[lang]['body']
        short = dict(CAT_SHORT[lang])
        short['body'] = SHOP_CAT_SHORT[lang]['body']
    if not items:
        return ''

    brands, cats = [], []
    for it in items:
        b = it.get('brand')
        if b and b not in brands:
            brands.append(b)
        if it['cat'] not in cats:
            cats.append(it['cat'])

    def chips(key, vals, label):
        if len(vals) < 2:
            return ''
        bs = '<button class="chip is-on" type="button" data-v="">%s</button>' % e(u['all'])
        bs += ''.join('<button class="chip" type="button" data-v="%s">%s</button>' % (e(v), e(t))
                      for v, t in vals)
        return ('<div class="shop-row"><span class="shop-lbl">%s</span>'
                '<div class="chips" data-f="%s">%s</div></div>' % (e(label), key, bs))

    su = STOCK_UI[lang]
    stocks = [k for k in ('in', 'pre') if any(it.get('stock') == k for it in items)]
    bar = ('<div class="shop-row shop-find"><input type="search" id="shop-q" '
           'placeholder="%s" autocomplete="off" aria-label="%s">'
           '<button class="chip shop-toggle" type="button" id="shop-more" '
           'aria-expanded="false" aria-controls="shop-rows">%s</button></div>'
           % (e(SHOP_SEARCH[lang]), e(SHOP_SEARCH[lang]), e(SHOP_FILTERS[lang])))
    rows = chips('brand', [(b, b) for b in brands], u['brand'])
    rows += chips('cat', [(c, cat_name.get(c, c)) for c in cats], u['cat'])
    rows += chips('stock', [(k, su['in'] if k == 'in' else su['pre']) for k in stocks], su['label'])
    if any(it.get('top') for it in items):
        tf = TOP_FILTER[lang]
        rows += ('<div class="shop-row"><span class="shop-lbl">%s</span>'
                '<div class="chips" data-f="top">'
                '<button class="chip is-on" type="button" data-v="">%s</button>'
                '<button class="chip" type="button" data-v="1">%s</button></div></div>'
                % (e(tf[0]), e(u['all']), e(tf[1])))
    rows += ('<div class="shop-row"><label class="shop-lbl" for="shop-sort">%s</label>'
            '<select class="shop-sort" id="shop-sort">'
            '<option value="def">%s</option><option value="asc">%s</option>'
            '<option value="desc">%s</option></select></div>'
            % (e(u['sort']), e(u['def']), e(u['asc']), e(u['desc'])))
    bar += '<div class="shop-rows" id="shop-rows">%s</div>' % rows

    cards = ''.join(prod_card(it, lang, city, cur, n, short.get(it['cat'], ''))
                    for n, it in enumerate(items))
    if len(brands) > 2 and city == 'prague':
        links = ', '.join('<a href="/%s/%s/%s%s/">%s</a>'
                          % (lang, city, REL['cosmetics'], brand_slug(b), e(b))
                          for b in sorted(brands, key=lambda x: x.lower()))
        brands_line = '<p class="shop-brands">%s: %s.</p>' % (e(SHOP_BRANDS_LEAD[lang]), links)
    elif len(brands) > 2:
        brands_line = ('<p class="shop-brands">%s: %s.</p>'
                       % (e(SHOP_BRANDS_LEAD[lang]),
                          e(', '.join(sorted(brands, key=lambda x: x.lower())))))
    else:
        brands_line = ''
    return ("""
<section class="rose"><div class="wrap">
  <div class="sec-head"><h2>%s</h2>%s</div>
  <div class="shop-bar">%s</div>
  <div class="shop-count">%s<span id="shop-n">%d</span></div>
  <div class="prods" id="shop-grid" data-msg="%s" data-msgpre="%s">%s</div>
  <p class="shop-empty" id="shop-empty" hidden>%s</p>
</div></section>
<script>%s</script>""" % (e(u['title']), brands_line, bar, e(u['count']), len(items),
                          e(ORDER_UI[lang]['msg']), e(STOCK_UI[lang]['msgPre']), cards,
                          e(u['empty']), SHOP_JS))


SHOP_FILTERS = {"ru": "Фильтры", "uk": "Фільтри", "cs": "Filtry", "en": "Filters", "es": "Filtros"}

SHOP_SEARCH = {
  "ru": "Поиск по названию или бренду",
  "uk": "Пошук за назвою або брендом",
  "cs": "Hledat podle názvu nebo značky",
  "en": "Search by name or brand",
  "es": "Buscar por nombre o marca"
 }

BRAND_UI = {
  "ru": {
   "buy": "купить в Праге",
   "all": "Весь каталог",
   "items": "Средств в каталоге",
   "lead": "Профессиональная косметика %s, с которой мы работаем в клинике. Подбираем после консультации, привозим под заказ."
  },
  "uk": {
   "buy": "купити в Празі",
   "all": "Увесь каталог",
   "items": "Засобів у каталозі",
   "lead": "Професійна косметика %s, з якою ми працюємо в клініці. Добираємо після консультації, привозимо під замовлення."
  },
  "cs": {
   "buy": "koupit v Praze",
   "all": "Celý katalog",
   "items": "Přípravků v katalogu",
   "lead": "Profesionální kosmetika %s, se kterou pracujeme na klinice. Vybíráme po konzultaci, vozíme na objednávku."
  },
  "en": {
   "buy": "buy in Prague",
   "all": "Full catalogue",
   "items": "Products in the catalogue",
   "lead": "Professional %s skincare we work with at the clinic. Chosen after a consultation, brought in to order."
  },
  "es": {
   "buy": "comprar en Praga",
   "all": "Catálogo completo",
   "items": "Productos en el catálogo",
   "lead": "Cosmética profesional %s con la que trabajamos en la clínica. La elegimos tras una consulta y la traemos bajo pedido."
  }
 }

SHOP_BRANDS_LEAD = {"ru": "Бренды в каталоге", "uk": "Бренди в каталозі", "cs": "Značky v katalogu", "en": "Brands in the catalogue", "es": "Marcas del catálogo"}

STOCK_UI = {
 'ru': {'label': 'Наличие', 'in': 'В наличии', 'pre': 'Под заказ', 'btnPre': 'Предзаказ',
        'msgPre': 'Здравствуйте! Хочу оформить предзаказ: {p}'},
 'uk': {'label': 'Наявність', 'in': 'В наявності', 'pre': 'Під замовлення',
        'btnPre': 'Передзамовлення', 'msgPre': 'Вітаю! Хочу оформити передзамовлення: {p}'},
 'cs': {'label': 'Dostupnost', 'in': 'Skladem', 'pre': 'Na objednávku',
        'btnPre': 'Předobjednat', 'msgPre': 'Dobrý den! Chtěla bych předobjednat: {p}'},
 'en': {'label': 'Availability', 'in': 'In stock', 'pre': 'To order',
        'btnPre': 'Pre-order', 'msgPre': 'Hello! I would like to pre-order: {p}'},
 'es': {'label': 'Disponibilidad', 'in': 'En stock', 'pre': 'Bajo pedido',
        'btnPre': 'Reservar', 'msgPre': '¡Hola! Me gustaría reservar: {p}'},
}

TOP_UI = {'ru': 'Хит', 'uk': 'Хіт', 'cs': 'Hit', 'en': 'Bestseller', 'es': 'Top ventas'}
TOP_FILTER = {'ru': ('Подборка', 'Хиты продаж'), 'uk': ('Добірка', 'Хіти продажів'),
              'cs': ('Výběr', 'Nejprodávanější'), 'en': ('Picks', 'Bestsellers'),
              'es': ('Selección', 'Más vendidos')}

PRICE_ASK = {'ru': 'Цена — на консультации', 'uk': 'Ціна — на консультації',
             'cs': 'Cena — na konzultaci', 'en': 'Price on consultation',
             'es': 'Precio en la consulta'}

ORDER_UI = {
 'ru': {'btn': 'Заказать', 'ing': 'Состав', 'full': 'Полный состав — на упаковке.',
        'msg': 'Здравствуйте! Хочу заказать: {p}'},
 'uk': {'btn': 'Замовити', 'ing': 'Склад', 'full': 'Повний склад — на упаковці.',
        'msg': 'Вітаю! Хочу замовити: {p}'},
 'cs': {'btn': 'Objednat', 'ing': 'Složení', 'full': 'Úplné složení najdete na obalu.',
        'msg': 'Dobrý den! Chtěla bych objednat: {p}'},
 'en': {'btn': 'Order', 'ing': 'Ingredients', 'full': 'The full ingredient list is on the pack.',
        'msg': 'Hello! I would like to order: {p}'},
 'es': {'btn': 'Pedir', 'ing': 'Composición', 'full': 'La composición completa está en el envase.',
        'msg': '¡Hola! Me gustaría pedir: {p}'},
}


def order_href(city, lang, product, pre=False):
    """Кнопка заказа ведёт в WhatsApp с уже набранным сообщением."""
    st = studios[city]
    phone = re.sub(r'[^0-9]', '', st['phone'])
    tpl = STOCK_UI[lang]['msgPre'] if pre else ORDER_UI[lang]['msg']
    text = tpl.format(p=product)
    return 'https://wa.me/%s?text=%s' % (phone, quote(text))


# ───────── запись через WhatsApp: текст подставляется сам ─────────
# Формулировки по ТЗ: сообщение зависит от языка, а на страницах услуг
# в него подставляются название процедуры и город.
WA_BOOK = {
 'ru': {'btn': 'Написать в WhatsApp', 'msg': 'Здравствуйте! Хочу записаться на процедуру.',
        'ctx': 'Здравствуйте! Хочу записаться: {p}. Город: {c}.'},
 'uk': {'btn': 'Написати у WhatsApp', 'msg': 'Добрий день! Хочу записатися на процедуру.',
        'ctx': 'Добрий день! Хочу записатися: {p}. Місто: {c}.'},
 'cs': {'btn': 'Napsat na WhatsApp', 'msg': 'Dobrý den! Chtěla bych se objednat na proceduru.',
        'ctx': 'Dobrý den! Chtěla bych se objednat: {p}. Město: {c}.'},
 'en': {'btn': 'Message on WhatsApp', 'msg': 'Hello! I would like to book a treatment.',
        'ctx': 'Hello! I would like to book: {p}. City: {c}.'},
 'es': {'btn': 'Escribir por WhatsApp', 'msg': '¡Hola! Quiero pedir una cita para un tratamiento.',
        'ctx': '¡Hola! Quiero pedir una cita: {p}. Ciudad: {c}.'},
}


def wa_book(lang, city, what=None):
    """Ссылка на WhatsApp с готовым текстом; если известна процедура — с её названием."""
    w = WA_BOOK[lang]
    cityname = studios[city]['city'].get(lang, studios[city]['city']['en'])
    text = w['ctx'].format(p=what, c=cityname) if what else w['msg']
    return 'https://wa.me/%s?text=%s' % (re.sub(r'[^0-9]', '', studios[city]['phone']), quote(text))


def wa_btn(lang, city, what=None):
    return ('<a class="btn btn-wa" href="%s" target="_blank" rel="noopener" data-wa>%s</a>'
            % (wa_book(lang, city, what), e(WA_BOOK[lang]['btn'])))


def wa_base(city):
    return 'https://wa.me/%s' % re.sub(r'[^0-9]', '', studios[city]['phone'])


def article_block(key, lang, sec_class='tint'):
    """Разъяснительный текст: заголовок, вводка и несколько подзаголовков."""
    a = (articles.get(key) or {}).get(lang) or (articles.get(key) or {}).get('ru')
    if not a:
        return ''
    body = ''.join('<article class="art-item"><h3>%s</h3><p>%s</p></article>'
                   % (e(x['h']), e(x['p'])) for x in a.get('items', []))
    return ('<section class="%s"><div class="wrap">'
            '<div class="sec-head"><h2>%s</h2><p>%s</p></div>'
            '<div class="art-grid">%s</div>'
            '</div></section>' % (sec_class, e(a['h']), e(a.get('lead', '')), body))


def tight(html):
    """Убираем отступы разметки: на 400 карточках это сотни килобайт."""
    return re.sub(r'\n\s+', '\n', html).strip()


def search_key(*parts):
    """Строка для поиска: без знаков препинания, чтобы «шампунь против перхоти» находился."""
    t = ' '.join(x for x in parts if x).lower()
    return re.sub(r'\s+', ' ', re.sub(r'[^0-9a-zа-яёіїєáčďéěíňóřšťúůýžäöüñ]+', ' ', t)).strip()


def prod_name(p, lang):
    """В СРМ часть названий записана по-русски — на других языках подменяем."""
    row = shop_names.get(p['name'])
    return (row or {}).get(lang) or p['name']


def prod_vol(vol, lang):
    for a, b in (VOL_UNITS.get(lang) or {}).items():
        if vol.endswith(a):
            return vol[:-len(a)] + b
    return vol


def prod_card(p, lang, city, cur, ord_=0, cat_label=''):
    """Фото, назначение, состав, цена и кнопка заказа — всё в одной карточке."""
    u = ORDER_UI[lang]
    brand = p.get('brand', '')
    name = prod_name(p, lang)
    full = (brand + ' ' + name).strip()
    vol = prod_vol(p.get('volume', '') or '', lang)
    img = p.get('img')
    pic = ('<img src="/assets/shop/%s" alt="%s" loading="lazy" width="520" height="390">'
           % (e(img), e(full))) if img else ('<span class="prod-ph">%s</span>' % e(name[:2].upper()))
    desc = (p.get('desc') or {}).get(lang) or (p.get('desc') or {}).get('ru', '')
    ing = (p.get('ing') or {}).get(lang) or (p.get('ing') or {}).get('ru', '')
    ing_html = ('<details class="prod-ing"><summary>%s</summary><p>%s<br><span class="prod-note">%s'
                '</span></p></details>' % (e(u['ing']), e(ing), e(u['full']))) if ing else ''
    label = full + ((', ' + vol) if vol else '')
    su = STOCK_UI[lang]
    stock = p.get('stock')
    pre = stock == 'pre'
    badge = ('<span class="prod-stock is-%s">%s</span>'
             % ('pre' if pre else 'in', e(su['pre'] if pre else su['in']))) if stock else ''
    if p.get('top'):
        badge += '<span class="prod-top">%s</span>' % e(TOP_UI[lang])
    btn = su['btnPre'] if pre else u['btn']
    return tight(f"""
      <article class="prod" data-brand="{e(brand)}" data-cat="{e(p.get('cat',''))}"
               data-stock="{e(stock or '')}" data-top="{'1' if p.get('top') else ''}"
               data-price="{p['price']}" data-ord="{ord_}">
        <figure class="prod-pic" data-q="{e(search_key(brand, name, vol, desc, ing))}">{'<span class="prod-cat">' + e(cat_label) + '</span>' if cat_label else ''}{badge}{pic}</figure>
        {'<div class="brand">' + e(brand) + '</div>' if brand else ''}
        <h3>{e(name)}</h3>
        <p class="prod-for">{e(desc)}</p>
        {ing_html}
        <div class="pm"><span>{e(vol)}</span>{'<b>' + e(p['price']) + ' ' + e(cur) + '</b>' if not p.get('priceHidden') else '<i class="pm-ask">' + e(PRICE_ASK[lang]) + '</i>'}</div>
        <a class="btn btn-sm btn-gold prod-order" href="{wa_base(city)}" data-p="{e(label)}"
           target="_blank" rel="noopener">{e(btn)}</a>
      </article>""")


CUR_CODE = {'prague': 'CZK', 'valencia': 'EUR'}


def shop_schema(lang, city):
    """Разметка товаров: Google показывает цену и наличие прямо в выдаче."""
    items = list(shop_items) if city == 'prague' else \
        [dict(x, cat='body') for x in cosm['body'].get(city, [])]
    if not items:
        return ''
    out = []
    for n, it in enumerate(items, 1):
        brand = it.get('brand', '')
        name = (brand + ' ' + prod_name(it, lang)).strip()
        desc = (it.get('desc') or {}).get(lang) or (it.get('desc') or {}).get('ru', '')
        st = it.get('stock')
        if it.get('priceHidden'):      # цену этого бренда публиковать нельзя
            prod = {'@type': 'Product', 'name': name}
            if brand:
                prod['brand'] = {'@type': 'Brand', 'name': brand}
            out.append({'@type': 'ListItem', 'position': n, 'item': prod})
            continue
        offer = {
            '@type': 'Offer',
            'price': str(it['price']),
            'priceCurrency': CUR_CODE[city],
        }
        if st != 'pre':
            offer['url'] = '%s/%s/%s/%s' % (BASE, lang, city, REL['cosmetics'])
        if st:
            offer['availability'] = ('https://schema.org/InStock' if st == 'in'
                                     else 'https://schema.org/PreOrder')
        prod = {'@type': 'Product', 'name': name, 'offers': offer}
        if brand:
            prod['brand'] = {'@type': 'Brand', 'name': brand}
        # у позиций под заказ оставляем только суть: разметка на 400 товаров
        # иначе весит больше самой страницы
        if st != 'pre':
            if desc:
                prod['description'] = desc
            if it.get('img'):
                prod['image'] = '%s/assets/shop/%s' % (BASE, it['img'])
        out.append({'@type': 'ListItem', 'position': n, 'item': prod})
    return jld({'@context': 'https://schema.org', '@type': 'ItemList',
                'itemListElement': out})


def brand_slug(b):
    return re.sub(r'[^a-z0-9]+', '-', b.lower()).strip('-')


def city_brands(city):
    """Бренды витрины города: у каждого своя страница для поиска по марке."""
    if city != 'prague':
        return []
    out = []
    for it in shop_items:
        b = it.get('brand')
        if b and b not in out:
            out.append(b)
    return sorted(out, key=lambda x: x.lower())


def build_brand(lang, city, brand):
    """Страница одного бренда: по запросам «марка + город» ищут чаще всего."""
    st = studios[city]
    h = HERO[lang]; u = BRAND_UI[lang]; su = SHOP_UI[lang]
    cur = st['currency']
    cityname = st['city'].get(lang, st['city']['en'])
    items = [it for it in shop_items if it.get('brand') == brand]
    order = {c: n for n, c in enumerate(SHOP_CATS)}
    items.sort(key=lambda it: (0 if it.get('top') else 1, order.get(it['cat'], 9), it['price']))
    short = dict(SHOP_CAT_SHORT[lang])
    cards = ''.join(prod_card(it, lang, city, cur, n, short.get(it['cat'], ''))
                    for n, it in enumerate(items))
    lead = u['lead'] % brand
    main = f"""
<section class="hero hero-sm"><div class="wrap">
  <div class="kicker"><a href="/{lang}/{city}/{REL['cosmetics']}">{e(nav_label('cosmetics', lang))}</a> · {e(cityname)}</div>
  <h1>{e(brand)} — {e(u['buy'])}</h1>
  <p class="lead">{e(lead)}</p>
  <div class="cta-row">
    <a class="btn btn-gold" href="{book_href(lang, city)}" data-book>{e(h['cta'])}</a>
    <a class="btn btn-ghost" href="/{lang}/{city}/{REL['cosmetics']}">{e(u['all'])}</a>
  </div>
</div></section>

<section class="rose"><div class="wrap">
  <div class="shop-count">{e(u['items'])}: {len(items)}</div>
  <div class="prods">{cards}</div>
</div></section>"""
    title = '%s — %s' % (brand, u['buy'])
    desc = lead
    return doc(lang, city, REL['cosmetics'] + brand_slug(brand) + '/', 'cosmetics',
               title, desc, main, other_rel=REL['cosmetics'], add_city=False,
               schema=crumbs(lang, city, [(nav_label('cosmetics', lang), REL['cosmetics']),
                                          (brand, REL['cosmetics'] + brand_slug(brand) + '/')]))


def build_cosmetics(lang, city):
    """Каталог домашнего ухода: линейка для тела + косметика для волос."""
    st = studios[city]
    h = HERO[lang]
    cityname = st['city'].get(lang, st['city']['en'])
    hd = cosm['head'][lang]; cu = cosm['ui'][lang]; bt = cosm['bodyText'][lang]
    cur = st['currency']

    shop = shop_block(lang, city, cur)
    intro = f"""
<section class="tint"><div class="wrap">
  <div class="sec-head"><h2>{e(bt['title'])}</h2><p>{e(bt['desc'])}</p></div>
</div></section>""" if cosm['body'].get(city) else ''

    if city == 'prague':
        note = cu.get('note', '')
        cta_link = ('<a class="btn btn-ghost" href="/%s/%s/trichology/">%s</a>'
                    % (lang, city, e(cu.get('cta', ''))) if services['trichology']['page'].get(lang) else '')
    else:
        note = COSM_NOTE_ES[lang]
        cta_link = ''

    main = f"""
<section class="hero hero-sm"><div class="wrap">
  <div class="kicker">{e(nav_label('cosmetics', lang))} · {e(cityname)}</div>
  <h1>{e(hd['h1'])}</h1>
  <p class="lead">{e(hd['lead'])}</p>
  <div class="cta-row">
    <a class="btn btn-gold" href="{book_href(lang, city)}" data-book>{e(h['cta'])}</a>
    {cta_link}
  </div>
</div></section>
{intro}
{shop}
<section class="{'alt' if shop else ''}"><div class="wrap"><p class="note">{e(note)}</p></div></section>
"""
    title = '%s — %s, Hi Sisters Clinic' % (hd['h1'], cityname)
    return doc(lang, city, REL['cosmetics'], 'cosmetics', title, hd['lead'], main,
               schema=crumbs(lang, city, [(hd['h1'], REL['cosmetics'])])
                      + shop_schema(lang, city))


# ───────────────────────────────── о нас ─────────────────────────────────
def build_about(lang, city):
    """Кто мы, принципы, команда и как проходит курс."""
    st = studios[city]
    h = HERO[lang]; sec = SECTIONS[lang]; ab = ABOUT[lang]
    u_ab = pick(ui['about'], lang); u_hiw = pick(ui['howItWorks'], lang)
    cityname = st['city'].get(lang, st['city']['en'])

    # оценки Google идут сразу за первым абзацем и собираются из данных студий
    body = list(ab['paras'])
    body.insert(1, rating_sentence(lang))
    paras = ''.join('<p>%s</p>' % e(x) for x in body)
    stats = ''.join('<div><b>%s</b>%s</div>' % (e(n), e(t)) for n, t in ab['stats'])
    vals = icon_cards([(v['title'], v['desc']) for v in (u_ab.get('values') or [])], ICO_VALUES)
    mates = ''
    for m in city_team(city):
        nm = m['name'].get(lang) or m['name']['ru']
        img = m.get('img')
        ava = ('<img class="ava" src="/assets/team/%s" alt="%s" loading="lazy" width="200" height="200">'
               % (e(img), e(nm))) if img else \
              ('<div class="ava ava-let" aria-hidden="true">%s</div>' % e(nm.strip()[:1]))
        mates += f"""
      <article class="mate">
        {ava}
        <h3>{e(nm)}</h3>
        <div class="role">{e(m['role'].get(lang) or m['role']['ru'])}</div>
        <p>{e(m['desc'].get(lang) or m['desc']['ru'])}</p>
      </article>"""
    steps = ''.join('<div class="step"><div class="step-n">%s</div><h3>%s</h3><p>%s</p></div>'
                    % (e(s['n']), e(s['t']), e(s['d'])) for s in u_hiw.get('steps', []))

    main = f"""
<section class="hero hero-sm"><div class="wrap">
  <div class="kicker">{e(nav_label('about', lang))} · {e(cityname)}</div>
  <h1>{e(ab['h1'])}</h1>
  <p class="lead">{e(ab['lead'])}</p>
</div></section>

<section class="alt"><div class="wrap">
  <div class="prose">{paras}</div>
  <div class="stats">{stats}</div>
</div></section>
{split_block('/assets/photos/glam.jpg', ab['h1'], SPLIT_ABOUT[lang][0], SPLIT_ABOUT[lang][1],
             SPLIT_ABOUT[lang][2], sec_class='tint')}

<section class="rose"><div class="wrap">
  <div class="sec-head"><h2>{e(u_ab.get('valuesTitle', sec['why']))}</h2></div>
  <div class="cards">{vals}</div>
</div></section>

<section class="alt"><div class="wrap">
  <div class="sec-head"><h2>{e(u_ab.get('teamTitle', sec['team']))}</h2></div>
  <div class="team">{mates}</div>
</div></section>

<section class="lilac"><div class="wrap">
  <div class="sec-head"><h2>{e(u_hiw.get('title',''))}</h2></div>
  <div class="steps">{steps}</div>
</div></section>
{article_block('choose', lang, 'tint')}
""" + reviews_block(lang, 3, alt=True, city=city)
    title = '%s — Hi Sisters Clinic' % ab['h1']
    return doc(lang, city, REL['about'], 'about', title, ab['lead'], main,
               schema=crumbs(lang, city, [(ab['h1'], REL['about'])]))


# ──────────────────────────────── контакты ────────────────────────────────
def build_contacts(lang, city):
    """Обе студии на одной странице: адрес, часы, телефон, запись."""
    st = studios[city]
    cp = CONTACTS_PAGE[lang]
    u_ct = pick(ui['contacts'], lang)
    cityname = st['city'].get(lang, st['city']['en'])
    order = [city] + [c for c in CITIES if c != city]

    cards = ''
    for cc in order:
        s = studios[cc]
        nm = s['city'].get(lang, s['city']['en'])
        igs = ''.join('<a href="https://instagram.com/%s" target="_blank" rel="noopener">@%s</a> '
                      % (ig, ig) for ig in s.get('instagram', []))
        cards += f"""
      <div class="studio">
        <h3>{e(nm)}</h3>
        <dl>
          <dt>{e(u_ct.get('addressLabel','Адрес'))}</dt><dd>{e(s['address'])}</dd>
          <dt>{e(cp['hours'])}</dt><dd>{e((s.get('hours') or {}).get(lang,''))}</dd>
          <dt>{e(u_ct.get('phoneLabel','Телефон'))}</dt><dd><a href="tel:{s['phone'].replace(' ','')}">{e(s['phone'])}</a></dd>
          <dt>{e(MAIL_LBL[lang])}</dt><dd><a href="mailto:{s.get('email','')}">{e(s.get('email',''))}</a></dd>
          <dt>Instagram</dt><dd>{igs}</dd>
        </dl>
        <div class="studio-cta">
          <a class="btn btn-gold" href="/{lang}/{cc}/booking/" data-book="{cc}">{e(cp['book'])}</a>
          {'<a class="btn btn-ghost btn-sm" href="' + s['maps'] + '" target="_blank" rel="noopener">' + e(cp['route']) + '</a>' if s.get('maps') else ''}
        </div>
      </div>"""

    main = f"""
<section class="hero hero-sm"><div class="wrap">
  <div class="kicker">{e(nav_label('contacts', lang))} · {e(cityname)}</div>
  <h1>{e(cp['h1'])}</h1>
  <p class="lead">{e(cp['lead'])}</p>
</div></section>

<section class="rose"><div class="wrap">
  <div class="studios">{cards}</div>
</div></section>
"""
    title = '%s — Hi Sisters Clinic %s' % (cp['h1'], cityname)
    sch = jld(biz_schema(lang, city)) + crumbs(lang, city, [(cp['h1'], REL['contacts'])])
    return doc(lang, city, REL['contacts'], 'contacts', title, cp['lead'], main, schema=sch)



def build_booking(lang, city):
    """Форма записи встроена в страницу: клиент не уходит с сайта."""
    st = studios[city]
    bp = BOOKPAGE[lang]
    cityname = st['city'].get(lang, st['city']['en'])
    igs = (st.get('instagram') or [''])[0]
    url = widget_url(city, lang)

    main = f"""
<section class="hero hero-sm"><div class="wrap">
  <div class="kicker">{e(bp['h1'])} · {e(cityname)}</div>
  <h1>{e(bp['h1'])}</h1>
  <p class="lead">{e(bp['lead'])}</p>
</div></section>

<section class="tint"><div class="wrap">
  <div class="bookwrap">
    <iframe class="bookframe" src="{url}" title="{e(bp['frame'])}"
            allow="payment" referrerpolicy="no-referrer-when-downgrade"></iframe>
  </div>
  <p class="note booknote">{e(bp['fallback'])}
    <a href="tel:{st['phone'].replace(' ','')}">{e(st['phone'])}</a>
    {'· <a href="https://instagram.com/' + igs + '" target="_blank" rel="noopener">@' + e(igs) + '</a>' if igs else ''}
    · <a href="{url}" target="_blank" rel="noopener">{e(bp['newtab'])}</a>
  </p>
</div></section>
"""
    title = '%s — %s, Hi Sisters Clinic' % (bp['h1'], cityname)
    return doc(lang, city, REL['booking'], 'booking', title, bp['lead'], main, with_band=False)



def service_reviews(key, city, lang):
    """Отзывы Google именно об этой услуге в этом городе."""
    items = (svc_reviews['items'].get(key) or {}).get(city) or []
    if not items:
        return ''
    cards = ''.join(
        '<figure class="rev"><div class="stars">★★★★★</div><p>%s</p><cite>%s · Google</cite></figure>'
        % (e(r['text'].get(lang) or r['text']['ru']), e(r['name'])) for r in items)
    return ('<section><div class="wrap">'
            '<div class="sec-head"><h2>%s</h2></div><div class="revs">%s</div>'
            '</div></section>' % (e(svc_reviews['sectionTitle'][lang]), cards))


# ─────────────────────── отдельная страница услуги ───────────────────────
def build_service(lang, city, key):
    st = studios[city]; h = HERO[lang]; sec = SECTIONS[lang]
    svc = services[key]
    pg = svc['page'].get(lang) or svc['page'].get('ru')
    card = svc['card'].get(lang) or svc['card'].get('ru')
    cityname = st['city'].get(lang, st['city']['en'])
    other = 'valencia' if city == 'prague' else 'prague'
    price = group_from(SERVICE_GROUP.get(city, {}).get(key, ''), city, lang)
    # в другом городе этой услуги может не быть — тогда ведём на его главную
    other_rel = (key + '/') if (other in svc['cities'] and svc['page'].get(lang)) else ''

    blocks = ''
    for s_ in pg.get('sections', []):
        t_ = s_.get('title') or s_.get('h')
        body = ''
        if s_.get('p'):
            body += '<p>%s</p>' % e(s_['p'])
        for p_ in s_.get('paras', []) or []:
            body += '<p>%s</p>' % e(p_)
        if s_.get('steps'):
            body += '<ol>%s</ol>' % ''.join('<li>%s</li>' % e(x) for x in s_['steps'])
        if s_.get('list'):
            body += '<ul>%s</ul>' % ''.join('<li>%s</li>' % e(x) for x in s_['list'])
        if s_.get('note'):
            body += '<p class="note">%s</p>' % e(s_['note'])
        if t_ or body:
            blocks += '<div class="art"><h2>%s</h2>%s</div>' % (e(t_ or ''), body)

    # аппарат упоминаем фоном, в конце текста услуги, а не отдельным блоком
    for it in equip['items']:
        if it.get('service') == key and city in it['cities']:
            blocks += ('<div class="art"><p class="note"><b>%s.</b> %s</p></div>'
                       % (e(it['title'][lang]), e(it['desc'][lang])))
            break

    faqs = ''.join('<details><summary>%s</summary><div class="ans">%s</div></details>'
                   % (e(f['q']), e(f['a'])) for f in pg.get('faq', []))
    faq_block = ('<section class="lilac"><div class="wrap"><div class="sec-head"><h2>%s</h2></div>'
                 '<div class="faq">%s</div></div></section>' % (e(pg.get('faqTitle', '')), faqs)) if faqs else ''

    ptab, extra = '', ''
    if proc_list(key, city, lang):
        # раздел с описанными процедурами: прайс разложен по подразделам,
        # названия ведут к описанию ниже на странице
        extra = proc_price_tables(key, city, lang)
    else:
        ptab = price_rows(SERVICE_GROUP.get(city, {}).get(key, ''), city, lang,
                          order=False, link='page')
        for xg in (SERVICE_EXTRA.get(key) or []):
            if xg in LANG_SKIP.get(lang, set()):
                continue
            xr = price_rows(xg, city, lang, order=False)
            if xr:
                extra += ('<h3 class="ptab-h">%s</h3><div class="ptable">%s</div>'
                          % (e((PGROUP_TITLE.get(xg) or {}).get(lang, xg)), xr))
    # у страницы может не быть своей группы цен — тогда показываем только дополнительные
    price_block = ('<section class="tint"><div class="wrap"><div class="sec-head"><h2>%s</h2></div>'
                   '%s%s'
                   '<div class="more-list"><a href="/%s/%s/services/#prices">%s</a></div>'
                   '</div></section>'
                   % (e(sec['prices']),
                      ('<div class="ptable">%s</div>' % ptab) if ptab else '',
                      extra, lang, city, e(sec['allPrices']))) if (ptab or extra) else ''

    methods_block = article_block('methods', lang) if key in ('laser', 'electro') else ''

    # другие услуги города — чтобы со страницы было куда идти
    # со страницы лазера ведём на зоны — это основные поисковые запросы
    zone_links = ''
    if key == 'laser':
        zone_links = ''.join('<a href="/%s/%s/laser/%s/">%s</a>'
                             % (lang, city, zk, e((zones[zk].get(lang) or zones[zk]['ru'])['title']))
                             for zk in zones if zones[zk]['rows'].get(city))

    sib = [k for k, v in services.items()
           if k != key and city in v['cities'] and v['page'].get(lang)]
    sib_links = ''.join('<a href="/%s/%s/%s/">%s</a>'
                        % (lang, city, k, e((services[k]['card'].get(lang) or {}).get('title', '')))
                        for k in sib)

    svc_split = ''
    if key == 'cosmetology':
        svc_split = split_block('/assets/photos/exoskin.jpg', card['title'], SPLIT_COSM[lang][0],
                                SPLIT_COSM[lang][1], sec_class='tint', rev=True)

    main = f"""
<section class="hero hero-sm"><div class="wrap">
  <div class="kicker"><a href="/{lang}/{city}/services/">{e(nav_label('services', lang))}</a> · {e(cityname)}</div>
  <h1>{e((pg.get('title') or card['title']) + ' ' + IN_CITY[city][lang])}</h1>
  <p class="lead">{e(pg.get('intro') or card['desc'])}</p>
  <div class="cta-row">
    <a class="btn btn-gold" href="{book_href(lang, city)}" data-book>{e(h['cta'])}</a>
    {wa_btn(lang, city, pg.get('title') or card['title'])}
    {'<span class="fact"><b>' + e(price) + '</b></span>' if price else ''}
    <span class="free">{e(h['free'])}</span>
  </div>
</div></section>

<section><div class="wrap arts">{blocks}</div></section>
{svc_split}
{methods_block}
{price_block}
{proc_blocks(key, city, lang)}
{faq_block}

{service_reviews(key, city, lang)}
<section><div class="wrap">
  <div class="sec-head"><h2>{e(sec['other'])}</h2></div>
  <div class="more-list">{zone_links}{sib_links}</div>
</div></section>
"""
    title = '%s — %s, Hi Sisters Clinic' % (pg.get('title') or card['title'], cityname)
    desc = (pg.get('intro') or card['desc'])[:300]
    nm = pg.get('title') or card['title']
    sch = (service_schema(lang, city, key, price_min(SERVICE_GROUP.get(city, {}).get(key, ''), lang))
           + crumbs(lang, city, [(SERVICES_PAGE[lang]['h1'], REL['services']), (nm, key + '/')])
           + faq_schema(pg.get('faq', [])))
    return doc(lang, city, key + '/', 'services', title, desc, main,
               other_rel=other_rel, schema=sch,
               langs=[l for l in LANGS if svc['page'].get(l)])



# ───────── отдельная страница процедуры: /<язык>/<город>/<услуга>/<процедура>/ ─────────
def build_proc(lang, city, it):
    """Своя страница процедуры — такую ссылку можно отправить клиенту."""
    st = studios[city]; h = HERO[lang]; sec = SECTIONS[lang]; u = PROC_UI[lang]
    key = it['service']
    svc = services[key]
    card = svc['card'].get(lang) or svc['card'].get('ru')
    pg = svc['page'].get(lang) or svc['page'].get('ru')
    cityname = st['city'].get(lang, st['city']['en'])
    title_ = it['title'][lang]
    lead = (it.get('lead') or {}).get(lang, '')
    rows = ''
    g = prices['groups'].get(it['group']) or {}
    rr = g.get(lang) or g.get('ru') or []
    for i in it['rows']:
        if i < len(rr) and _num(rr[i]) is not None:
            rows += ('<div class="prow"><span>%s</span><span>%s</span></div>'
                     % (e(rr[i]['label']), e(row_val(rr[i], city))))
    price_block = ('<section class="tint"><div class="wrap"><div class="sec-head"><h2>%s</h2></div>'
                   '<div class="ptable">%s</div>'
                   '<div class="more-list"><a href="/%s/%s/%s/">%s</a></div>'
                   '</div></section>' % (e(sec['prices']), rows, lang, city, key,
                                         e(u['back']))) if rows else ''
    sib = [x for x in proc_list(key, city, lang) if x['slug'] != it['slug'] and x['sub'] == it['sub']]
    if not sib:
        sib = [x for x in proc_list(key, city, lang) if x['slug'] != it['slug']][:6]
    sib_links = ''.join('<a href="/%s/%s/%s">%s</a>' % (lang, city, proc_rel(x), e(x['title'][lang]))
                        for x in sib)
    faqs = ''.join('<details><summary>%s</summary><div class="ans">%s</div></details>'
                   % (e(f['q']), e(f['a'])) for f in (it.get('faq') or {}).get(lang, []))
    faq_block = ('<section class="lilac"><div class="wrap"><div class="sec-head"><h2>%s</h2></div>'
                 '<div class="faq">%s</div></div></section>'
                 % (e(pg.get('faqTitle', '')), faqs)) if faqs else ''
    main = f"""
<section class="hero hero-sm"><div class="wrap">
  <div class="kicker"><a href="/{lang}/{city}/{key}/">{e(card['title'])}</a> · {e(cityname)}</div>
  <h1>{e(title_)}</h1>
  <p class="lead">{e(lead)}</p>
  <div class="cta-row">
    <a class="btn btn-gold" href="{book_href(lang, city)}" data-book>{e(h['cta'])}</a>
    {wa_btn(lang, city, title_)}
    {'<span class="fact"><b>' + e(proc_meta(it, city, lang)) + '</b></span>' if proc_meta(it, city, lang) else ''}
    <span class="free">{e(h['free'])}</span>
  </div>
</div></section>

<section><div class="wrap arts"><div class="art">{proc_body(it, lang, 'h2')}</div></div></section>
{price_block}
{faq_block}
<section class="alt"><div class="wrap">
  <div class="sec-head"><h2>{e(u['other'])}</h2></div>
  <div class="more-list">{sib_links}<a href="/{lang}/{city}/{key}/">{e(u['back'])}</a></div>
</div></section>
"""
    desc = (lead or '')[:300]
    sch = (crumbs(lang, city, [(SERVICES_PAGE[lang]['h1'], REL['services']),
                               (card['title'], key + '/'), (title_, proc_rel(it))])
           + faq_schema((it.get('faq') or {}).get(lang, [])))
    return doc(lang, city, proc_rel(it), 'services',
               '%s — %s, Hi Sisters Clinic' % (title_, cityname), desc, main,
               other_rel='', schema=sch,
               langs=[l for l in LANGS if (it.get('title') or {}).get(l)])


# ───────────── страницы под запросы по зонам: /<язык>/<город>/laser/<зона>/ ─────────────
ZONE_GROUP = {'prague': 'laserWomen', 'valencia': 'laserWomenEs'}
ZONE_UI = {
 'ru': {'other': 'Другие зоны', 'all': 'Весь прайс на лазер', 'price': 'Цены на эту зону'},
 'uk': {'other': 'Інші зони', 'all': 'Весь прайс на лазер', 'price': 'Ціни на цю зону'},
 'cs': {'other': 'Další zóny', 'all': 'Celý ceník laseru', 'price': 'Ceny za tuto zónu'},
 'en': {'other': 'Other areas', 'all': 'Full laser price list', 'price': 'Prices for this area'},
 'es': {'other': 'Otras zonas', 'all': 'Tarifa completa del láser', 'price': 'Precios de esta zona'},
}


def zone_rows(city, lang, key):
    """Строки прайса именно этой зоны: берём по номеру, порядок во всех языках один."""
    grp = prices['groups'].get(ZONE_GROUP[city]) or {}
    rows = grp.get(lang) or grp.get('ru') or []
    cur = studios[city]['currency']
    out, vals = '', []
    for i in zones[key]['rows'].get(city, []):
        if i >= len(rows):
            continue
        r = rows[i]
        v = r.get('now') or r.get('price')
        n = _num(r)
        if n:
            vals.append(n)
        out += ('<div class="prow"><span>%s</span><span>%s</span></div>'
                % (e(r['label']), e(v if isinstance(v, str) else '%s %s' % (v, cur))))
    return out, (min(vals) if vals else None)


def build_zone(lang, city, key):
    st = studios[city]; h = HERO[lang]; z = zones[key]
    t = z.get(lang) or z['ru']
    ui_z = ZONE_UI[lang]
    cityname = st['city'].get(lang, st['city']['en'])
    title_city = '%s %s' % (t['title'], IN_CITY[city][lang])
    table, pmin = zone_rows(city, lang, key)
    price = ('%s %d %s' % (PRICE_FROM[lang], pmin, st['currency'])) if pmin else None

    arts = ''.join('<div class="art"><h2>%s</h2><p>%s</p></div>' % (e(a), e(b))
                   for a, b in t['sections'])
    faqs = ''.join('<details><summary>%s</summary><div class="ans">%s</div></details>'
                   % (e(q), e(a)) for q, a in t['faq'])
    sibs = ''.join('<a href="/%s/%s/laser/%s/">%s</a>'
                   % (lang, city, k, e((zones[k].get(lang) or zones[k]['ru'])['title']))
                   for k in zones if k != key)

    main = f"""
<section class="hero hero-sm"><div class="wrap">
  <div class="kicker"><a href="/{lang}/{city}/laser/">{e(services['laser']['card'].get(lang, services['laser']['card']['ru'])['title'])}</a> · {e(cityname)}</div>
  <h1>{e(title_city)}</h1>
  <p class="lead">{e(t['intro'])}</p>
  <div class="cta-row">
    <a class="btn btn-gold" href="{book_href(lang, city)}" data-book>{e(h['cta'])}</a>
    {'<span class="fact"><b>' + e(price) + '</b></span>' if price else ''}
    <span class="free">{e(h['free'])}</span>
  </div>
</div></section>

<section><div class="wrap arts">{arts}</div></section>

{'<section class="tint"><div class="wrap"><div class="sec-head"><h2>' + e(ui_z['price']) + '</h2></div><div class="ptable">' + table + '</div><div class="more-list"><a href="/' + lang + '/' + city + '/laser/">' + e(ui_z['all']) + '</a></div></div></section>' if table else ''}

{'<section><div class="wrap"><div class="sec-head"><h2>' + e(pick(ui['faq'], lang).get('title', '')) + '</h2></div><div class="faq">' + faqs + '</div></div></section>' if faqs else ''}

<section class="alt"><div class="wrap">
  <div class="sec-head"><h2>{e(ui_z['other'])}</h2></div>
  <div class="more-list">{sibs}</div>
</div></section>
"""
    sch = (service_schema(lang, city, 'laser', pmin)
           + crumbs(lang, city, [(SERVICES_PAGE[lang]['h1'], REL['services']),
                                 (services['laser']['card'].get(lang, services['laser']['card']['ru'])['title'], 'laser/'),
                                 (t['title'], 'laser/%s/' % key)])
           + faq_schema([{'q': q, 'a': a} for q, a in t['faq']]))
    return doc(lang, city, 'laser/%s/' % key, 'services',
               '%s — Hi Sisters Clinic' % title_city, t['intro'], main, schema=sch)


# ──────────────────────────────── обучение ────────────────────────────────
def build_training(lang, city):
    st = studios[city]; tr = TRAIN[lang]
    cityname = st['city'].get(lang, st['city']['en'])
    ui_prog = (courses['ui'].get(lang) or courses['ui']['ru']).get('prog', '')

    visible = courses.get('visible') or []
    items = {i['id']: i for i in (courses['items'].get(lang) or courses['items']['ru'])}
    cards = ''
    for cid in visible:
        it = items.get(cid)
        if not it:
            continue
        det = (courses['details'].get(cid) or {}).get(lang) or (courses['details'].get(cid) or {}).get('ru') or {}
        prog = ''
        for grp in det.get('groups', []):
            if isinstance(grp, list) and len(grp) == 2:
                prog += '<h4>%s</h4><ul>%s</ul>' % (e(grp[0]), ''.join('<li>%s</li>' % e(x) for x in grp[1]))
        body = (('<p class="c-lead">%s</p>' % e(det['lead'])) if det.get('lead') else '') + prog
        cards += f"""
      <article class="course">
        <h3>{e(it.get('title',''))}</h3>
        <div class="c-meta"><span>{e(it.get('format',''))}</span><b>{e(it.get('price',''))}</b></div>
        {'<p class="c-desc">' + e(it.get('desc','')) + '</p>' if it.get('desc') else ''}
        {'<details><summary>' + e(ui_prog) + '</summary><div class="c-prog">' + body + '</div></details>' if body else ''}
        <a class="btn btn-sm" href="{book_href(lang, city)}" data-book>{e(tr['cta'])}</a>
      </article>"""

    main = f"""
<section class="hero hero-sm"><div class="wrap">
  <div class="kicker">{e(tr['kicker'])} · {e(cityname)}</div>
  <h1>{e(tr['h1'])}</h1>
  <p class="lead">{e(tr['lead'])}</p>
</div></section>

{split_block('/assets/photos/portrait.jpg', tr['h1'], SPLIT_TRAIN[lang][0],
             SPLIT_TRAIN[lang][1], sec_class='tint', rev=True)}

<section class="lilac"><div class="wrap">
  <div class="courses">{cards}</div>
</div></section>
"""
    title = '%s — %s, Hi Sisters Clinic' % (tr['h1'], cityname)
    return doc(lang, city, REL['training'], 'training', title, tr['lead'], main, cta=tr['cta'],
               schema=crumbs(lang, city, [(tr['kicker'], REL['training'])]))



def sitemap(pages):
    """Карта сайта: каждая страница один раз, со ссылками на свои языки.
    Так Google понимает, что это переводы, а не копии."""
    groups = {}
    for lang, city, rel in pages:
        groups.setdefault((city, rel), []).append(lang)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for (city, rel), langs in sorted(groups.items()):
        alts = ''.join('<xhtml:link rel="alternate" hreflang="%s" href="%s/%s/%s/%s"/>'
                       % (l, BASE, l, city, rel) for l in LANGS if l in langs)
        alts += ('<xhtml:link rel="alternate" hreflang="x-default" href="%s/cs/%s/%s"/>'
                 % (BASE, city, rel)) if 'cs' in langs else ''
        prio = '1.0' if rel == '' else ('0.9' if rel in (REL['services'],) else '0.7')
        for l in LANGS:
            if l not in langs:
                continue
            out.append('<url><loc>%s/%s/%s/%s</loc><priority>%s</priority>%s</url>'
                       % (BASE, l, city, rel, prio, alts))
    out.append('</urlset>')
    return '\n'.join(out)



# ─────────────── корень сайта: мгновенный переход на язык посетителя ───────────────
ROOT_LINKS = {'ru': 'Русский', 'uk': 'Українська', 'cs': 'Čeština',
              'en': 'English', 'es': 'Español'}


GTAG = ('<script async src="https://www.googletagmanager.com/gtag/js?id=G-K921K357QH">'
        '</script><script>'
        'window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}'
        "gtag('js',new Date());gtag('config','AW-18276095826');"
        "gtag('config','G-K921K357QH');"
        '</script>')


def page_redirect(target, title, lang='cs'):
    """Страница-перенаправление: услуга переехала, адрес остаётся живым."""
    return ('<!doctype html><html lang="%s"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><meta name="robots" content="noindex,follow">'
            '<link rel="canonical" href="%s%s">'
            '<meta http-equiv="refresh" content="0;url=%s">'
            '<link rel="icon" href="/favicon.svg">'
            '</head><body><p><a href="%s">%s</a></p>'
            '<script>location.replace(%r);</script></body></html>'
            % (lang, html.escape(title), BASE, target, target, target,
               html.escape(title), target))


# старые адреса рекламы остаются живыми и уводят на новые разделы
LEGACY_MAP = {'services.html': REL['services'],
              'training.html': REL['training'],
              'contacts.html': REL['contacts'],
              'collaboration.html': REL['contacts']}


def legacy_redirect(rel):
    """Старый адрес остаётся живым, но сразу ведёт на новый раздел."""
    js = ("(function(){var m={ru:'ru',uk:'uk',cs:'cs',sk:'cs',en:'en',es:'es',be:'ru',kk:'ru'},"
          "L=navigator.languages||[navigator.language||'cs'],p='cs',i,c;"
          "for(i=0;i<L.length;i++){c=String(L[i]).slice(0,2).toLowerCase();"
          "if(m[c]){p=m[c];break;}}"
          "setTimeout(function(){location.replace('/'+p+'/prague/%s'"
          "+location.search+location.hash);},350);})();" % rel)
    tgt = '/cs/prague/' + rel
    return ('<!doctype html><html lang="cs"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Hi Sisters Clinic</title><meta name="robots" content="noindex,follow">'
            '<link rel="canonical" href="%s%s">'
            '<meta http-equiv="refresh" content="0;url=%s">'
            '<link rel="icon" href="/favicon.svg">%s'
            '<style>body{font-family:system-ui,sans-serif;background:#130B56;color:#fff;margin:0;'
            'min-height:100vh;display:flex;align-items:center;justify-content:center}'
            'a{color:#E8C6B0}</style></head><body>'
            '<p><a href="%s">Hi Sisters Clinic</a></p>'
            '<script>%s</script></body></html>'
            % (BASE, tgt, tgt, GTAG, tgt, js))


def root_redirect():
    """index.html в корне: сразу уводит на нужный язык, сохраняя utm-метки."""
    alts = ''.join('<link rel="alternate" hreflang="%s" href="%s/%s/prague/">' % (l, BASE, l)
                   for l in LANGS)
    alts += '<link rel="alternate" hreflang="x-default" href="%s/cs/prague/">' % BASE
    links = ''.join('<li><a href="/%s/prague/">%s</a></li>' % (l, html.escape(ROOT_LINKS[l]))
                    for l in LANGS)
    js = ("(function(){var m={ru:'ru',uk:'uk',cs:'cs',sk:'cs',en:'en',es:'es',be:'ru',kk:'ru'},"
          "L=navigator.languages||[navigator.language||'cs'],p='cs',i,c;"
          "for(i=0;i<L.length;i++){c=String(L[i]).slice(0,2).toLowerCase();"
          "if(m[c]){p=m[c];break;}}"
          "setTimeout(function(){location.replace('/'+p+'/prague/'"
          "+location.search+location.hash);},350);})();")
    return ('<!doctype html><html lang="cs"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Hi Sisters Clinic — Praha a Valencia</title>'
            '<meta name="robots" content="noindex,follow">'
            '<link rel="canonical" href="%s/cs/prague/">%s'
            '<meta http-equiv="refresh" content="0;url=/cs/prague/">'
            '<link rel="icon" href="/favicon.svg">%s'
            '<style>body{font-family:system-ui,sans-serif;background:#130B56;color:#fff;'
            'margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;'
            'text-align:center}a{color:#EFD9B4}ul{list-style:none;padding:0;line-height:2.2}'
            '</style></head><body><div><p>Hi Sisters Clinic</p><ul>%s</ul></div>'
            '<script>%s</script></body></html>' % (BASE, alts, GTAG, links, js))


ROBOTS = """User-agent: *
Allow: /
Disallow: /admin/
Disallow: /src/
Disallow: /new/

Sitemap: %s/sitemap.xml
""" % BASE


# ───────────────────────────────── сборка ─────────────────────────────────
def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, 'w', encoding='utf-8').write(text)


if __name__ == '__main__':
    os.makedirs(os.path.join(OUT, 'assets'), exist_ok=True)
    io.open(os.path.join(OUT, 'assets', 'app.css'), 'w', encoding='utf-8').write(css())
    # картинки живут в assets/ рядом с контентом: site/ можно пересобрать с нуля.
    # В сборке на сервере картинки уже лежат в репозитории — их не копируем.
    src = os.path.join(ROOT, 'assets')
    skip_assets = os.environ.get('HS_SKIP_ASSETS') == '1'
    for dp, _, fs in (os.walk(src) if os.path.isdir(src) and not skip_assets else []):
        rel = os.path.relpath(dp, src)
        dst = os.path.join(OUT, 'assets') if rel == '.' else os.path.join(OUT, 'assets', rel)
        os.makedirs(dst, exist_ok=True)
        for f in sorted(fs):
            if not f.startswith('.'):
                shutil.copy2(os.path.join(dp, f), os.path.join(dst, f))
    for f in ('favicon.svg', 'CNAME'):
        if os.path.isfile(os.path.join(ROOT, f)):
            shutil.copy2(os.path.join(ROOT, f), os.path.join(OUT, f))
    # панель управления: отдельная страница, в поиск не идёт
    adm = os.path.join(ROOT, 'admin', 'index.html')
    if os.path.isfile(adm):
        os.makedirs(os.path.join(OUT, 'admin'), exist_ok=True)
        shutil.copy2(adm, os.path.join(OUT, 'admin', 'index.html'))
        # понятные названия прайсов для панели
        names = {k: (v.get('ru') or k) for k, v in PGROUP_TITLE.items()}
        io.open(os.path.join(OUT, 'admin', 'groups.json'), 'w', encoding='utf-8').write(
            json.dumps(names, ensure_ascii=False, indent=1))
    pages = []
    seo_pages = []
    for lang in LANGS:
        for city in CITIES:
            d = os.path.join(OUT, lang, city)
            for rel, text in (
                ('', build_home(lang, city)),
                (REL['services'], build_services(lang, city)),
                (REL['training'], build_training(lang, city)),
                (REL['cosmetics'], build_cosmetics(lang, city)),
                (REL['about'], build_about(lang, city)),
                (REL['contacts'], build_contacts(lang, city)),
                (REL['booking'], build_booking(lang, city)),
            ):
                write(os.path.join(d, rel, 'index.html'), text)
                pages.append('/%s/%s/%s' % (lang, city, rel))
                if rel != REL['booking']:     # форму записи индексировать незачем
                    seo_pages.append((lang, city, rel))
            for key, svc in services.items():
                # /cosmetics/ — отдельная страница каталога, общая услуга её не перекрывает
                if key == 'cosmetics' or city not in svc['cities'] or not svc['page'].get(lang):
                    continue
                write(os.path.join(d, key, 'index.html'), build_service(lang, city, key))
                pages.append('/%s/%s/%s/' % (lang, city, key))
                seo_pages.append((lang, city, key + '/'))
            for it_ in PROC_ITEMS:
                k_ = it_['service']
                svc_ = services.get(k_) or {}
                if (city not in svc_.get('cities', []) or not svc_.get('page', {}).get(lang)
                        or not (it_.get('title') or {}).get(lang)
                        or it_ not in proc_list(k_, city, lang)):
                    continue
                write(os.path.join(d, k_, it_['slug'], 'index.html'), build_proc(lang, city, it_))
                pages.append('/%s/%s/%s' % (lang, city, proc_rel(it_)))
                seo_pages.append((lang, city, proc_rel(it_)))
            for b in city_brands(city):
                rel_b = REL['cosmetics'] + brand_slug(b) + '/'
                write(os.path.join(d, REL['cosmetics'], brand_slug(b), 'index.html'),
                      build_brand(lang, city, b))
                pages.append('/%s/%s/%s' % (lang, city, rel_b))
                seo_pages.append((lang, city, rel_b))
            for zkey in zones:
                if not zones[zkey]['rows'].get(city):
                    continue
                write(os.path.join(d, 'laser', zkey, 'index.html'), build_zone(lang, city, zkey))
                pages.append('/%s/%s/laser/%s/' % (lang, city, zkey))
                seo_pages.append((lang, city, 'laser/%s/' % zkey))

    io.open(os.path.join(OUT, 'sitemap.xml'), 'w', encoding='utf-8').write(sitemap(seo_pages))
    io.open(os.path.join(OUT, 'robots.txt'), 'w', encoding='utf-8').write(ROBOTS)
    io.open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(root_redirect())
    # массажа тела больше нет: старый адрес уводит на косметологию, а не висит пустым
    for l in LANGS:
        tgt = '/%s/prague/cosmetology/' % l
        d_ = os.path.join(OUT, l, 'prague', 'massage')
        os.makedirs(d_, exist_ok=True)
        io.open(os.path.join(d_, 'index.html'), 'w', encoding='utf-8').write(
            page_redirect(tgt, 'Hi Sisters Clinic', l))
    # старые .html с рекламы и из выдачи уводим на соответствующие разделы
    for fname, rel_ in LEGACY_MAP.items():
        io.open(os.path.join(OUT, fname), 'w', encoding='utf-8').write(legacy_redirect(rel_))

    print('страниц собрано: %d' % len(pages))
    print('карта сайта: %d адресов' % seo_pages.__len__())
    print('css: %.1f КБ' % (os.path.getsize(os.path.join(OUT, 'assets', 'app.css')) / 1024))
    sizes = [os.path.getsize(os.path.join(dp, f))
             for dp, _, fs in os.walk(OUT) for f in fs if f == 'index.html']
    print('страница: в среднем %.1f КБ, самая большая %.1f КБ'
          % (sum(sizes) / len(sizes) / 1024, max(sizes) / 1024))
