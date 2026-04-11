from __future__ import annotations

import os
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from html import unescape
from urllib.parse import urlparse

import requests

from .config import Config

AUTO_SEARCH_HINTS = (
    "latest",
    "current",
    "today",
    "news",
    "update",
    "release",
    "version",
    "price",
    "weather",
    "score",
    "stocks",
    "crypto",
    "breaking",
    "this week",
    "right now",
    "happening",
)

URL_PATTERN = re.compile(r"https?://", flags=re.IGNORECASE)
WEATHER_HINT_PATTERN = re.compile(
    r"\b(weather|forecast|temperature|rain|wind|humidity)\b",
    flags=re.IGNORECASE,
)
LOOKUP_VERB_PATTERN = re.compile(
    r"\b(check|look up|lookup|search|find|google|browse|pull up)\b",
    flags=re.IGNORECASE,
)
SCRIPT_STYLE_PATTERN = re.compile(
    r"<(script|style|noscript)\b.*?>.*?</\1>",
    flags=re.IGNORECASE | re.DOTALL,
)
TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")

WEB_EXCERPT_MAX_RESULTS = 2
WEB_EXCERPT_MAX_CHARS = 420
CURRENT_YEAR = date.today().year
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
RECENCY_TOKENS = (
    "today",
    "tonight",
    "tomorrow",
    "current",
    "latest",
    "new",
    "news",
    "update",
    "updated",
    "release",
    "price",
    "weather",
    "forecast",
    "score",
    "stocks",
    "crypto",
    "right now",
    "live",
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
QUERY_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "about",
    "into",
    "can",
    "you",
    "your",
    "please",
    "check",
    "search",
    "find",
    "look",
    "lookup",
    "google",
    "browse",
    "pull",
    "latest",
    "current",
    "today",
    "tomorrow",
    "now",
}
LOW_TRUST_HOST_HINTS = (
    "tokencalculator",
    "llm-stats",
    "chatgptimagegenerator",
    "buildfastwithai",
    "pasqualepillitteri",
)
WEATHER_TRUSTED_DOMAINS = (
    "bom.gov.au",
    "weather.gov",
    "metoffice.gov.uk",
    "accuweather.com",
    "weather.com",
    "wunderground.com",
)
OPENAI_TRUSTED_DOMAINS = (
    "openai.com",
    "platform.openai.com",
    "help.openai.com",
)
TECH_NEWS_DOMAINS = (
    "techcrunch.com",
    "theverge.com",
    "wired.com",
    "reuters.com",
    "fortune.com",
)


@dataclass
class WebContextBundle:
    query: str
    context: str
    result_count: int


@contextmanager
def _suppress_native_output() -> object:
    stdout_fd: int | None = None
    stderr_fd: int | None = None
    saved_stdout_fd: int | None = None
    saved_stderr_fd: int | None = None
    devnull_fd: int | None = None

    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    try:
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
    except Exception:
        yield
        return

    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_stdout_fd = os.dup(stdout_fd)
        saved_stderr_fd = os.dup(stderr_fd)
        os.dup2(devnull_fd, stdout_fd)
        os.dup2(devnull_fd, stderr_fd)
        yield
    finally:
        if saved_stdout_fd is not None and stdout_fd is not None:
            os.dup2(saved_stdout_fd, stdout_fd)
            os.close(saved_stdout_fd)
        if saved_stderr_fd is not None and stderr_fd is not None:
            os.dup2(saved_stderr_fd, stderr_fd)
            os.close(saved_stderr_fd)
        if devnull_fd is not None:
            os.close(devnull_fd)


def _load_ddgs_client() -> type:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise RuntimeError(
                "DuckDuckGo search requires the 'duckduckgo-search' package. "
                "Run: pip install duckduckgo-search"
            ) from exc
    return DDGS


def _clean_text(value: object, fallback: str) -> str:
    if isinstance(value, str):
        cleaned = " ".join(value.strip().split())
        if cleaned:
            return cleaned
    return fallback


def _as_result_line(title: str, url: str, snippet: str, index: int) -> list[str]:
    host = urlparse(url).netloc or "unknown-source"
    return [
        f"{index}. {title}",
        f"   Source: {host}",
        f"   URL: {url}",
        f"   Snippet: {snippet}",
    ]


def _trim_text(text: str, max_chars: int) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= max_chars:
        return compact
    clipped = compact[: max_chars - 3].rsplit(" ", 1)[0].strip()
    return (clipped or compact[: max_chars - 3]).rstrip(" ,.;:") + "..."


