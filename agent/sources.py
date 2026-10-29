"""The source list.

Tier drives the "source authority" part of the score (see score.py):
    A = university / public research lab     -> 25 pts
    B = corporate research lab               -> 22 pts
    C = journal / preprint                   -> 20 pts
    D = press reporting on a primary source  -> 12 pts

Feed URLs were verified live. Entries with enabled=False have NO working
feed as of the last check — they need RSSHub or an Exa monitor (phase 9).
Leave them in the table so source_health reports them as known gaps rather
than silently pretending they do not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


def _google_news(query: str, days: int = 7) -> str:
    """A Google News search feed (India edition), last `days` days only."""
    return ("https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q="
            + quote(f"{query} when:{days}d"))


_GN_NOTE = "Google News search; links are redirects, so it is scored from the headline"


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    tier: str
    kind: str = "rss"          # rss | json | gdelt | exa
    url: str = ""
    enabled: bool = True
    note: str = ""


SOURCES: list[Source] = [
    # ---------------------------------------------------- Tier A
    Source("mit_ai", "MIT News (AI)", "A",
           url="https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml"),
    Source("mit_main", "MIT News", "A",
           url="https://news.mit.edu/rss/feed"),
    Source("mit_csail", "MIT CSAIL", "A",
           url="https://news.mit.edu/rss/topic/computer-science-and-artificial-intelligence-laboratory-csail",
           note="low volume"),
    Source("mit_tr", "MIT Technology Review", "A",
           url="https://www.technologyreview.com/feed/"),
    Source("bair", "Berkeley BAIR", "A",
           url="https://bair.berkeley.edu/blog/feed.xml",
           note="only ~3 items in feed; poll often or you miss items"),
    Source("cmu_ml", "CMU ML Blog", "A",
           url="https://blog.ml.cmu.edu/feed/"),
    Source("cmu_scs", "CMU SCS", "A",
           url="https://www.cs.cmu.edu/news/feed.rss", note="low volume"),
    Source("caltech", "Caltech", "A",
           url="https://www.caltech.edu/about/news/rss"),
    Source("ethz", "ETH Zurich", "A",
           url="https://www.ethz.ch/en/news-und-veranstaltungen/eth-news/news/_jcr_content.feed.html"),
    Source("mpg", "Max Planck", "A",
           url="https://www.mpg.de/en/research.rss"),
    Source("cambridge", "Cambridge", "A",
           url="https://www.cam.ac.uk/news/feed"),
    Source("harvard", "Harvard Gazette", "A",
           url="https://news.harvard.edu/gazette/feed/",
           note="SEAS has no feed; Gazette is the substitute"),
    Source("stanford_hai", "Stanford HAI", "A", enabled=False,
           note="NO FEED - needs RSSHub or Exa monitor"),
    Source("oxford", "Oxford", "A", enabled=False,
           note="NO FEED - needs RSSHub or Exa monitor"),
    Source("jhuapl", "Johns Hopkins APL", "A", enabled=False,
           note="NO FEED - needs RSSHub or Exa monitor"),

    # ---------------------------------------------------- Tier B
    Source("google_research", "Google Research", "B",
           url="https://research.google/blog/rss/"),
    Source("deepmind", "Google DeepMind", "B",
           url="https://deepmind.google/blog/rss.xml"),
    Source("openai", "OpenAI", "B",
           url="https://openai.com/news/rss.xml"),
    Source("msr", "Microsoft Research", "B",
           url="https://www.microsoft.com/en-us/research/feed/"),
    Source("nvidia", "NVIDIA Technical Blog", "B",
           url="https://developer.nvidia.com/blog/feed/"),
    Source("apple_ml", "Apple ML Research", "B",
           url="https://machinelearning.apple.com/rss.xml"),
    Source("amazon_science", "Amazon Science", "B",
           url="https://www.amazon.science/index.rss"),
    Source("mistral", "Mistral AI", "B",
           url="https://mistral.ai/news/rss"),
    Source("huggingface", "Hugging Face", "B",
           url="https://huggingface.co/blog/feed.xml"),
    Source("ibm", "IBM Research", "B",
           url="https://newsroom.ibm.com/press-releases-research-and-innovation?pagetemplate=rss"),
    Source("anthropic", "Anthropic", "B", enabled=False,
           note="NO OFFICIAL FEED - needs RSSHub or Exa monitor"),
    Source("meta_ai", "Meta AI", "B", enabled=False,
           note="NO FEED - needs RSSHub or Exa monitor"),
    Source("qwen", "Qwen / Alibaba", "B", enabled=False,
           note="old github feed stale since Sep 2025 - use Exa on qwen.ai"),

    # ---------------------------------------------------- Tier C
    # arXiv: poll each category SEPARATELY. The cs.AI+cs.LG multi-category
    # syntax returns a valid channel with ZERO items. Dedupe by arXiv id.
    Source("arxiv_ai", "arXiv cs.AI", "C",
           url="https://rss.arxiv.org/rss/cs.AI",
           note="rebuilt ~04:00 UTC daily, 50 items, gate on external signal"),
    Source("arxiv_lg", "arXiv cs.LG", "C",
           url="https://rss.arxiv.org/rss/cs.LG"),
    Source("arxiv_cl", "arXiv cs.CL", "C",
           url="https://rss.arxiv.org/rss/cs.CL"),
    Source("hf_papers", "HF Daily Papers", "C", kind="json",
           url="https://huggingface.co/api/daily_papers",
           note="has upvotes - use as the arXiv signal gate"),
    Source("nature", "Nature", "C",
           url="https://www.nature.com/nature.rss"),
    Source("nature_mi", "Nature Machine Intelligence", "C",
           url="https://www.nature.com/natmachintell.rss", note="monthly"),
    Source("nature_ml", "Nature: machine learning", "C",
           url="https://www.nature.com/subjects/machine-learning.rss"),
    Source("science", "Science News", "C",
           url="https://www.science.org/rss/news_current.xml",
           note="403s from datacentre IPs - may fail from Actions runners"),

    # ---------------------------------------------------- Tier D
    Source("techcrunch_ai", "TechCrunch AI", "D",
           url="https://techcrunch.com/category/artificial-intelligence/feed/"),
    Source("ieee", "IEEE Spectrum", "D",
           url="https://spectrum.ieee.org/feeds/feed.rss"),
    Source("venturebeat", "VentureBeat AI", "D",
           url="https://venturebeat.com/category/ai/feed/"),
    Source("hn", "Hacker News 100+", "D",
           url="https://hnrss.org/frontpage?points=100",
           note="points filter confirmed working"),
    Source("the_information", "The Information", "D",
           url="https://www.theinformation.com/feed",
           note="headline + 1 sentence only, hard paywall"),
    Source("semianalysis", "SemiAnalysis", "D",
           url="https://newsletter.semianalysis.com/feed",
           note="NOT semianalysis.com/feed - that one is stale since 2025"),
    Source("stratechery", "Stratechery", "D",
           url="https://stratechery.com/feed/", note="descriptions only"),
    Source("arstechnica", "Ars Technica", "D",
           url="https://feeds.arstechnica.com/arstechnica/index",
           note="403s from some datacentre IPs - real UA set in ingest"),
    Source("verge_ai", "The Verge AI", "D",
           url="https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    Source("wired_ai", "Wired AI", "D",
           url="https://www.wired.com/feed/tag/ai/latest/rss"),
    Source("reuters", "Reuters Tech", "D", enabled=False,
           note="RSS deprecated - get via GDELT instead"),
    Source("bloomberg", "Bloomberg Tech", "D", enabled=False,
           note="robots-disallowed - get via GDELT instead"),

    # ---------------------------------------------------- Beyond AI (Oct 2026)
    # Every domain the scorer knows (see DOMAINS in config.py). Feeds were tested
    # live on 21 Oct 2026; ~items/day is from that test. Total ~150/day, chosen so
    # scoring (~250/day on Groq's free tier) keeps up.
    # EVs and mobility
    Source("electrek", "Electrek", "D", url="https://electrek.co/feed/", note="~16/day"),
    Source("insideevs", "InsideEVs", "D", url="https://insideevs.com/rss/news/all/"),
    Source("tc_transport", "TechCrunch Transportation", "D",
           url="https://techcrunch.com/category/transportation/feed/"),
    Source("verge_transport", "The Verge Transportation", "D",
           url="https://www.theverge.com/rss/transportation/index.xml"),
    # Space
    Source("spacenews", "SpaceNews", "D", url="https://spacenews.com/feed/"),
    Source("nasa", "NASA", "B", url="https://www.nasa.gov/news-release/feed/",
           note="tier B not A: ~9 press releases/day, most minor"),
    # Health, energy, chips, security, robotics, science
    Source("endpoints", "Endpoints News", "D", url="https://endpts.com/feed/"),
    Source("canary", "Canary Media", "D", url="https://www.canarymedia.com/rss.rss"),
    Source("utilitydive", "Utility Dive", "D", url="https://www.utilitydive.com/feeds/news/"),
    Source("eetimes", "EE Times", "D", url="https://www.eetimes.com/feed/"),
    Source("thehackernews", "The Hacker News", "D",
           url="https://feeds.feedburner.com/TheHackersNews", note="~16/day"),
    Source("krebs", "Krebs on Security", "D", url="https://krebsonsecurity.com/feed/"),
    Source("robotreport", "The Robot Report", "D", url="https://www.therobotreport.com/feed/"),
    Source("quanta", "Quanta Magazine", "D", url="https://www.quantamagazine.org/feed/"),
    Source("sciencedaily", "ScienceDaily (tech)", "D",
           url="https://www.sciencedaily.com/rss/top/technology.xml"),
    # India: tech, legal, market
    Source("et_tech", "ET Tech", "D",
           url="https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms", note="~14/day"),
    Source("medianama", "MediaNama", "D", url="https://www.medianama.com/feed/"),
    Source("barandbench", "Bar & Bench", "D", url="https://www.barandbench.com/feed"),
    Source("scc_online", "SCC Online Blog", "D", url="https://www.scconline.com/blog/feed"),
    Source("gn_dispute_india", "Dispute resolution India (Google News)", "D",
           url=_google_news('arbitration OR mediation OR "online dispute resolution" OR IBC '
                            'OR SARFAESI OR "debt recovery tribunal" india'),
           note=_GN_NOTE),
    Source("economic_times", "Economic Times", "D",
           url="https://economictimes.indiatimes.com/rssfeedsdefault.cms"),
    Source("inc42", "Inc42", "D", url="https://inc42.com/feed/"),
    Source("gn_startups_india", "Startup funding India (Google News)", "D",
           url=_google_news("startup funding india"), note=_GN_NOTE),
    Source("gn_fintech_india", "Fintech India (Google News)", "D",
           url=_google_news("fintech india"), note=_GN_NOTE),
    # Competitors: one search per group of names, not one per company
    Source("gn_odr_competitors", "ODR competitors (Google News)", "D",
           url=_google_news('"Jupitice" OR "Webnyay" OR "SMART ODR" OR "CADRE ODR" OR "JustAct" '
                            'OR "WeVaad" OR "Sama ODR" OR "adrEdge" OR "Presolv360"'),
           note=_GN_NOTE),
    Source("gn_legaltech_india", "Legal tech India (Google News)", "D",
           url=_google_news('"Credgenics" OR "SpotDraft" OR "Legistify" OR "CaseMine" OR "NearLaw" '
                            'OR legaltech india'),
           note=_GN_NOTE),
    Source("gn_legaltech_global", "Legal tech global (Google News)", "D",
           url=_google_news('"Clio" legal OR "Smokeball" OR "PracticePanther" OR "LegalZoom" '
                            'OR "Harvey AI" legal'),
           note=_GN_NOTE),
]


# Research-paper feeds. They outnumber news about 10 to 1, so later stages
# handle news first and papers after (see score.py).
ARXIV_SOURCES = ("arxiv_ai", "arxiv_lg", "arxiv_cl")
PAPER_SOURCES = ARXIV_SOURCES + ("hf_papers",)


REQUEST_PREFIX = "req_"


def requested_sources(rows: list[dict]) -> list[Source]:
    """Source requests an admin approved on the website (Supabase source_request) as tier-D feeds.

    A feed that sources.py already has is skipped, so approving it twice never polls it twice.
    """
    known = {s.url.rstrip("/").lower() for s in SOURCES if s.url}
    out = []
    for r in rows:
        url = str(r.get("url") or "").strip()
        name = str(r.get("name") or "").strip()
        if not name or not url.lower().startswith(("http://", "https://")):
            continue
        if url.rstrip("/").lower() in known:
            continue
        known.add(url.rstrip("/").lower())
        out.append(Source(id=f"{REQUEST_PREFIX}{r['id']}", name=name[:120], tier="D", url=url,
                          note="requested on the website"))
    return out


def enabled_sources() -> list[Source]:
    return [s for s in SOURCES if s.enabled and s.url]


def by_id(source_id: str) -> Source | None:
    return next((s for s in SOURCES if s.id == source_id), None)
