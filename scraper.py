import re
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from urllib.parse import quote_plus

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from database import validate_and_normalize_phone, extract_place_id_from_link


ProgressCallback = Callable[[Dict], None]


@dataclass
class ScraperConfig:
    headless: bool = False
    slow_mo_ms: int = 40
    scroll_rounds: int = 18
    detail_timeout_ms: int = 8000


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def parse_rating(text: str):
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", "."))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def parse_reviews(text: str):
    if not text:
        return None
    match = re.search(r"\(?([\d,]+)\)?", text)
    if match:
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


class GoogleMapsScraper:
    """Simple Playwright-based Google Maps scraper.

    This is built for personal/local workflow. Google Maps DOM changes often,
    so selectors may need updates in the future. It does not bypass CAPTCHA or
    login walls. If Google shows a verification screen, solve it manually in the
    opened browser window.
    """

    def __init__(self, config: Optional[ScraperConfig] = None):
        self.config = config or ScraperConfig()

    def search(self, business_type: str, city: str, max_results: int = 30,
               only_no_website: bool = True, only_with_phone: bool = True,
               progress: Optional[ProgressCallback] = None) -> List[Dict]:
        query = f"{business_type} in {city}".strip()
        max_results = max(1, int(max_results or 30))
        results: List[Dict] = []

        def emit(step: str, message: str, current: int = 0, total: int = 0):
            if progress:
                progress({
                    "step": step,
                    "message": message,
                    "current": current,
                    "total": total,
                })

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.config.headless,
                slow_mo=self.config.slow_mo_ms,
            )
            context = browser.new_context(
                viewport={"width": 1366, "height": 850},
                locale="en-US",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            search_url = f"https://www.google.com/maps/search/{quote_plus(query)}"
            emit("opening", f"Opening Google Maps search: {query}")
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            self._try_accept_cookies(page)
            page.wait_for_timeout(3000)

            emit("collecting", "Collecting business links from search results")
            place_links = self._collect_place_links(page, max_results=max_results)
            emit("collected", f"Collected {len(place_links)} possible business links", len(place_links), max_results)

            for index, link in enumerate(place_links[:max_results], start=1):
                emit("details", f"Reading lead {index} of {min(len(place_links), max_results)}", index, min(len(place_links), max_results))
                try:
                    detail = self._read_place_detail(page, link)
                    detail["city"] = city
                    detail["category"] = business_type
                    detail["source_query"] = query
                    if only_no_website and detail.get("website"):
                        continue
                    if only_with_phone and not detail.get("phone"):
                        continue
                    if detail.get("business_name"):
                        results.append(detail)
                except Exception as exc:
                    emit("warning", f"Skipped one listing because of error: {exc}", index, min(len(place_links), max_results))
                    continue

            emit("done", f"Finished. Useful leads found: {len(results)}", len(results), max_results)
            context.close()
            browser.close()
        return results

    def _try_accept_cookies(self, page):
        for label in ["Accept all", "I agree", "Accept"]:
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.I))
                if btn.count() > 0:
                    btn.first.click(timeout=2000)
                    page.wait_for_timeout(1000)
                    return
            except Exception:
                pass

    def _collect_place_links(self, page, max_results: int) -> List[str]:
        links: List[str] = []
        seen = set()

        for _ in range(self.config.scroll_rounds):
            page.wait_for_timeout(1200)
            anchors = page.locator("a[href*='/maps/place/']")
            try:
                count = anchors.count()
            except Exception:
                count = 0
            for i in range(count):
                try:
                    href = anchors.nth(i).get_attribute("href")
                    if href and "/maps/place/" in href and href not in seen:
                        seen.add(href)
                        links.append(href)
                except Exception:
                    continue
            if len(links) >= max_results:
                break
            # Scroll results panel. Google usually uses role=feed, but we keep fallback.
            try:
                feed = page.locator("div[role='feed']").first
                feed.evaluate("el => el.scrollBy(0, el.scrollHeight)")
            except Exception:
                try:
                    page.mouse.wheel(0, 2500)
                except Exception:
                    pass
        return links

    def _read_place_detail(self, page, link: str) -> Dict:
        page.goto(link, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        name = self._first_text(page, ["h1.DUwDvf", "h1"])
        address = self._button_text_by_data(page, "address") or self._aria_text(page, ["Address:"])
        phone = self._phone(page)
        website = self._website(page)
        rating = self._rating(page)
        reviews = self._reviews(page)

        return {
            "business_name": clean_text(name),
            "phone": clean_text(phone),
            "address": clean_text(address),
            "website": clean_text(website),
            "has_website": 1 if website else 0,
            "google_map_link": link,
            "google_place_id": extract_place_id_from_link(link),
            "rating": rating,
            "reviews_count": reviews,
        }

    def _first_text(self, page, selectors: List[str]) -> str:
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if loc.count() > 0:
                    txt = loc.inner_text(timeout=self.config.detail_timeout_ms)
                    txt = clean_text(txt)
                    if txt:
                        return txt
            except Exception:
                continue
        return ""

    def _button_text_by_data(self, page, token: str) -> str:
        selectors = [
            f"button[data-item-id*='{token}']",
            f"div[data-item-id*='{token}']",
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if loc.count() > 0:
                    aria = loc.get_attribute("aria-label", timeout=2500) or ""
                    txt = loc.inner_text(timeout=2500) or ""
                    value = aria or txt
                    value = re.sub(r"^(Address|Phone|Website):\s*", "", value, flags=re.I)
                    value = re.sub(r"^Located in:\s*", "", value, flags=re.I)
                    return clean_text(value)
            except Exception:
                continue
        return ""

    def _aria_text(self, page, prefixes: List[str]) -> str:
        for prefix in prefixes:
            try:
                loc = page.locator(f"button[aria-label^='{prefix}']").first
                if loc.count() > 0:
                    aria = loc.get_attribute("aria-label") or ""
                    return clean_text(aria.replace(prefix, ""))
            except Exception:
                continue
        return ""

    def _phone(self, page) -> str:
        candidates = [
            "button[data-item-id^='phone:tel:']",
            "button[aria-label^='Phone:']",
            "button[aria-label*='Call']",
            "div[data-item-id^='phone:tel:']",
        ]
        for selector in candidates:
            try:
                loc = page.locator(selector).first
                if loc.count() > 0:
                    aria = loc.get_attribute("aria-label", timeout=2500) or ""
                    txt = loc.inner_text(timeout=2500) or ""
                    value = aria or txt
                    value = value.replace("Phone:", "").replace("Call", "")
                    phone_info = validate_and_normalize_phone(value)
                    if phone_info.get("phone_status") == "Valid":
                        return phone_info.get("phone") or clean_text(value)
            except Exception:
                continue

        # Fallback: inspect only lines that look like contact details, not the whole rating/review area.
        try:
            body = page.locator("body").inner_text(timeout=3000)
            for line in body.splitlines():
                line = clean_text(line)
                if not line or len(line) > 80:
                    continue
                if any(word in line.lower() for word in ["review", "star", "rating"]):
                    continue
                phone_info = validate_and_normalize_phone(line)
                if phone_info.get("phone_status") == "Valid":
                    return phone_info.get("phone") or line
        except Exception:
            return ""
        return ""

    def _website(self, page) -> str:
        candidates = [
            "a[data-item-id='authority']",
            "a[aria-label^='Website:']",
            "a[href^='http']:has-text('Website')",
        ]
        for selector in candidates:
            try:
                loc = page.locator(selector).first
                if loc.count() > 0:
                    href = loc.get_attribute("href", timeout=2500) or ""
                    if href and "google." not in href and "maps" not in href:
                        return clean_text(href)
            except Exception:
                continue
        return ""

    def _rating(self, page):
        candidates = ["div.F7nice span[aria-hidden='true']", "span[aria-label*='stars']", "div[aria-label*='stars']"]
        for selector in candidates:
            try:
                loc = page.locator(selector).first
                if loc.count() > 0:
                    text = (loc.get_attribute("aria-label") or loc.inner_text(timeout=2500) or "")
                    rating = parse_rating(text)
                    if rating is not None:
                        return rating
            except Exception:
                continue
        return None

    def _reviews(self, page):
        candidates = ["button[jsaction*='pane.reviewChart.moreReviews']", "span[aria-label*='reviews']"]
        for selector in candidates:
            try:
                loc = page.locator(selector).first
                if loc.count() > 0:
                    text = (loc.get_attribute("aria-label") or loc.inner_text(timeout=2500) or "")
                    reviews = parse_reviews(text)
                    if reviews is not None:
                        return reviews
            except Exception:
                continue
        return None
