"""Shared helpers: dates, text cleaning, classification, filters, scoring, dedupe keys."""
import hashlib
import html
import math
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

DUBAI = timezone(timedelta(hours=4))


def today_dubai():
    return datetime.now(DUBAI).date()


def clean(value):
    """Return a plain string for anything, treating None/NaN as empty."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def strip_html(text):
    text = html.unescape(clean(text))
    text = html.unescape(text)  # Greenhouse double-escapes its HTML
    text = TAG_RE.sub(" ", text)
    return WS_RE.sub(" ", text).strip()


# ---------------------------------------------------------------- dates

MONTH_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%d-%b-%Y")


def parse_date(value):
    """Best-effort parse of the many date shapes job systems return."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        stamp = value / 1000 if value > 1e11 else value  # Lever uses milliseconds
        return datetime.fromtimestamp(stamp, tz=timezone.utc).date()
    s = clean(value)
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    for fmt in MONTH_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(s).date()  # RSS: "Mon, 02 Nov 2026 12:05:49 +0400"
    except (TypeError, ValueError, IndexError):
        pass
    return relative_posted(s)


def relative_posted(text):
    """Workday style 'Posted Today', 'Posted 3 Days Ago', 'Posted 30+ Days Ago'."""
    t = clean(text).lower()
    if not t:
        return None
    today = today_dubai()
    if "today" in t or "just posted" in t:
        return today
    if "yesterday" in t:
        return today - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*(day|week|month|hour)", t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if unit == "hour":
        return today
    days = n * {"day": 1, "week": 7, "month": 30}[unit]
    return today - timedelta(days=days)


# ---------------------------------------------------------------- location

UAE_RE = re.compile(
    r"united arab emirates|\bu\.?a\.?e\b|\bae-[a-z]|dubai|abu ?dhabi|sharjah|\bajman\b|ras al[ -]?khaimah|"
    r"fujairah|umm al[ -]?quwain|\bal ain\b|jebel ali|musaffah|mussafah|ruwais|\bdifc\b|\badgm\b|"
    r"دبي|أبوظبي|ابوظبي|الإمارات|الامارات|الشارقة",
    re.I,
)
CITY_RE = re.compile(
    r"dubai|abu ?dhabi|sharjah|\bajman\b|ras al[ -]?khaimah|fujairah|umm al[ -]?quwain|\bal ain\b",
    re.I,
)


def is_uae(location):
    return bool(UAE_RE.search(clean(location)))


def city_of(location):
    m = CITY_RE.search(clean(location))
    if not m:
        return "UAE"
    c = m.group(0).lower().replace(" ", "")
    return {"abudhabi": "Abu Dhabi", "dubai": "Dubai", "sharjah": "Sharjah", "ajman": "Ajman",
            "alain": "Al Ain", "fujairah": "Fujairah"}.get(c, m.group(0).title())


# ---------------------------------------------------------------- classification

# Entry-level HR and recruitment administration (a wider-net lane). Its titles pass EXCLUDE_RE, which
# keeps recruitment, talent acquisition and people operations out of every other lane; an agency's
# "Recruitment Consultant" is a sales job and stays out.
HR_ROLE = (
    r"\b(hr|human resources?|people) (assistant|coordinator|administrator|executive|officer|associate|generalist|"
    r"admin|clerk|specialist|support|operations (assistant|coordinator|associate))\b|"
    r"recruitment (coordinator|assistant|administrator|officer|associate|specialist)|"
    r"talent acquisition (coordinator|assistant|administrator|associate|specialist)|"
    r"onboarding (coordinator|administrator)|personnel (assistant|officer|clerk)|"
    r"learning (and|&) development (coordinator|assistant|administrator)|training coordinator"
)

