"""Extract structured fields from freight chat messages."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

_WS = re.compile(r"\s+")
_ARROW_RE = re.compile(r"(?:➡️|⬅️|➡|⬅|→|←|⇒|⇔|➔|⟶|⟷)")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "]+",
    flags=re.UNICODE,
)

SHIPPER_STRONG = [
    r"ищу\s+машин",
    r"нужн[аоы]\s+машин",
    r"нужен\s+транспорт",
    r"ищу\s+транспорт",
    r"ищу\s+фур",
    r"нужн[аоы]\s+фур",
    r"ищу\s+тс\b",
    r"нужен\s+тс\b",
    r"ищу\s+перевозчик",
    r"нужен\s+перевозчик",
    r"требуется\s+(машин|транспорт|фур)",
    r"заявк[аи]\s+на\s+перевоз",
    r"есть\s+груз",
    r"груз\s+есть",
    r"отда(ю|ем)\s+груз",
    r"срочн(ый|о)\s+груз",
    r"нужен\s+реф",
    r"ищу\s+реф",
    r"#ищумашин",
    r"кто\s+вез[её]т",
    r"кто\s+возьм[её]т",
]

SHIPPER_WEAK = [
    r"груз\s+\d",
    r"погрузк",
    r"разгрузк",
]

# backward-compatible alias
SHIPPER_PATTERNS = SHIPPER_STRONG + SHIPPER_WEAK

DRIVER_PATTERNS = [
    r"ищу\s+груз",
    r"свобод(ен|на|ны|но)",
    r"машин[аы]\s+свобод",
    r"тс\s+свобод",
    r"готов\s+взять",
    r"возьму\s+груз",
    r"возьму\s+попутн",
    r"пустой\s+(на|в|из)",
    r"выезжаю\s+порожн",
]

EXCLUDE_PATTERNS = [
    r"вакансия",
    r"требуется\s+водител",
    r"ищу\s+водител",
    r"работа\s+водител",
    r"крипт",
    r"казино",
    r"букмекер",
    r"ставки\s+на\s+",
    r"18\+",
    r"интим",
]

BODY_MAP = {
    "реф": "reefer",
    "рефрижератор": "reefer",
    "холодильник": "reefer",
    "изотерм": "isotherm",
    "тент": "tent",
    "еврофура": "tent",
    "штора": "tent",
    "борт": "board",
    "бортов": "board",
    "закрытый": "box",
    "фургон": "box",
    "цельнометалл": "box",
}

CITY_ALIASES: dict[str, str] = {
    # --- Москва и Московская область (ЦФО) ---
    "москва": "москва",
    "мск": "москва",
    "м.о": "москва",
    "мо ": "москва",
    "мо.": "москва",
    "мо,": "москва",
    "г москва": "москва",
    "г. москва": "москва",
    "город москва": "москва",
    "московская": "москва",
    "московская область": "москва",
    "московской": "москва",
    "подмосковье": "москва",
    "moscow": "москва",
    "msk": "москва",
    "спб": "санкт-петербург",
    "питер": "санкт-петербург",
    "петербург": "санкт-петербург",
    "санкт петербург": "санкт-петербург",
    "г санкт-петербург": "санкт-петербург",
    "ленинградская": "санкт-петербург",
    "ло ": "санкт-петербург",
    "spb": "санкт-петербург",
    "saint petersburg": "санкт-петербург",
    "ст-петербург": "санкт-петербург",
    "нн": "нижний новгород",
    "н.новгород": "нижний новгород",
    "нижний": "нижний новгород",
    "н новгород": "нижний новгород",
    "ростов": "ростов-на-дону",
    "ростов на дону": "ростов-на-дону",
    "рнд": "ростов-на-дону",
    "ебург": "екатеринбург",
    "екб": "екатеринбург",
    "екат": "екатеринбург",
    "нвкз": "новороссийск",
    "нврск": "новороссийск",
    "крд": "краснодар",
    "крдар": "краснодар",
    "тверь": "тверь",
    "твр": "тверь",
    "рязань": "рязань",
    "рзн": "рязань",
    "тула": "тула",
    "калуга": "калуга",
    "владимир": "владимир",
    "ярославль": "ярославль",
    "ярославл": "ярославль",
    "смоленск": "смоленск",
    "воронеж": "воронеж",
    "врж": "воронеж",
    "липецк": "липецк",
    "тамбов": "тамбов",
    "пенза": "пенза",
    "самара": "самара",
    "тольятти": "тольятти",
    "казань": "казань",
    "кзн": "казань",
    "уфа": "уфа",
    "пермь": "пермь",
    "челябинск": "челябинск",
    "челны": "набережные челны",
    "наб челны": "набережные челны",
    "набережные": "набережные челны",
    "радумля": "радумля",
    "петро-славянка": "петро-славянка",
    "петро славянка": "петро-славянка",
    "славянка": "петро-славянка",
    "химки": "химки",
    "мытищи": "мытищи",
    "балашиха": "балашиха",
    "подольск": "подольск",
    "одинцово": "одинцово",
    "королёв": "королёв",
    "королев": "королёв",
    "люберцы": "люберцы",
    "красногорск": "красногорск",
    "серпухов": "серпухов",
    "коломна": "коломна",
    "домодедово": "домодедово",
    "видное": "видное",
    "видное мо": "видное",
    "видное московская": "видное",
    "видное московской": "видное",
    "зеленоград": "зеленоград",
    "дмитров": "дмитров",
    "клин": "клин",
    "чехов": "чехов",
    "раменское": "раменское",
    "жуковский": "жуковский",
    "реутов": "реутов",
    "долгопрудный": "долгопрудный",
    "лобня": "лобня",
    "щелково": "щелково",
    "пушкино": "пушкино",
    "ногинск": "ногинск",
    "солнечногорск": "солнечногорск",
    "электросталь": "электросталь",
    "железнодорожный": "железнодорожный",
    "наро-фоминск": "наро-фоминск",
    "нарофоминск": "наро-фоминск",
    "ступино": "ступино",
    "волоколамск": "волоколамск",
    "можайск": "можайск",
    "истра": "истра",
    "сергиев посад": "сергиев посад",
    "сергиев-посад": "сергиев посад",
    "загорск": "сергиев посад",
    "орехово-зуево": "орехово-зуево",
    "орехово зуево": "орехово-зуево",
    "воскресенск": "воскресенск",
    "егорьевск": "егорьевск",
    "кашира": "кашира",
    "озёры": "озёры",
    "озеры": "озёры",
    "луховицы": "луховицы",
    "шатура": "шатура",
    "павловский посад": "павловский посад",
    "павловский-посад": "павловский посад",
    "фрязино": "фрязино",
    "ивантеевка": "ивантеевка",
    "дубна": "дубна",
    "дзержинский": "дзержинский",
    "протвино": "протвино",
    "пущино": "пущино",
    "черноголовка": "черноголовка",
    "краснознаменск": "краснознаменск",
    "кубинка": "кубинка",
    "звенигород": "звенигород",
    "апрелевка": "апрелевка",
    "голицыно": "голицыно",
    "руза": "руза",
    "талдом": "талдом",
    "красноармейск": "красноармейск",
    "лотошино": "лотошино",
    "шаховская": "шаховская",
    "серебряные пруды": "серебряные пруды",
    "зарайск": "зарайск",
    "бронницы": "бронницы",
    "котельники": "котельники",
    "лыткарино": "лыткарино",
    "томилино": "томилино",
    "лесной городок": "лесной городок",
    "нахабино": "нахабино",
    "дедовск": "дедовск",
    "краснозаводск": "краснозаводск",
    "пересвет": "пересвет",
    "хотьково": "хотьково",
    "яхрома": "яхрома",
    "высоковск": "высоковск",
    # --- ЦФО: области (центры и крупные города) ---
    "белгород": "белгород",
    "старый оскол": "старый оскол",
    "старооскол": "старый оскол",
    "губкин": "губкин",
    "валуйки": "валуйки",
    "алексеевка": "алексеевка",
    "шебекино": "шебекино",
    "строитель": "строитель",
    "брянск": "брянск",
    "клинцы": "клинцы",
    "новозыбков": "новозыбков",
    "дятьково": "дятьково",
    "унеча": "унеча",
    "владимир": "владимир",
    "ковров": "ковров",
    "муром": "муром",
    "александров": "александров",
    "гусь-хрустальный": "гусь-хрустальный",
    "гусь хрустальный": "гусь-хрустальный",
    "киржач": "киржач",
    "вязники": "вязники",
    "колочугино": "колочугино",
    "петушки": "петушки",
    "суздаль": "суздаль",
    "собинка": "собинка",
    "радужный": "радужный",
    "воронеж": "воронеж",
    "борисоглебск": "борисоглебск",
    "россошь": "россошь",
    "лиски": "лиски",
    "острогожск": "острогожск",
    "нововоронеж": "нововоронеж",
    "павловск": "павловск",
    "семилуки": "семилуки",
    "иваново": "иваново",
    "кинешма": "кинешма",
    "шуя": "шуя",
    "вичуга": "вичуга",
    "фурманов": "фурманов",
    "тейково": "тейково",
    "кохма": "кохма",
    "калуга": "калуга",
    "обнинск": "обнинск",
    "людиново": "людиново",
    "малоярославец": "малоярославец",
    "боровск": "боровск",
    "кондрово": "кондрово",
    "сухиничи": "сухиничи",
    "козельск": "козельск",
    "таруса": "таруса",
    "кострома": "кострома",
    "буй": "буй",
    "шарья": "шарья",
    "нерехта": "нерехта",
    "галич": "галич",
    "мантурово": "мантурово",
    "волгореченск": "волгореченск",
    "курск": "курск",
    "железногорск": "железногорск",
    "курчатов": "курчатов",
    "льгов": "льгов",
    "рыльск": "рыльск",
    "щигры": "щигры",
    "липецк": "липецк",
    "елец": "елец",
    "грязи": "грязи",
    "данков": "данков",
    "лебедянь": "лебедянь",
    "усмань": "усмань",
    "задонск": "задонск",
    "орёл": "орёл",
    "орел": "орёл",
    "ливны": "ливны",
    "мценск": "мценск",
    "болхов": "болхов",
    "рязань": "рязань",
    "касимов": "касимов",
    "скопин": "скопин",
    "сасово": "сасово",
    "ряжск": "ряжск",
    "рыбное": "рыбное",
    "михайлов": "михайлов",
    "новомичуринск": "новомичуринск",
    "смоленск": "смоленск",
    "вязьма": "вязьма",
    "рославль": "рославль",
    "ярцево": "ярцево",
    "сафоново": "сафоново",
    "гагарин": "гагарин",
    "десногорск": "десногорск",
    "тамбов": "тамбов",
    "мичуринск": "мичуринск",
    "рассказово": "рассказово",
    "моршанск": "моршанск",
    "котовск": "котовск",
    "кирсанов": "кирсанов",
    "уварово": "уварово",
    "тверь": "тверь",
    "ржев": "ржев",
    "вышний волочёк": "вышний волочёк",
    "вышний волочек": "вышний волочёк",
    "кимры": "кимры",
    "торжок": "торжок",
    "конаково": "конаково",
    "осташков": "осташков",
    "бежецк": "бежецк",
    "кашин": "кашин",
    "калязин": "калязин",
    "удомля": "удомля",
    "бологое": "бологое",
    "нелидово": "нелидово",
    "тула": "тула",
    "новомосковск": "новомосковск",
    "донской": "донской",
    "алексин": "алексин",
    "щёкино": "щёкино",
    "щекино": "щёкино",
    "узловая": "узловая",
    "богородицк": "богородицк",
    "киреевск": "киреевск",
    "суворов": "суворов",
    "ефремов": "ефремов",
    "венёв": "венёв",
    "венев": "венёв",
    "ярославль": "ярославль",
    "рыбинск": "рыбинск",
    "переславль": "переславль-залесский",
    "переславль-залесский": "переславль-залесский",
    "тутаев": "тутаев",
    "углич": "углич",
    "ростов великий": "ростов великий",
    "ростов-великий": "ростов великий",
    "ростов ярославский": "ростов великий",
    "гаврилов-ям": "гаврилов-ям",
    "данилов": "данилов",
    "любим": "любим",
    "белёв": "белёв",
    "белев": "белёв",
    "плавск": "плавск",
    "ясногорск": "ясногорск",
    "кимовск": "кимовск",
    "заокский": "заокский",
    "юрьев-польский": "юрьев-польский",
    "юрьев польский": "юрьев-польский",
    "карабаново": "карабаново",
    "лакинск": "лакинск",
    "покров": "покров",
    "струнино": "струнино",
    "костерево": "костерево",
    "меленки": "меленки",
    "гороховец": "гороховец",
    "почеп": "почеп",
    "трубчевск": "трубчевск",
    "стародуб": "стародуб",
    "жуковка": "жуковка",
    "севск": "севск",
    "фатеж": "фатеж",
    "обоянь": "обоянь",
    "суджа": "суджа",
    "дмитриев": "дмитриев",
    "старица": "старица",
    "торопец": "торопец",
    "западная двина": "западная двина",
    "лихославль": "лихославль",
    "красный холм": "красный холм",
    "весиегонск": "весиегонск",
    "зубцов": "зубцов",
    # --- прочие крупные (не ЦФО, оставляем) ---
    "спб": "санкт-петербург",
    "питер": "санкт-петербург",
    "с-петербург": "санкт-петербург",
    "санкт-петербург": "санкт-петербург",
    "петербург": "санкт-петербург",
    "ленинградская": "санкт-петербург",
    "петро-славянка": "петро-славянка",
    "петрославянка": "петро-славянка",
    "петро славянка": "петро-славянка",
    "шушары": "шушары",
    "колпино": "колпино",
    "радумля": "радумля",
    "радумли": "радумля",
    "радужный": "радумля",
    "лобня": "лобня",
    "казань": "казань",    "екатеринбург": "екатеринбург",
    "екб": "екатеринбург",
    "свердловск": "екатеринбург",
    "новосибирск": "новосибирск",
    "нск": "новосибирск",
    "краснодар": "краснодар",
    "крд": "краснодар",
    "ростов": "ростов-на-дону",
    "ростов-на-дону": "ростов-на-дону",
    "самара": "самара",
    "уфа": "уфа",
    "челябинск": "челябинск",
    "омск": "омск",
    "пермь": "пермь",
    "тюмень": "тюмень",
    "волгоград": "волгоград",
    "красноярск": "красноярск",
    "иркутск": "иркутск",
    "хабаровск": "хабаровск",
    "владивосток": "владивосток",
    "нижний": "нижний новгород",
    "н.новгород": "нижний новгород",
    "нн": "нижний новгород",
    "сочи": "сочи",
    "ставрополь": "ставрополь",
    "саратов": "саратов",
    "тольятти": "тольятти",
    "барнаул": "барнаул",
    "томск": "томск",
    "кемерово": "кемерово",
    "оренбург": "оренбург",
    "пенза": "пенза",
    "мурманск": "мурманск",
    "архангельск": "архангельск",
    "калининград": "калининград",
    "симферополь": "симферополь",
    "севастополь": "севастополь",
    "крым": "крым",
    "нальчик": "нальчик",
    "махачкала": "махачкала",
    "грозный": "грозный",
    "владикавказ": "владикавказ",
    "астрахань": "астрахань",
    "новороссийск": "новороссийск",
    "анапа": "анапа",
    "туапсе": "туапсе",
    "псков": "псков",
    "великий новгород": "великий новгород",
    "новгород": "великий новгород",
    "череповец": "череповец",
    "вологда": "вологда",
    "сыктывкар": "сыктывкар",
    "киров": "киров",
    "ижевск": "ижевск",
    "йошкар-ола": "йошкар-ола",
    "чебоксары": "чебоксары",
    "саранск": "саранск",
    "ульяновск": "ульяновск",
    "магнитогорск": "магнитогорск",
    "нижневартовск": "нижневартовск",
    "сургут": "сургут",
    "ноябрьск": "ноябрьск",
    "якутск": "якутск",
    "благовещенск": "благовещенск",
    "чита": "чита",
    "улан-удэ": "улан-удэ",
    "ташкент": "ташкент",
    "тошкент": "ташкент",
    "джизак": "джизак",
    "джиззак": "джизак",
    "урганч": "ургенч",
    "ургенч": "ургенч",
    "хорезм": "ургенч",
    "хоразм": "ургенч",
    "навои": "навои",
    "навоий": "навои",
    "нукус": "нукус",
    "чирчик": "чирчик",
    "ангрен": "ангрен",
    "мерсин": "мерсин",
    "худжанд": "худжанд",
    "поти": "поти",
    "караганда": "караганда",
    "алматы": "алматы",
    "алма-ата": "алматы",
    "бишкек": "бишкек",
    "самарканд": "самарканд",
    "бухара": "бухара",
    "астана": "астана",
    "нур-султан": "астана",
    "шымкент": "шымкент",
}


def normalize(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    t = _ARROW_RE.sub("-", t)
    t = t.replace("—", "-").replace("–", "-").replace("﹣", "-").replace("−", "-")
    t = _EMOJI_RE.sub(" ", t)
    return _WS.sub(" ", t).strip()


def fingerprint(text: str) -> str:
    n = normalize(text)
    n = re.sub(r"https?://\S+", "", n)
    n = re.sub(r"@\w+", "", n)
    n = re.sub(r"[^\w\sа-яa-z0-9+\-]+", " ", n, flags=re.I)
    n = _WS.sub(" ", n).strip()
    return hashlib.sha1(n.encode("utf-8")).hexdigest()


@dataclass
class ParsedLoad:
    text: str
    norm: str
    kind: str  # shipper | driver | mixed | noise | other
    from_city: str | None = None
    to_city: str | None = None
    tonnage: float | None = None
    volume_m3: float | None = None
    body: str | None = None  # reefer|tent|isotherm|board|box
    temps: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    contacts: list[str] = field(default_factory=list)
    price: str | None = None
    load_date: str | None = None
    shipper_hits: list[str] = field(default_factory=list)
    driver_hits: list[str] = field(default_factory=list)
    fp: str = ""


def _first_match(patterns: list[str], text: str) -> list[str]:
    hits = []
    for p in patterns:
        if re.search(p, text, re.I):
            hits.append(p)
    return hits


def _canon_city(token: str) -> str | None:
    t = token.strip(" .,;:()[]").lower().replace("ё", "е")
    if not t:
        return None
    # Exact match on ё-normalized aliases
    for alias, canon in CITY_ALIASES.items():
        if alias.replace("ё", "е") == t:
            return canon
    for alias, canon in CITY_ALIASES.items():
        a = alias.replace("ё", "е")
        if a in t or t in a:
            if len(t) >= 3:
                return canon
    return None


def city_search_terms(query: str) -> list[str]:
    """Expand city aliases so 'Питер' also matches 'санкт-петербург' / 'спб'."""
    raw = (query or "").strip().lower().replace("ё", "е")
    if not raw:
        return []
    canon = _canon_city(raw) or raw
    terms = {raw, canon}
    for alias, c in CITY_ALIASES.items():
        if c == canon and len(alias) >= 3:
            terms.add(alias)
    # Prefer longer terms first for LIKE matching quality (order irrelevant for OR)
    return sorted(terms, key=len, reverse=True)


_CITY_STOP = {
    "груз",
    "догруз",
    "нужен",
    "нужна",
    "нужно",
    "ищу",
    "тонн",
    "тонны",
    "тент",
    "реф",
    "машина",
    "мошина",
    "ставки",
    "ставка",
    "сегодня",
    "завтра",
    "срочно",
    "есть",
    "фура",
    "погрузка",
    "погрузки",
    "разгрузка",
    "разгрузки",
    "выгрузка",
    "выгрузки",
    "загрузка",
    "загрузки",
    "откуда",
    "куда",
    "дата",
    "оплата",
    "контакт",
    "телефон",
    "адрес",
    "готов",
    "готова",
    "готово",
    "готовы",
    "задняя",
    "задней",
    "боковая",
    "боковой",
    "верхняя",
    "верхней",
    "нижняя",
    "нижней",
    "реально",
    "налом",
    "нал",
    "безнал",
    "аванс",
    "вес",
    "объем",
    "объём",
    "нужны",
    "коллеги",
    "привет",
    "вопрос",
    "рынок",
    "склад",
    "палет",
    "палеты",
}


def _looks_like_city(token: str) -> bool:
    t = token.strip().lower().replace("ё", "е")
    if len(t) < 3 or len(t) > 28:
        return False
    if not re.fullmatch(r"[а-яa-z][а-яa-z.\-]*", t):
        return False
    return t not in _CITY_STOP


def _canon_city_flex(token: str) -> str | None:
    """Canonize city including simple Russian case endings (москвы→москва)."""
    t = token.strip(" .,;:()[]").lower().replace("ё", "е")
    if not t:
        return None
    hit = _canon_city(t)
    if hit:
        return hit
    # Drop common case endings and retry
    for suf in ("ого", "ему", "ой", "ей", "ую", "ая", "ые", "ии", "ию", "ия", "ы", "и", "е", "у", "а"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            hit = _canon_city(t[: -len(suf)])
            if hit:
                return hit
            stem = t[: -len(suf)]
            for ending in ("а", "ь", "й", "ы", ""):
                hit = _canon_city(stem + ending)
                if hit:
                    return hit
    # Accusative -у: уфу→уфа, пензу→пенза
    if len(t) >= 3 and t.endswith("у"):
        for ending in ("а", "ь", ""):
            hit = _canon_city(t[:-1] + ending)
            if hit:
                return hit
    return None


def _city_token(token: str) -> str | None:
    """Canonize known city or keep plausible unknown place name."""
    t = (token or "").strip().lower().replace("ё", "е")
    t = _EMOJI_RE.sub(" ", t)
    t = re.sub(r"^[^а-яa-z0-9]+|[^а-яa-z0-9.\-]+$", "", t)
    t = _WS.sub(" ", t).strip(" .,;:()[]")
    if not t:
        return None
    c = _canon_city_flex(t)
    if c:
        return c
    if t in _CITY_STOP:
        return None
    # multi-word: try first 1–2 tokens
    words = t.split()
    if len(words) >= 2:
        c2 = _canon_city_flex(" ".join(words[:2]))
        if c2:
            return c2
        c1 = _canon_city_flex(words[0])
        if c1:
            return c1
    if _looks_like_city(t):
        return t
    if words and _looks_like_city(words[0]):
        return words[0]
    return None


_ROUTE_PAIR_RE = re.compile(
    r"([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-]{2,28})"
    r"(?:\s*[-–—/→]+\s*|\s+-\s+)"
    r"([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-]{2,28})"
)

_FROM_TO_RE = re.compile(
    r"(?:из|от)\s+([а-яёa-z.\- ]{2,40}?)\s+(?:в|до|на)\s+([а-яёa-z.\- ]{2,40}?)(?=\s|$|[,.!;\n]|\d)",
    re.I,
)

_LOAD_CITY_RE = re.compile(
    r"(?:погрузк[ауиеойя]*|загрузк[ауиеойя]*|откуда|пункт\s+погрузки)"
    r"\s*[:=/\-]?\s*"
    r"(?!готов|готова|готово|готовы|задн|боков|верхн|нижн|налом|безнал)"
    r"([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-\s]{1,40}?)"
    r"(?=\s*(?:разгруз|выгруз|куда|пункт\s+разгруз|,|;|\n|$|\d+\s*т))",
    re.I,
)

_UNLOAD_CITY_RE = re.compile(
    r"(?:разгрузк[ауиеойя]*|выгрузк[ауиеойя]*|куда|пункт\s+разгрузки)"
    r"\s*[:=/\-]?\s*"
    r"(?!готов|готова|готово|готовы|задн|боков|верхн|нижн|налом|безнал)"
    r"([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-\s]{1,40}?)"
    r"(?=\s*(?:погруз|загруз|откуда|,|;|\n|$|\d+\s*т|тент|реф|ставк))",
    re.I,
)

_LOAD_UNLOAD_INLINE_RE = re.compile(
    r"(?:погрузк[ауиеойя]*|загрузк[ауиеойя]*)\s*[:=/\-]?\s*"
    r"([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-]{2,28})"
    r"\s*(?:/|,|\||\s+)?\s*"
    r"(?:разгрузк[ауиеойя]*|выгрузк[ауиеойя]*)\s*[:=/\-]?\s*"
    r"([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-]{2,28})",
    re.I,
)


def _clean_place(raw: str) -> str | None:
    t = (raw or "").strip(" .,;:()[]")
    t = re.split(r"\s+(?:груз|догруз|нужн|ищу|тент|реф|тонн|ставк|оплат)", t, maxsplit=1, flags=re.I)[
        0
    ].strip()
    # keep first 1–3 words of place name
    words = t.split()
    if len(words) > 3:
        t = " ".join(words[:3])
    return _city_token(t)


def _extract_labeled_route(norm: str) -> tuple[str | None, str | None]:
    m = _LOAD_UNLOAD_INLINE_RE.search(norm)
    if m:
        a, b = _clean_place(m.group(1)), _clean_place(m.group(2))
        if a or b:
            return a, b
    frm = None
    to = None
    m1 = _LOAD_CITY_RE.search(norm)
    if m1:
        frm = _clean_place(m1.group(1))
    m2 = _UNLOAD_CITY_RE.search(norm)
    if m2:
        to = _clean_place(m2.group(1))
    if frm or to:
        return frm, to
    return None, None


def _extract_route(norm: str) -> tuple[str | None, str | None]:
    # Prefer explicit A-B routes first. Labeled "погрузка: готов" must not win.
    # Multi-hop on one line: A - B - C → A to C (not A to B)
    for line in re.split(r"[\n|;]+", norm):
        parts = [p.strip() for p in re.split(r"\s*[-–—/→]\s*", line) if p.strip()]
        city_parts = []
        for p in parts:
            p0 = re.split(
                r"\s+(?:груз|догруз|нужн|ищу|тент|реф|тонн)", p, maxsplit=1, flags=re.I
            )[0].strip()
            # skip "1. Москва" numbering prefix
            p0 = re.sub(r"^\d+[.)]\s*", "", p0)
            c = _city_token(p0)
            if c:
                city_parts.append(c)
        if len(city_parts) >= 3 and city_parts[0] != city_parts[-1]:
            return city_parts[0], city_parts[-1]
        if len(city_parts) == 2 and city_parts[0] != city_parts[1]:
            return city_parts[0], city_parts[1]

    for m in _ROUTE_PAIR_RE.finditer(norm):
        a, b = _city_token(m.group(1)), _city_token(m.group(2))
        if a and b and a != b and a not in _CITY_STOP and b not in _CITY_STOP:
            return a, b

    m = _FROM_TO_RE.search(norm)
    if m:
        a, b = _clean_place(m.group(1)), _clean_place(m.group(2))
        if a or b:
            return a, b

    labeled = _extract_labeled_route(norm)
    if labeled[0] or labeled[1]:
        return labeled

    # Do NOT grab arbitrary first two known cities across a multi-load post.
    return None, None

_ROUTE_START_RE = re.compile(
    r"^\s*(?:"
    r"\d+[.)]\s*"  # 1. / 2)
    r"|[-–—*•]\s*"
    r")?"
    r"(?:"
    r"[А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-\s]{1,40}\s*[-–—/→]\s*[А-ЯЁа-яёA-Za-z]"
    r"|(?:из|от)\s+[А-ЯЁа-яёA-Za-z]"
    r"|(?:погрузк|загрузк|разгрузк|выгрузк)[а-я]*\s*[:=]"
    r"|(?:погрузк|загрузк)[а-я]*\s+[А-ЯЁа-яёA-Za-z]"
    r")",
    re.I,
)


def split_load_blocks(text: str) -> list[str]:
    """Split a multi-offer post into separate load blocks."""
    raw = (text or "").replace("\r\n", "\n").strip()
    if not raw:
        return []

    # Explicit separators
    parts = re.split(r"\n\s*(?:[-—–=]{3,}|_{3,}|\*{3,})\s*\n", raw)
    if len(parts) >= 2:
        out = [p.strip() for p in parts if p.strip()]
        if len(out) >= 2:
            return out

    lines = raw.split("\n")
    blocks: list[list[str]] = []
    cur: list[str] = []

    def _cur_has_route() -> bool:
        blob = "\n".join(cur)
        return bool(
            _ROUTE_PAIR_RE.search(blob)
            or _FROM_TO_RE.search(blob)
            or _LOAD_UNLOAD_INLINE_RE.search(blob)
            or (_LOAD_CITY_RE.search(blob) and _UNLOAD_CITY_RE.search(blob))
        )

    for i, line in enumerate(lines):
        stripped = line.strip()
        is_blank = not stripped
        starts_route = bool(_ROUTE_START_RE.match(line)) if stripped else False
        # New block when a route-looking line starts and current already has a route
        if starts_route and cur and _cur_has_route():
            blocks.append(cur)
            cur = [line]
            continue
        # Blank line between two route chunks
        if is_blank and cur and _cur_has_route():
            # peek ahead for another route start
            nxt = next((ln for ln in lines[i + 1 :] if ln.strip()), "")
            if nxt and _ROUTE_START_RE.match(nxt):
                blocks.append(cur)
                cur = []
                continue
        cur.append(line)
    if cur:
        blocks.append(cur)

    out = ["\n".join(b).strip() for b in blocks if "\n".join(b).strip()]
    if len(out) >= 2:
        return out
    return [raw]


def _extract_tonnage(norm: str) -> float | None:
    m = re.search(r"(\d+[.,]?\d*)\s*(?:т(?:онн(?:ы|а)?)?|t)\b", norm)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})\s*тн\b", norm)
    if m:
        return float(m.group(1))
    return None


def _extract_volume(norm: str) -> float | None:
    m = re.search(r"(\d+[.,]?\d*)\s*(?:м3|м³|куб)", norm)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return None
    return None


def _extract_body(norm: str) -> str | None:
    for key, body in BODY_MAP.items():
        if key in norm:
            return body
    return None


def _extract_temps(norm: str) -> list[str]:
    found = re.findall(r"[+\-]?\d{1,2}\s*°?\s*[cс]?", norm)
    # Also patterns like +2+4, -18
    more = re.findall(r"[+\-]\d{1,2}", norm)
    out = []
    for x in found + more:
        x = x.replace(" ", "")
        if x and x not in out and re.search(r"\d", x):
            out.append(x)
    # keywords
    for kw in ("замороз", "охлажд", "температур"):
        if kw in norm and kw not in out:
            out.append(kw)
    return out[:6]


_PHONE_RE = re.compile(
    r"(?:\+?7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
)
_AT_RE = re.compile(r"(?<![а-яa-z0-9_])@([A-Za-z][A-Za-z0-9_]{3,31})")
_PRICE_RE = re.compile(
    r"(?:ставка|цена|оплата|фрахт)?\s*[:=]?\s*(\d[\d\s]{2,7})\s*(?:₽|руб|т\.?р\.?|тыс)?",
    re.I,
)
_DATE_RE = re.compile(
    r"(?:погрузк[аи]|выгрузк[аи]|дата|на)\s*[:=]?\s*"
    r"(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|\d{1,2}\s+(?:янв|фев|мар|апр|мая|май|июн|июл|авг|сен|окт|ноя|дек)[а-я]*)",
    re.I,
)


def _extract_phones(text: str) -> list[str]:
    out: list[str] = []
    for m in _PHONE_RE.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) == 11 and digits[0] in "78":
            nice = "+7" + digits[1:]
            if nice not in out:
                out.append(nice)
    return out[:4]


def _extract_contacts(text: str) -> list[str]:
    return list(dict.fromkeys(_AT_RE.findall(text or "")))[:4]


def _extract_price(norm: str, text: str) -> str | None:
    for src in (text, norm):
        m = re.search(
            r"(?:ставка|цена|оплата|фрахт)\s*[:=]?\s*(\d[\d\s]{2,8})\s*(₽|руб\.?|т\.?р\.?|тыс\.?)?",
            src,
            re.I,
        )
        if m:
            num = re.sub(r"\s+", "", m.group(1))
            unit = (m.group(2) or "₽").strip()
            return f"{num} {unit}"
    m = re.search(r"\b(\d{4,7})\s*(₽|руб)\b", text or "", re.I)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    # Common messenger style: "62000 нал" / "85000 безнал"
    m = re.search(r"\b(\d{4,7})\s*(?:нал|безнал|на карту|наличными)\b", text or "", re.I)
    if m:
        return f"{m.group(1)} ₽"
    return None


def _extract_load_date(text: str) -> str | None:
    m = _DATE_RE.search(text or "")
    if m:
        return m.group(1).strip()
    m = re.search(r"\b(сегодня|завтра|послезавтра)\b", text or "", re.I)
    if m:
        return m.group(1).lower()
    return None


def parse_load(text: str) -> ParsedLoad:
    norm = normalize(text)
    if any(re.search(p, norm) for p in EXCLUDE_PATTERNS):
        return ParsedLoad(text=text, norm=norm, kind="noise", fp=fingerprint(text))

    shipper_strong = _first_match(SHIPPER_STRONG, norm)
    shipper_weak = _first_match(SHIPPER_WEAK, norm)
    shipper = shipper_strong + shipper_weak
    driver = _first_match(DRIVER_PATTERNS, norm)
    frm, to = _extract_route(norm)
    tonnage = _extract_tonnage(norm)
    price = _extract_price(norm, text)
    if shipper_strong and driver:
        kind = "mixed"
    elif shipper_strong:
        kind = "shipper"
    elif driver and not shipper_strong:
        kind = "driver"
    elif shipper_weak and not driver:
        kind = "other"
    else:
        kind = "other"
    # Cargo ads often omit keywords: route + tonnage/price ⇒ treat as shipper
    if kind == "other" and not driver and frm and to and (price or tonnage is not None):
        kind = "shipper"
    if kind == "other" and not driver and frm and to and len(norm) >= 40:
        kind = "shipper"

    return ParsedLoad(
        text=text,
        norm=norm,
        kind=kind,
        from_city=frm,
        to_city=to,
        tonnage=tonnage,
        volume_m3=_extract_volume(norm),
        body=_extract_body(norm),
        temps=_extract_temps(norm),
        phones=_extract_phones(text),
        contacts=_extract_contacts(text),
        price=price,
        load_date=_extract_load_date(text),
        shipper_hits=shipper,
        driver_hits=driver,
        fp=fingerprint(text),
    )


def parse_load_blocks(text: str) -> list[ParsedLoad]:
    blocks = split_load_blocks(text)
    parsed = [parse_load(b) for b in blocks]
    useful = [
        p
        for p in parsed
        if p.kind != "noise"
        and (p.from_city or p.to_city or p.kind in {"shipper", "mixed"} or p.tonnage)
    ]
    return useful or parsed[:1] or [parse_load(text)]