def _extract_page_excerpt(url: str, timeout_seconds: int) -> str | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=max(4, min(timeout_seconds, 12)),
        )
    except requests.RequestException:
        return None

    if response.status_code >= 400:
        return None

    content_type = response.headers.get("Content-Type", "").lower()
    if not (
        "text/html" in content_type
        or "application/xhtml+xml" in content_type
        or "text/plain" in content_type
    ):
        return None

    raw_text = response.text
    if not raw_text:
        return None

    text = SCRIPT_STYLE_PATTERN.sub(" ", raw_text)
    text = TAG_PATTERN.sub(" ", text)
    text = unescape(text)
    text = WHITESPACE_PATTERN.sub(" ", text).strip()
    if len(text) < 80:
        return None
    return _trim_text(text, WEB_EXCERPT_MAX_CHARS)


def _enrich_results_with_page_excerpts(
    results: list[dict[str, str]],
    timeout_seconds: int,
) -> None:
    for result in results[:WEB_EXCERPT_MAX_RESULTS]:
        url = result.get("url", "").strip()
        if not url:
            continue
        excerpt = _extract_page_excerpt(url, timeout_seconds)
        if excerpt:
            result["page_excerpt"] = excerpt


def _has_explicit_year(query: str) -> bool:
    return bool(YEAR_PATTERN.search(query))


def _is_recency_focused_query(query: str) -> bool:
    lowered = query.lower()
    return any(token in lowered for token in RECENCY_TOKENS)


def _infer_time_range(query: str) -> str | None:
    if _has_explicit_year(query):
        return None

    lowered = query.lower()
    if any(token in lowered for token in ("today", "tonight", "tomorrow", "right now", "live")):
        return "day"
    if any(token in lowered for token in ("weather", "forecast", "score", "stocks", "crypto", "price")):
        return "week"
    if _is_recency_focused_query(query):
        return "month"
    return None


def _expand_query_for_recency(query: str) -> str:
    if _has_explicit_year(query):
        return query
    if not _is_recency_focused_query(query):
        return query
    if str(CURRENT_YEAR) in query:
        return query
    return f"{query} {CURRENT_YEAR}"


def _query_tokens(query: str) -> list[str]:
    tokens = []
    for token in TOKEN_PATTERN.findall(query.lower()):
        if len(token) <= 2:
            continue
        if token in QUERY_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _normalize_host(url: str) -> str:
    host = urlparse(url).netloc.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def _domain_trust_score(query: str, host: str) -> int:
    if not host:
        return 0

    query_lower = query.lower()
    score = 0

    if any(host == domain or host.endswith(f".{domain}") for domain in OPENAI_TRUSTED_DOMAINS):
        if "openai" in query_lower or "chatgpt" in query_lower or "gpt" in query_lower:
            score += 120
        else:
            score += 20

    if any(host == domain or host.endswith(f".{domain}") for domain in WEATHER_TRUSTED_DOMAINS):
        if any(token in query_lower for token in ("weather", "forecast", "temperature", "rain", "wind")):
            score += 90
        else:
            score += 25

    if any(host == domain or host.endswith(f".{domain}") for domain in TECH_NEWS_DOMAINS):
        score += 18

    if host.endswith(".gov") or ".gov." in host:
        score += 22
    if host.endswith(".edu") or ".edu." in host:
        score += 16

    if any(hint in host for hint in LOW_TRUST_HOST_HINTS):
        score -= 30

    return score


def _result_relevance_score(
    result: dict[str, str],
    tokens: list[str],
    query: str,
) -> int:
    if not tokens:
        return 0
    title = result.get("title", "").lower()
    url = result.get("url", "").lower()
    host = _normalize_host(url)
    snippet = result.get("snippet", "").lower()
    excerpt = result.get("page_excerpt", "").lower()
    query_lower = query.lower()

    score = 0
    for token in tokens:
        if token in host:
            score += 24
        if token in title:
            score += 10
        if token in url:
            score += 6
        if token in snippet:
            score += 4
        if token in excerpt:
            score += 3

    combined = " ".join((title, snippet, excerpt, url))
    score += _domain_trust_score(query, host)
    if any(token in query_lower for token in ("today", "current", "latest", "right now")):
        if "history" in combined or "archive" in combined:
            score -= 18
    if "weather" in query_lower and "history" in combined and "forecast" not in combined:
        score -= 12
    return score