# Order matters: the first family whose pattern matches the title wins.
FAMILIES = [
    ("data_science", "Data_Scientist",
     r"data scien|applied scien|research scien|decision scien|quantitative analy|statistic|predictive model"),
    ("ai_ml", "AI_Engineer",
     r"machine learning|\bml\b|mlops|\bai\b|a\.i\.|artificial intelligence|gen ?ai|generative|\bllms?\b|"
     r"\bnlp\b|natural language|computer vision|deep learning|prompt engineer|agentic|conversational|chatbot"),
    ("data_eng", "Data_Engineer",
     r"data engineer|analytics engineer|\betl\b|big data|data platform|data pipeline|data warehouse|"
     r"databricks|\bspark\b|data integration|dataops|data ops"),
    ("bi", "Data_Analyst",
     r"business intelligence|\bbi\b|\bbie\b|power ?bi|tableau|qlik|reporting|\bmis\b|dashboard|insights?\b|"
     r"visuali[sz]ation"),
    ("data_analyst", "Data_Analyst",
     r"data analy|analytics|data quality|data governance|data management|data specialist|data officer|"
     r"data steward|data associate|data operations|data coordinator|crm analy|marketing analy|"
     r"pricing analy|revenue analy|risk analy|fraud analy|performance analy|people analy|hr data|"
     r"workforce analy|supply chain analy|demand plan|planning analy|research analy|market research|"
     r"\bdata\b(?!\s*(cent(er|re)|entry))"),
    ("product", "Data_Analyst",
     r"product analy|product owner|associate product manager|\bapm\b|product associate|product specialist|"
     r"junior product manager|product management (intern|trainee|graduate)"),
    ("business", "Data_Analyst",
     r"business analy|operations analy|process analy|commercial analy|strategy analy|strategy associate|"
     r"transformation analy|business systems analy|functional analy|business operations|"
     r"operations associate|pmo analy|project coordinator|management associate|consulting analy"),
    ("software", "Backend_Engineer",
     r"software (engineer|developer|development)|backend|back[- ]end|python|django|fastapi|flask|"
     r"node\.?js|java developer|\.net developer|golang|api (developer|engineer)|integration (engineer|developer)|"
     r"platform engineer|cloud engineer|devops|site reliability|\bsre\b|full[- ]?stack|\bsde\b|programmer|"
     r"application developer|automation engineer|\brpa\b|solutions? engineer|"
     r"implementation (engineer|consultant|specialist)|technical consultant|erp (developer|consultant)|"
     r"odoo (developer|consultant|engineer|programmer|technical|functional)|"
     r"salesforce (developer|admin)|crm (developer|consultant)|systems? engineer|database (developer|admin)|"
     r"\bdba\b|sql developer|developer advocate|forward[- ]deployed|\bqa (engineer|analyst|automation)|"
     r"test (engineer|automation)|software tester|quality assurance (engineer|analyst)"),
    ("it", "IT",
     r"\bit (support|analyst|specialist|engineer|officer|technician|administrator|coordinator|executive|"
     r"associate|trainee|intern|operations|customer support|user support)|information technology|service desk|"
     r"help ?desk|desktop support|"
     r"support engineer|"
     r"technical support|application support|systems? analyst|systems? administrator|"
     r"network (engineer|administrator|support)|\bnoc\b|data cent(er|re)|infrastructure (engineer|analyst|support)|"
     r"end user (support|computing)"),
    # The wider net: office and phone roles outside data and tech that take newcomers. No selling roles
    # (SALES_RE). No CV variant is written for them yet, hence "General".
    ("collections", "General",
     r"collections? (officer|agent|executive|specialist|associate|analyst|representative|coordinator|advisor|"
     r"caller|controller|assistant|clerk|staff)|(debt|tele|phone|loan|card)[- ]?collect|"
     r"(?<!content )(?<!data )\bcollectors?\b|"
     r"recover(y|ies) (officer|agent|executive|specialist|associate)|"
     r"(officer|agent|executive|specialist|associate)[\s,.–-]+(collections?|recover(y|ies))\b|"
     r"credit control(ler)?|skip trac|"
     # accounts receivable and payable, billing: the back office of the same money
     r"accounts? (receivable|payable) (clerk|assistant|administrator|executive|officer|specialist|associate|"
     r"coordinator)|\b(ar|ap) (clerk|assistant|executive|officer|specialist)\b|"
     r"billing (executive|officer|assistant|coordinator|specialist|clerk|associate|administrator)|"
     r"accounts (assistant|clerk)|reconciliation (officer|executive|assistant|specialist)"),
    ("customer", "General",
     r"(customer|client|guest|patient|member|vip) (services?|support|care|relations?|success|servicing|happiness|"
     r"engagement|onboarding|access|retention|advisor|adviser|representative|agent|associate|officer|executive|"
     r"operations|coordinator)|"
     # "Customer Experience Officer" answers customers; "Specialist, Customer Experience (Design)" designs
     r"(customer|client|guest|patient) experience (agent|officer|executive|associate|representative|advisor|"
     r"adviser|coordinator|assistant|ambassador)|"
     r"(officer|executive|agent|associate|representative)[\s,.–-]+(customer|client|guest|patient) experience|"
     r"contact cent(er|re)|call cent(er|re)|\bcsr\b|"
     r"(service|support|chat|call|voice|phone|telephone|reservations?|booking|ticketing) "
     r"(agent|advisor|adviser|representative|operator|officer|executive)|"
     r"tele ?(banking|operator)|live chat|\bteller\b|service (officer|associate|executive|ambassador)|"
     r"passenger (service|services) (agent|officer|assistant)|check[- ]?in (agent|officer)|"
     r"airport services? (agent|officer)"),
    ("hr", "General", HR_ROLE),
    ("operations", "General",
     r"operations? (executive|officer|assistant|coordinator|support|specialist|associate|administrator|clerk)|"
     r"\b(officer|executive|associate|assistant|specialist)[\s,.–-]+(\w+ )?operations\b|"
     r"account opening|settlement (services )?(specialist|officer|executive)|"
     r"logistics (coordinator|executive|officer|assistant|associate|specialist|administrator|clerk)|"
     r"supply chain (coordinator|executive|officer|assistant|associate|specialist|administrator)|"
     r"(shipping|import|export|freight|customs|clearance|documentation) "
     r"(coordinator|executive|officer|assistant|clerk|associate)|"
     r"(procurement|purchasing|purchase) (assistant|executive|officer|coordinator|associate|specialist|"
     r"administrator|clerk)|"
     r"(inventory|stock) (controller|coordinator|executive|officer|assistant|associate|specialist|clerk|"
     r"administrator)|warehouse (coordinator|administrator|clerk|executive|officer)|"
     r"(demand|supply|production|inventory|logistics|transport|material|resource) "
     r"plann(er|ing (specialist|executive|coordinator|officer|assistant))|"
     r"fleet (coordinator|executive|officer|administrator)|dispatch (coordinator|executive|officer)|"
     r"order (management|processing|fulfil+ment) (agent|executive|officer|coordinator|specialist|associate)|"
     r"fulfil+ment (officer|coordinator|executive|associate|specialist)|"
     r"vendor (registration|management|onboarding) (specialist|officer|executive|coordinator|associate)|"
     r"onboarding (specialist|associate|executive|officer)|"
     r"e-?commerce (executive|coordinator|specialist|assistant|associate|officer|administrator|operations)|"
     r"marketplace (executive|coordinator|specialist|associate|operations)|"
     r"catalog(ue)? (executive|coordinator|specialist|associate|assistant|officer)|"
     r"listing (executive|specialist|associate|coordinator)|content moderat|trust (and|&) safety|content review"),
    ("admin", "General",
     r"admin(istrative|istration)?[ -]+(assistant|officer|executive|coordinator|associate|support|specialist|clerk)|"
     r"(?<!front )office (assistant|administrator|coordinator|executive|admin)|administrative|"
     r"(project|contracts?|business) administrator|general administration|"
     r"data entry|back[- ]?office|document control(ler)?|\bcoordinator\b|\bsecretary\b|"
     r"(personal|executive|team|documentation|travel) (assistant|clerk)|business support|"
     r"medical records (assistant|clerk|officer)|patient registration"),
    ("analyst", "Data_Analyst", r"\banalyst\b"),
    ("graduate", "Data_Analyst",
     r"graduate|trainee|fresh(er)? grad|entry[- ]level|early (careers?|talent)|rotational|campus|apprentice"),
]
FAMILIES = [(f, cv, re.compile(rx, re.I)) for f, cv, rx in FAMILIES]
WIDE_FAMILIES = {"collections", "customer", "hr", "operations", "admin"}
HR_ROLE_RE = re.compile(HR_ROLE, re.I)


def track_of(family):
    """'core' for the data and tech lanes and graduate programmes, 'wide' for the wider net."""
    return "wide" if family in WIDE_FAMILIES else "core"


# Titles never relevant, whatever family they would otherwise match.
EXCLUDE_RE = re.compile(
    r"front[- ]?end|\bui\b|\bux\b|ui/ux|\bios\b|android|flutter|react native|mobile (app|developer|engineer)|"
    r"graphic|designer|animat|illustrat|video (editor|maker|producer)|videograph|photograph|copywrit|"
    r"content (writer|creator)|teacher|lecturer|professor|faculty|tutor|\btrainers?\b|instructor|"
    r"\bnurse|physician|doctor|surgeon|pharmacist|therapist|psycholog|behaviou?ral analyst|dietitian|dentist|"
    r"oncology|immunology|cardiology|vaccine|respiratory|ophthalm|optometr|optician|dermatolog|neuroscience|"
    r"rare disease|laborator|\blab (technical|support|technician|assistant)|"
    r"driver|cashier|security guard|cyber|soc analyst|security analyst|threat|"
    r"penetration|information security|infosec|\bgrc\b|\biam\b|identity (and|&) access|legal|paralegal|"
    r"people operations|talent acquisition|recruit(er|ment|ing)|payroll|workplace (operations|experience)|"
    r"facilit(y|ies)|\bpermits?\b|embedded|firmware|fpga|"
    r"surveyor|inspector|\bhse\b|(?<!trust and )(?<!trust & )safety|mechanical|maintenance|civil engineer|electrical engineer|chemical engineer|"
    r"petroleum|drilling|reservoir|geolog|quantity|estimator|merchandis|buyer\b|store manager|"
    r"cabin crew|pilot\b|aircraft|chef|culinary|housekeep|waiter|barista|"
    r"data recovery|quality control|distillates|gasoil|"
    # talent pools, career fairs and open applications are not vacancies
    r"talent pool|talent community|career fair|open day|open application|hiring event|"
    r"future (openings?|opportunit|vacanc)",
    re.I,
)
# A walk-in day is how call centres hire, so the wider net keeps one; for a data or tech role it is a
# general hiring event, not a vacancy.
WALK_IN_RE = re.compile(r"walk[- ]?in", re.I)

# A job whose own name is a wider-net role. It goes to that lane even when the title also names a
# data or tech word ("Customer Service Agent - IT Products", "Contact Centre Agent - Digital Banking").
STRONG_WIDE_RE = re.compile(
    r"customer (service|support|care|success) (representative|agent|officer|executive|advisor|adviser|associate|"
    r"specialist|manager|consultant)|(call|contact) cent(er|re)|"
    r"collections? (officer|agent|executive|specialist)|debt collect|\bteller\b",
    re.I,
)

# Selling roles, as the data and tech lanes have always dropped them ("AI Sales Executive", "Tableau
# Account Executive"). A data role about sales stays ("Sales Analyst", "Sales Operations Analyst").
CORE_SALES_RE = re.compile(
    r"\bsales\b(?!.*\b(analy|operations|ops|insights?|data|intelligence|reporting|planning))|inside sales|"
    r"telesales|account (executive|manager|director|representative)|key account|business development|"
    r"\b[bs]dr\b|(customer|merchant|client) acquisition",
    re.I,
)
# No selling roles in the wider net either (decided 18 November 2026): any title that says sales, and
# the jobs that sell under other names: account management, business development, telesales and lead
# generation, a bank's relationship and finance-product roles, property, insurance, financial and
# travel advice, retention desks.
SALES_RE = re.compile(
    r"\bsales(man|men|woman|women|person|people)?\b|\bselling\b|tele ?(sales|marketing|caller)|telemarket|"
    r"account (manager|executive|representative|director|specialist|associate|officer|coordinator)s?\b|"
    r"account management|key accounts?\b|business development|\b[bs]dr\b|lead (generation|gen|qualification)|"
    r"(customer|merchant|client|partner|dealer|seller) acquisition|"
    r"(?<!patient )(?<!guest )relationship (manager|officer|banker|executive|associate)|"
    r"partnerships? (executive|associate|coordinator|specialist|manager|officer)|"
    r"commercial (executive|officer|coordinator|associate)|pre[- ]?sales|personal bank(ing|er)\b|"
    r"(retail|personal|business|priority) banking (executive|officer|advisor|adviser|associate|representative)|"
    r"(islamic|personal|home|auto|car|consumer) finance (executive|advisor|adviser|officer|consultant)|"
    r"(mortgage|financial|investment|wealth) (advisor|adviser|consultant|planner)|bancassurance|bancatakaful|"
    r"insurance (agent|advisor|adviser|consultant)|(real estate|property) (agent|consultant|broker|advisor|"
    r"adviser|specialist|executive)|off[- ]plan|(?<!customs )\bbrokers?\b|leasing (consultant|executive|agent)|"
    r"medical (rep|representative)\b|pharma\w* (rep|representative)\b|travel (consultant|agent)|"
    r"retention (agent|officer|executive|specialist)|cold call",
    re.I,
)