def _result_recency_score(result: dict[str, str]) -> int:
    joined = " ".join(
        (
            result.get("title", ""),
            result.get("snippet", ""),
            result.get("page_excerpt", ""),
            result.get("url", ""),
        )
    )
    lowered = joined.lower()
    score = 0

    years = [int(match.group(1)) for match in YEAR_PATTERN.finditer(joined)]
    if years:
        newest = max(years)
        if newest >= CURRENT_YEAR:
            score += 40
        elif newest == CURRENT_YEAR - 1:
            score += 20
        elif newest <= CURRENT_YEAR - 3:
            score -= 25

    if any(token in lowered for token in ("today", "tonight", "tomorrow", "live", "updated", "current")):
        score += 15
    if "weather" in lowered or "forecast" in lowered:
        score += 5

    return score


def _rerank_results_for_recency(
    records: list[dict[str, str]],
    query: str,
) -> list[dict[str, str]]:
    if not records:
        return records
    query_tokens = _query_tokens(query)
    recency_focused = _is_recency_focused_query(query)

    def sort_key(result: dict[str, str]) -> tuple[int, int]:
        relevance = _result_relevance_score(result, query_tokens, query)
        recency = _result_recency_score(result) if recency_focused else 0
        return (relevance, recency)

    return sorted(records, key=sort_key, reverse=True)


def _searxng_language(region: str) -> str:
    normalized = region.strip().lower()
    mapping = {
        "us-en": "en-US",
        "uk-en": "en-GB",
        "gb-en": "en-GB",
        "en-us": "en-US",
        "en-gb": "en-GB",
        "all": "all",
    }
    return mapping.get(normalized, region or "en-US")


def _searxng_safesearch(value: str) -> int:
    normalized = value.strip().lower()
    if normalized == "off":
        return 0
    if normalized in {"strict", "high"}:
        return 2
    return 1


def _search_web_via_searxng(
    query: str,
    *,
    config: Config,
) -> list[dict[str, str]]:
    normalized_query = " ".join(query.strip().split())
    if not normalized_query:
        raise RuntimeError("Please provide a web search query after /web.")

    limit = max(1, min(config.web_max_results, 10))
    effective_query = _expand_query_for_recency(normalized_query)
    params = {
        "q": effective_query,
        "format": "json",
        "language": _searxng_language(config.web_region),
        "safesearch": _searxng_safesearch(config.web_safesearch),
    }
    time_range = _infer_time_range(normalized_query)
    if time_range:
        params["time_range"] = time_range

    headers = {
        "Accept": "application/json",
        "User-Agent": "NovaAI/1.0 (+https://github.com/)",
    }

    try:
        response = requests.get(
            config.web_search_url,
            params=params,
            headers=headers,
            timeout=config.web_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"SearXNG request failed for {config.web_search_url}: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise RuntimeError(
            f"SearXNG returned HTTP {response.status_code} from {config.web_search_url}."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"SearXNG returned invalid JSON from {config.web_search_url}."
        ) from exc

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return []

    records: list[dict[str, str]] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        url = _clean_text(raw.get("url"), "")
        if not url:
            continue
        title = _clean_text(raw.get("title"), "Untitled result")
        snippet = _clean_text(
            raw.get("content") or raw.get("snippet"),
            "No snippet provided.",
        )
        records.append({"title": title, "url": url, "snippet": snippet})
        if len(records) >= max(limit, min(12, limit * 2)):
            break

    if records:
        _enrich_results_with_page_excerpts(records, config.web_timeout_seconds)
        records = _rerank_results_for_recency(records, normalized_query)
        records = records[:limit]
    return records


def _search_web_via_duckduckgo(
    query: str,
    *,
    config: Config,
) -> list[dict[str, str]]:
    normalized_query = " ".join(query.strip().split())
    if not normalized_query:
        raise RuntimeError("Please provide a web search query after /web.")

    DDGS = _load_ddgs_client()
    limit = max(1, min(config.web_max_results, 10))
    timelimit_map = {
        "day": "d",
        "week": "w",
        "month": "m",
    }
    time_range = _infer_time_range(normalized_query)
    timelimit = timelimit_map.get(time_range or "")
    effective_query = _expand_query_for_recency(normalized_query)
    records: list[dict[str, str]] = []

    try:
        with _suppress_native_output():
            with DDGS(timeout=config.web_timeout_seconds) as client:
                raw_results = client.text(
                    effective_query,
                    region=config.web_region,
                    safesearch=config.web_safesearch,
                    timelimit=timelimit,
                    backend="html",
                    max_results=max(limit, min(12, limit * 2)),
                )
            for raw in raw_results or []:
                if not isinstance(raw, dict):
                    continue
                url = _clean_text(raw.get("href") or raw.get("url"), "")
                if not url:
                    continue
                title = _clean_text(raw.get("title"), "Untitled result")
                snippet = _clean_text(
                    raw.get("body") or raw.get("snippet"),
                    "No snippet provided.",
                )
                records.append({"title": title, "url": url, "snippet": snippet})
                if len(records) >= max(limit, min(12, limit * 2)):
                    break
    except Exception as exc:
        raise RuntimeError(f"DuckDuckGo search failed: {exc}") from exc

    if records:
        _enrich_results_with_page_excerpts(records, config.web_timeout_seconds)
        records = _rerank_results_for_recency(records, normalized_query)
        records = records[:limit]
    return records