# Wider net only. Out: the shop floor, field and commission-only work, short contracts and remote
# roles (no work visa comes with those), errand jobs, and roles that need training in their field.
WIDE_EXCLUDE_RE = re.compile(
    r"boutique|showroom|\bstore\b|\bmall\b|\bshop\b|fashion|beauty|fragrance|perfume|cosmetic|make ?up|jewel|"
    r"watch(es)?\b|luxury|retail (associate|assistant)|"
    r"\bfield\b|outdoor|door[- ]to[- ]door|commission|freelanc|part[- ]?time|temporary|\btemp\b|"
    r"maternity cover|\bremote\b|work from home|\bwfh\b|"
    r"promoter|hostess|\bspa\b|salon|\bgym\b|fitness|office boy|tea boy|\bhelper\b|cleaner|messenger|"
    r"care assistant|caregiver|site coordinator|construction|clinical|nursing|academic|school|admissions?|"
    r"(?<!customer )service advis[eo]r|\bdesign\b|project specialist|company secretary|corporate secretary",
    re.I,
)
# A coordinator of a specialist field has that field's training ("Radiology Coordinator", "BIM
# Coordinator"); an office, logistics or operations coordinator is the wider net's.
FIELD_COORDINATOR_RE = re.compile(
    r"radiolog|trauma|medical|matern|childcare|clinic|nurs|surg|transplant|oncolog|therap|"
    r"engineering|\bbim\b|building information|security|technical|education|outreach|research|quality|"
    r"\bsite\b|\bmep\b|events?\b|wedding|social media|marketing|content|public relations|\bpr\b",
    re.I,
)
# Wider net only: a role sold to large clients, or a title that itself asks for experience
# ("Enterprise Account Executive", "Collection Officer - Bank Experience Must"), is not a newcomer's.
WIDE_EXPERIENCED_RE = re.compile(
    r"enterprise|strategic|key account|mid[- ]?market|institutional|"
    r"(corporate|major|global|named|national) accounts?\b",
    re.I,
)
EXPERIENCE_ASKED_RE = re.compile(
    r"\bexperienced\b|\bexp\b|(?<!customer )(?<!client )(?<!guest )(?<!patient )(?<!member )(?<!user )"
    r"(?<!employee )\bexperience\b",
    re.I,
)
NO_EXPERIENCE_RE = re.compile(r"\b(no|without|zero)\b[^|()]{0,25}\bexperience|\bfresh", re.I)

# A title that asks for a language other than English or Arabic ("Customer Service Agent - Russian
# Speaker"). "Russian or Arabic Speaker" stays, "Russian and Arabic" does not. Edit the list for the
# languages you speak.
OTHER_LANGUAGE_RE = re.compile(
    r"\b(russian|french|german|chinese|mandarin|cantonese|hindi|urdu|tagalog|spanish|italian|turkish|persian|"
    r"farsi|malayalam|tamil|korean|japanese|portuguese|ukrainian|kazakh|uzbek|romanian|polish|hebrew|greek|"
    r"dutch|swedish|bengali|sinhala|nepali|vietnamese|thai|indonesian|pashto|kurdish|armenian|serbian|czech)"
    r"\b(\s*(and|or|&|/|,|\+)\s*\w+){0,3}[ -]*(speak|language|native|fluent)|"
    r"\b(speak\w*|fluent in|native) (russian|french|german|chinese|mandarin|"
    r"hindi|urdu|tagalog|spanish|italian|turkish|persian|farsi|korean|japanese|portuguese|ukrainian)\b",
    re.I,
)
ARABIC_RE = re.compile(r"\barabic\b", re.I)
ARABIC_AS_WELL_RE = re.compile(r"(\band\b|&|\+)\s*arabic\b|\barabic( speak\w*| language)?\s*(\band\b|&|\+)", re.I)


def other_language(title):
    """True when a title asks for a language the search does not cover. Arabic as the alternative
    ("Arabic Speaker / Malayalam Speaker") is enough; Arabic on top of another language is not."""
    return bool(OTHER_LANGUAGE_RE.search(title)) and (
        not ARABIC_RE.search(title) or bool(ARABIC_AS_WELL_RE.search(title)))


# Not employers: sites that repost other companies' vacancies under their own name, most of them
# remote roles nobody in the UAE stands behind, and a poster whose generic ads (five in one sample
# of 181 Indeed results) lead to a third-party site instead of an employer's.
REPOSTER_RE = re.compile(r"\bjoblet\b|\bjobgether\b|^stylo$", re.I)

# Finance, risk and control titles: dropped unless the title also names a technical role
# ("Associate Support Engineer - Treasury & Risk", "AML Data Analyst" stay).
DOMAIN_EXCLUDE_RE = re.compile(
    r"\baml\b|\bkyc\b|compliance|credit|financial (analyst|reporting|planning|controller|control|crime)|"
    r"financial (&|and) |fp&a|accountant|accounting|audit|\btax\b|treasury|equity|investment analyst|actuar|"
    r"\bcost (analyst|accountant|control)|business finance|shari'?a|shari’a|"
    r"finance (analyst|associate|intern|graduate)|commercial finance|portfolio (management|analyst)|"
    r"\bclaims?\b|underwrit",
    re.I,
)
TECH_CORE_RE = re.compile(
    r"data (analy|scien|engineer)|analytics|business intelligence|\bbi\b|power ?bi|machine learning|\bai\b|"
    r"software|developer|support engineer|systems? (analyst|engineer)|automation|\brpa\b|application support|"
    r"technical support|\bit (support|analyst|engineer)|\bmodel",
    re.I,
)