def search_web(query: str, config: Config) -> list[dict[str, str]]:
    if config.web_search_provider == "searxng":
        return _search_web_via_searxng(query, config=config)
    if config.web_search_provider == "duckduckgo":
        return _search_web_via_duckduckgo(query, config=config)
    raise RuntimeError(
        f"Unsupported web search provider '{config.web_search_provider}'."
    )


def should_auto_search(user_text: str) -> bool:
    text = user_text.strip()
    if len(text) < 8:
        return False
    if text.startswith("/"):
        return False
    if URL_PATTERN.search(text):
        return False

    lowered = text.lower()
    return any(hint in lowered for hint in AUTO_SEARCH_HINTS)


def _normalize_query_text(text: str) -> str:
    compact = " ".join(text.strip().split())
    compact = re.sub(r"^[,.\-:;!? ]+", "", compact)
    compact = re.sub(r"[,.\-:;!? ]+$", "", compact)
    return compact


def _strip_conversational_filler(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^\s*(hey|hi|hello)\b[,\s]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"^\s*(can|could|would|will)\s+you\b[,\s]*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^\s*please\b[,\s]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bfor\s+me\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bplease\b", "", cleaned, flags=re.IGNORECASE)
    return _normalize_query_text(cleaned)


def _extract_weather_location(text: str) -> str | None:
    for token in (" in ", " for ", " at "):
        if token not in text:
            continue
        location_candidate = text.split(token, 1)[1]
        location_candidate = re.sub(
            r"\b(today|tonight|tomorrow|right now|please|thanks|thank you)\b",
            "",
            location_candidate,
            flags=re.IGNORECASE,
        )
        location_candidate = re.sub(
            r"\bfor\s+me\b",
            "",
            location_candidate,
            flags=re.IGNORECASE,
        )
        location_candidate = _normalize_query_text(location_candidate)
        if not location_candidate:
            continue
        if location_candidate.lower() in {"me", "my", "my area", "here"}:
            continue
        return location_candidate
    return None


def extract_web_query_from_request(user_text: str) -> str | None:
    text = user_text.strip()
    if len(text) < 8:
        return None
    if text.startswith("/"):
        return None
    if URL_PATTERN.search(text):
        return None

    lowered = text.lower()
    if WEATHER_HINT_PATTERN.search(lowered):
        location = _extract_weather_location(text)
        if location:
            return f"weather {location}"
        return "weather forecast today"

    if not LOOKUP_VERB_PATTERN.search(lowered):
        return None

    stripped = _strip_conversational_filler(text)
    stripped = re.sub(
        r"^\s*(check|look up|lookup|search|find|google|browse|pull up)\s+",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"^\s*(for|about)\s+",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"^\s*me\s+",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = _normalize_query_text(stripped)
    if stripped.lower() in {"anything", "something", "it", "that", "this"}:
        return None
    return stripped or None


def build_web_context(query: str, results: list[dict[str, str]], config: Config) -> str:
    if not results:
        return (
            "Web context is unavailable right now. "
            "Be transparent and answer from existing knowledge only."
        )

    lines = [
        "Fresh web context for the next answer:",
        f"Search provider: {config.web_search_provider}",
        f"Search query: {query}",
        "Results:",
    ]
    for index, result in enumerate(results, start=1):
        result_lines = _as_result_line(
            title=result["title"],
            url=result["url"],
            snippet=result["snippet"],
            index=index,
        )
        page_excerpt = _clean_text(result.get("page_excerpt"), "")
        if page_excerpt:
            result_lines.append(f"   Website excerpt: {page_excerpt}")
        lines.extend(result_lines)
    lines.append(
        "If you reference these results, mention the source URL plainly and do not "
        "invent details that are not supported."
    )
    return "\n".join(lines)


def fetch_web_context(query: str, config: Config) -> WebContextBundle:
    results = search_web(query, config)
    if not results:
        raise RuntimeError("No web results were returned for that query.")
    return WebContextBundle(
        query=query,
        context=build_web_context(query, results, config),
        result_count=len(results),
    )