# Internships and other student placements: out, because employers in the UAE do not sponsor a
# work visa for them. Graduate programmes and trainee roles stay: some of those do.
INTERN_RE = re.compile(
    r"\bintern(s|ship|ships)?\b|\bsummer (analyst|associate|placement)\b|"
    r"\b(industrial|work|student) placement\b|\bplacement student\b|\bworking student\b",
    re.I,
)

# A title that names a graduate programme or a trainee role. It stays even when a job site files it
# under "Internship", as LinkedIn does with many campus roles ("AI Agent Engineer Graduate").
GRAD_TITLE_RE = re.compile(r"graduate|trainee|early (careers?|talent)|rotational|campus", re.I)

# Graduate and trainee roles in disciplines outside the target lanes.
GRAD_EXCLUDE_RE = re.compile(
    r"mechanical|civil|electrical|chemical|petroleum|structural|architect|nurs|medical|pharm|clinical|"
    r"legal|\blaw\b|finance|accounting|audit|\btax\b|sales|hospitality|chef|culinary|cabin|pilot|aircraft|"
    r"technician|\bhse\b|safety|marketing(?!.*analy)|\bhr\b(?!.*(data|analy))|human resources|procurement|"
    r"retail|store|fashion|design|interior|quantity|survey|geolog|reservoir|drilling|welding|construction|"
    r"site engineer|planning engineer|medic|shari|fulfil+ment|warehouse|\bfc\b|area manager|"
    r"instrument|\bi&c\b|control systems?|"
    r"people (and|&) (organi[sz]ation|culture)",
    re.I,
)

# A place outside the UAE named in the title ("IAM Business Analyst - Riyadh, KSA") when the
# listing's location field says Dubai: aggregators often attach the poster's office instead.
# Cities count only in location position, since some are also first names ("Lab of Dr. Riyadh A.").
ELSEWHERE_RE = re.compile(
    r"\b(ksa|saudi|qatar|bahrain|kuwait|oman|egypt|lebanon|morocco|pakistan|india)\b|"
    r"\b(riyadh|jeddah|dammam|khobar|doha|manama|muscat|cairo|amman|jordan|beirut|karachi|lahore|"
    r"bengaluru|bangalore|hyderabad|mumbai|london|singapore)\b(?=\s*([-–,)/&|]|$))",
    re.I,
)


def elsewhere(title):
    """True when the title names a place outside the UAE and no place inside it."""
    t = clean(title)
    return bool(ELSEWHERE_RE.search(t)) and not UAE_RE.search(t)

CV_HINTS = [
    (re.compile(r"software|developer|backend|python|devops|cloud|platform", re.I), "Backend_Engineer"),
    (re.compile(r"\bai\b|machine learning|\bml\b|llm|nlp", re.I), "AI_Engineer"),
    (re.compile(r"\bit\b|support|infrastructure|network|systems", re.I), "IT"),
    (re.compile(r"data scien", re.I), "Data_Scientist"),
    (re.compile(r"data engineer", re.I), "Data_Engineer"),
]


def classify(title):
    """Return (family, cv_variant) or (None, reason)."""
    t = clean(title)
    if not t:
        return None, "no-title"
    # an HR role's own words ("Recruitment Coordinator") are not what EXCLUDE_RE is there to catch
    if EXCLUDE_RE.search(HR_ROLE_RE.sub(" ", t)):
        return None, "excluded-title"
    if INTERN_RE.search(t):
        return None, "internship"
    if other_language(t):
        return None, "other-language"
    named_wide = STRONG_WIDE_RE.search(t) or HR_ROLE_RE.search(t)
    for family, cv, rx in FAMILIES:
        if named_wide and family not in WIDE_FAMILIES:
            continue
        if rx.search(t):
            if family in WIDE_FAMILIES:
                if not named_wide and ANALYST_RE.search(t):
                    continue  # "Client Services Analyst": an analyst stays in the data and tech lanes
                # "Collections Officer - Credit Cards" is a wider-net role, whatever finance word it carries
                return wider_net(family, cv, t)
            if CORE_SALES_RE.search(t):
                return None, "sales"
            if (DOMAIN_EXCLUDE_RE.search(t) and not TECH_CORE_RE.search(t)) or WALK_IN_RE.search(t):
                return None, "excluded-title"
            if family == "graduate":
                if GRAD_EXCLUDE_RE.search(t):
                    return None, "graduate-other-discipline"
                for hint, variant in CV_HINTS:
                    if hint.search(t):
                        cv = variant
                        break
            return family, cv
    if SALES_RE.search(t) or CORE_SALES_RE.search(t):
        return None, "sales"
    if (DOMAIN_EXCLUDE_RE.search(t) and not TECH_CORE_RE.search(t)) or WALK_IN_RE.search(t):
        return None, "excluded-title"
    return None, "no-family"


ANALYST_RE = re.compile(r"\banalyst\b", re.I)


def wider_net(family, cv, t):
    """The wider net's own checks on a title one of its lanes matched: (family, cv) or (None, reason)."""
    if SALES_RE.search(t):
        return None, "sales"
    if WIDE_EXCLUDE_RE.search(t):
        return None, "excluded-title"
    if family in ("admin", "operations") and re.search(r"\bcoordinator\b", t, re.I) and FIELD_COORDINATOR_RE.search(t):
        return None, "excluded-title"
    asks = EXPERIENCE_ASKED_RE.search(t) and not NO_EXPERIENCE_RE.search(t) and min_years(t) is None
    if WIDE_EXPERIENCED_RE.search(t) or asks:
        return None, "experienced-role"  # a stated number of years is left to the years rule
    return family, cv


SENIOR_HARD_RE = re.compile(
    r"\b(director|head|vp|vice president|chief|principal|principle|partner|avp|svp|evp|architect|distinguished|"
    r"executive director|general manager|deputy|ceo|cto|cio|cfo|coo|cdo|ciso|"
    r"staff (engineer|scientist|software|data|analyst|developer)|"
    r"associate (manager|director|principal|partner|vice president))\b",
    re.I,
)
SENIOR_SOFT_RE = re.compile(r"\b(senior|sr|snr|lead|manager|mgr|expert|supervisor|team leader|shift leader)\b", re.I)
# A second level or higher: "Data Analyst II", "Software Engineer ll" (typed with two L's), "SDE 2",
# "Full Stack Developer [L2]", "Level 3", "Tier 2 Support". The first level stays ("Engineer I", "L1").
LEVEL_RE = re.compile(
    r"\b(ii|ll|iii|iv)\b|\bl[2-9]\b|\b(level|tier|grade) ?([2-9]|ii|iii|iv)\b|"
    r"\b(engineer|developer|sde|analyst|scientist|consultant|specialist|associate|administrator|programmer|tester)"
    r"[ -]?[2-9]\b",
    re.I,
)
FIRST_LEVEL_RE = re.compile(r"\bl1\b|\b(level|tier) ?(1|i)\b", re.I)  # "L1/L2 Support Engineer" covers the first level
SENIOR_WORD_RE = re.compile(r"\b(senior|sr|snr)\b", re.I)
JUNIOR_RE = re.compile(
    r"\b(junior|jr|associate|graduate|grad|trainee|intern|internship|entry|fresh|apprentice|campus)\b",
    re.I,
)


def seniority(title):
    t = clean(title)
    if SENIOR_HARD_RE.search(t):
        return "senior"
    junior_words = {w.lower() for w in JUNIOR_RE.findall(t)}
    level = LEVEL_RE.search(t) and not FIRST_LEVEL_RE.search(t)
    if SENIOR_SOFT_RE.search(t) or level:
        # "Senior Associate" is a grade of its own (three to six years at the Big Four and the like), and
        # so is "Associate Engineer II": "associate" alone does not make such a title junior, the other
        # words do ("Graduate Engineer II")
        rescued = bool(junior_words - {"associate"}) or (
            "associate" in junior_words and not SENIOR_WORD_RE.search(t) and not level)
        if not rescued:
            return "senior"
    if junior_words:
        return "junior"
    return "unspecified"


NAT_PREF_RE = re.compile(
    r"nationals? (are |will be )?(strongly )?preferred|preference (will be |is )?given to (uae )?nationals|"
    r"emiratis? (are |will be )?preferred|national preferred|nationals preferred",
    re.I,
)
NAT_TITLE_RE = re.compile(
    r"uae nationals?|\buaen\b|\bemirati|emiratisation|emiratization|emiriti[sz]ation|nationals? only|tawteen|"
    r"national talent|"
    r"\bnafis\b|kawader|\bwatani\b|maseeraty|إمارات|مواطن",
    re.I,
)
NAT_DESC_RE = re.compile(
    r"nationals? only|only (for )?(uae )?nationals|uae nationals? only|open (only )?to uae nationals|"
    r"exclusively for (uae )?nationals|emirati (candidates|nationals) only|emiratis only|"
    r"(role|position|opportunity|program+e?) is (only )?(open )?(to|for) uae nationals|"
    r"\(\s*(uae nationals?|uaen|emiratis?)( only)?\s*\)|are you an? (\w+ ){0,3}(uae national|emirati)\b|"
    r"must be an? (uae national|emirati)\b|(uae|emirati) nationality (is )?(required|mandatory|a must)|"
    r"for (uae nationals?|uaen|emiratis?|emirati nationals) (applicants|candidates)|"
    r"(aimed at|designed for|dedicated to) (preparing |developing |empowering )?(young |talented )?"
    r"(uae nationals|emiratis)|family book|khulasat al[- ]qaid|"
    r"(develop|empower|nurtur)\w* (young |talented |ambitious )?(uae nationals?|emirati) "
    r"(talent|graduates|youth|students)|خلاصة القيد|"
    # "our internship programme for UAE National students" (not "... for UAE nationals and expatriates")
    r"(program+e?|internship|scheme|initiative) for (uae nationals?|emiratis?)\b"
    r"(?!\s*(and|&|or|as well as)\s*(expat|resident|international|non|other))",
    re.I,
)


def nationals(title, desc):
    """'preferred', 'only' or None."""
    title, desc = clean(title), clean(desc)
    if NAT_PREF_RE.search(title) or NAT_PREF_RE.search(desc[:3000]):
        return "preferred"
    if NAT_TITLE_RE.search(title):
        return "only"
    if NAT_DESC_RE.search(desc[:5000]):
        return "only"
    return None


# "3+ years", "2-4 years", "5 to 10 or more years": the first number is the requirement. Not the tail of
# a bigger number ("100 years" of company history) or of a decimal ("1.5 years").
YEARS_RE = re.compile(
    r"(?<![\d.,])(\d{1,2})\s*(?:\+|plus|or more)?\s*(?:(?:-|–|to)\s*(\d{1,2}))?\s*(?:\+|plus|or more)?\s*"
    r"(?:years?|yrs?)\b",
    re.I,
)


# "Up to 7 years", "less than 2 years": a ceiling. "Graduated within the last 2 years": not experience.
YEARS_CEILING_RE = re.compile(
    r"(up ?to|maximum( of)?|max\.?|no more than|less than|fewer than|under|at most|"
    r"(with)?in the (last|past)|over the (last|past)|(last|past))\s*$",
    re.I,
)


def _experience_years(desc):
    """(years, match) for each 'N years ... experience' statement in a cleaned description."""
    for m in YEARS_RE.finditer(desc):
        n = int(m.group(1))
        if n >= 15:  # company boilerplate such as 'for over 20 years'
            continue
        if YEARS_CEILING_RE.search(desc[max(0, m.start() - 16): m.start()]):
            continue
        ctx = desc[max(0, m.start() - 90): m.end() + 90].lower()
        if "experience" in ctx or "exp." in ctx:
            yield n, m


def min_years(desc):
    """The years of experience a posting asks for, or None if it names none: the first requirement it
    states. A later, smaller number is nearly always a part of it ("6-8 years of experience, including
    at least 2 years in ..."); in 118 descriptions read in November 2026 the first number was the
    requirement every time, and the smallest one was not in 5 of the 8 that had two."""
    for n, _ in _experience_years(clean(desc)):
        return n
    return None


NO_SPONSOR_RE = re.compile(
    r"(no|not|unable to|cannot|can't|will not|won't) (offer |provide )?(visa )?sponsor|"
    r"without (visa )?sponsorship|must (already )?(have|hold) (a )?(valid )?(uae )?(residence|residency|work) visa",
    re.I,
)
# Softer: the employer would rather not sponsor. Kept, but ranked lower.
OWN_VISA_RE = re.compile(r"own (residence |work )?visa|on (your )?own visa|valid uae (residence|residency) visa", re.I)


# Words that welcome a newcomer: "fresh graduates are welcome", "freshers can apply", "no prior
# experience required", "an entry-level role". Not when the same sentence says the opposite
# ("freshers please excuse", "this is not an entry-level position").
FRESH_RE = re.compile(
    r"\bfresh(er)?[- ]?grad(uate)?s?\b|\bfreshers?\b|\b(recent|new) graduates?\b|\bentry[- ]level\b|"
    r"\bno (prior |previous |work |professional )?experience (is )?(required|needed|necessary)\b",
    re.I,
)
FRESH_NOT_RE = re.compile(r"\b(not|no|non|never|without|except|excluding|excuse|don'?t|won'?t|cannot|can'?t)\b", re.I)


def fresh_ok(desc):
    """True when a description welcomes fresh graduates or people without experience."""
    desc = clean(desc)[:6000]
    for m in FRESH_RE.finditer(desc):
        if m.group(0).lower().startswith("no "):  # "no experience required" is itself the welcome
            return True
        start = max(desc.rfind(".", 0, m.start()), desc.rfind("\n", 0, m.start())) + 1
        ends = [i for i in (desc.find(".", m.end()), desc.find("\n", m.end())) if i >= 0]
        if not FRESH_NOT_RE.search(desc[start: min(ends) if ends else len(desc)]):
            return True
    return False


def evidence(title, desc, reason):
    """The words behind a nationals-only, years or no-sponsorship rejection, so that it can
    be checked by eye. Empty when the description is not at hand (facts from the cache)."""
    title, desc = clean(title), clean(desc)
    m = None
    if reason == "nationals-only":
        if NAT_TITLE_RE.search(title):
            return title[:200]
        m = NAT_DESC_RE.search(desc[:5000])
    elif reason.endswith("+ years"):
        m = next((match for _, match in _experience_years(desc)), None)
    elif reason == "no-sponsorship":
        m = NO_SPONSOR_RE.search(desc)
    return desc[max(0, m.start() - 80): m.end() + 80].strip() if m else ""


# Facts cached from full descriptions are tagged with this; when any of these patterns changes,
# cached facts are stale and those descriptions are fetched again.
FACTS_VERSION = hashlib.sha1("\n".join(rx.pattern for rx in (
    NAT_PREF_RE, NAT_TITLE_RE, NAT_DESC_RE, YEARS_RE, YEARS_CEILING_RE, NO_SPONSOR_RE,
    OWN_VISA_RE, FRESH_RE, FRESH_NOT_RE)).encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------- dedupe keys

COMPANY_SUFFIX_RE = re.compile(
    r"\b(llc|l l c|pjsc|psc|p j s c|fze|fzco|fzc|fz llc|fz|dmcc|ltd|limited|inc|incorporated|corp|corporation|"
    r"co|company|group|holding|holdings|the|plc|gmbh|sa|ag|bv|pty|pte|pvt|llp|wll|sarl|srl|bhd|sdn)\b"
)
COMPANY_ALIASES = {
    "abu dhabi islamic bank": "adib",
    "first abu dhabi bank": "fab",
    "emirates nbd bank": "emirates nbd",
    "etisalat": "e&",
    "etisalat by e&": "e&",
    "e& uae": "e&",
    "emirates telecommunications": "e&",
    "emirates integrated telecommunications": "du",
    "bayut dubizzle": "dubizzle",
    "bayut": "dubizzle",
    "majid al futtaim": "maf",
    "dp world": "dp world",
    # one employer, several names: the group's own site and the job sites name its brands differently
    "dnata": "emirates", "dnata cargo": "emirates", "dnata travel": "emirates", "emirates skycargo": "emirates",
    "emirates holidays": "emirates", "emirates security": "emirates",
    "emirates flight training academy": "emirates",
    "adnoc logistics & services": "adnoc", "adnoc distribution": "adnoc", "adnoc gas": "adnoc",
    "adnoc drilling": "adnoc", "adnoc offshore": "adnoc", "adnoc onshore": "adnoc", "adnoc refining": "adnoc",
    "adnoc global trading": "adnoc", "adnoc trading": "adnoc", "adnoc sour gas": "adnoc",
    "delivery hero": "talabat",
    "inception42": "g42", "inception": "g42", "core42": "g42", "cpx": "g42",
    "cigna healthcare": "cigna",
    "abu dhabi ports": "ad ports",
}


def norm_company(name):
    c = html.unescape(clean(name)).lower()
    # "Masdar (Abu Dhabi Future Energy Company)", "Halian | Managed Services, Recruitment"
    c = re.sub(r"\([^)]*\)", " ", c.split(" | ")[0]).replace("&amp;", "&")
    c = re.sub(r"[^\w\s&]", " ", c)
    c = COMPANY_SUFFIX_RE.sub(" ", c)
    c = WS_RE.sub(" ", c).strip()
    return COMPANY_ALIASES.get(c, c)


def norm_title(title):
    t = html.unescape(clean(title)).lower()
    t = CITY_RE.sub(" ", t)
    t = re.sub(r"\b(uae|united arab emirates|remote|hybrid|on-?site)\b", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return WS_RE.sub(" ", t).strip()


# Words that job sites add to or drop from an employer's name. They are ignored unless they are
# the first word, so "Etihad Airways" matches "Etihad" but "Emirates NBD" does not match "Emirates".
EMPLOYER_QUALIFIERS = {
    "engineer", "engineers", "engineering", "airways", "airline", "airlines", "global", "talent", "private",
    "india", "pakistan", "egypt", "middle", "east", "north", "africa", "and", "com", "international", "intl",
    "worldwide", "solutions", "services", "technologies", "technology", "tech", "consulting", "consultancy",
    "consultants", "recruitment", "recruiting", "careers", "uae", "dubai", "abu", "dhabi", "emirates", "mena",
    "gcc", "pvt",
}
TITLE_FILLER = {"and", "of", "the", "for", "in", "with", "to", "a", "an", "at", "m", "f", "d", "w"}
TITLE_NOISE_RE = re.compile(r"\b(immediate joiners?|urgent(ly)? hiring|urgent|now hiring|we are hiring|hiring)\b")


def employer_sig(name):
    """An employer's name without the qualifiers that differ between job sites
    ("ADIB - Abu Dhabi Islamic Bank", "Amazon.com", "Buro Happold Engineer India Private Limited")."""
    words = norm_company(re.split(r"\s[-–—]\s", clean(name))[0]).split()
    return " ".join(words[:1] + [w for w in words[1:] if w not in EMPLOYER_QUALIFIERS])


def title_sig(title):
    """A title's words in any order, without reference codes ("(5AD7)"), years and filler, so
    "Databricks Data Analyst" and "Data Analyst – Databricks" match."""
    words = TITLE_NOISE_RE.sub(" ", norm_title(title)).split()
    kept = sorted({w for w in words if w not in TITLE_FILLER and not any(c.isdigit() for c in w)})
    return " ".join(kept) or norm_title(title)


def job_key(company, title):
    """One key for the same job wherever it is posted. The city is left out: job sites disagree
    on it, and it changes between days."""
    raw = "%s|%s" % (employer_sig(company), title_sig(title))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- scoring

FAMILY_WEIGHT = {
    "data_analyst": 3.0, "bi": 3.0, "data_science": 3.0, "ai_ml": 3.0, "data_eng": 3.0,
    "graduate": 2.6, "software": 2.6, "product": 2.5, "business": 2.3, "analyst": 2.0, "it": 1.8,
    # the wider net ranks below the data and tech lanes
    "customer": 1.7, "collections": 1.7, "operations": 1.7, "hr": 1.5, "admin": 1.5,
}
OLD_AFTER_DAYS = 30  # an employer posting open longer than this is ranked lower; aggregator posts are dropped sooner

# Recruitment agencies and unnamed posters: flagged, not dropped. Generic words first, then agencies
# that post UAE roles often. The flag means "the employer is not who it says", so expect a screening
# call before any employer, and often a wish for candidates already in the country.
AGENCY_RE = re.compile(
    r"recruit|staffing|manpower|headhunt|executive search|resourcing|outsourc|placement|"
    r"\btalent\b|consultanc(y|ies)|hr (advisory|solutions|consult)|managed services|^confidential\b|"
    r"\bhalian\b|\baiqu\b|\blnkd\b|joblet|madison pearl|referment|lobo management|\bquantin\b|dicetek|"
    r"brad contech|michael page|robert half|robert walters|\bhays\b|randstad|adecco|charterhouse|"
    r"cooper fitch|black pearl|mark williams|propel consult|\bantal\b|\breed\b|\btasc\b|nadia global|"
    r"bac middle east|huxley|mackenzie jones|guildhall|parker connect|inspire selection|"
    # seen often in the second week of November 2026
    r"jobgether|tandem interim|durlston|kingston stanley|involved solutions|la fosse|hire ?right+|"
    r"discovered mena|pyramid consulting|mcg asia|akkodis|^salt$",
    re.I,
)


def is_agency(employer):
    return bool(AGENCY_RE.search(clean(employer)))
SOURCE_RANK = {"employer": 0, "ats": 1, "indeed": 2, "linkedin": 3, "google": 4, "bayt": 5}


def score(job):
    s = FAMILY_WEIGHT.get(job["family"], 1.5)
    if job["seniority"] == "junior" and job["family"] != "graduate":  # the graduate lane is junior by nature
        s += 1.2
    if job.get("is_new"):
        s += 1.0
    age = job.get("age_days")
    if age is not None and age <= 7:
        s += 0.5
    if age is not None and age > OLD_AFTER_DAYS:
        s -= 1.0
    if job.get("source_type") == "employer":
        s += 0.6
    flags = job.get("flags", [])
    if "nationals_preferred" in flags:
        s -= 3
    if "own_visa_preferred" in flags:
        s -= 1.5
    if "agency" in flags:
        s -= 0.5
    if "entry_level" in flags:  # the posting itself says a newcomer is welcome, or asks for a year at most
        s += 1.0
    if "mid_senior" in flags:   # LinkedIn's own label for the role
        s -= 1.0
    return round(s, 2)
