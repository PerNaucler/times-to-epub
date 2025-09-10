#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Times → EPUB (thin Chrome + retries + rotation)

- Logs in with Selenium (single session, no parallelism).
- Collects /article/ links from an edition/section page.
- Fetches each article via the already-logged-in driver.
- Uses Readability (with AMP + JSON-LD fallbacks).
- Builds one HTML and converts to EPUB via calibre (if installed).
- Runs a *thin* Chrome (blocked images/fonts/video/ads, fewer renderers).
- Rotates the driver every N articles to avoid memory creep.
"""

from __future__ import annotations
import os, sys, time, argparse, datetime, subprocess, re
from pathlib import Path
from typing import List, Tuple, Optional

from dotenv import load_dotenv # New 2025-08-12
load_dotenv()  # .env next to the script, if present
load_dotenv(Path.home() / ".env")  # fallback to ~/.env
#load_dotenv(dotenv_path=os.path.expanduser("~/.env")) # New 2025-08-12

# -------------------- deps --------------------
import requests
from bs4 import BeautifulSoup
from readability import Document
from tqdm import tqdm

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, WebDriverException, NoSuchElementException
)

# -------------------- constants --------------------
DEFAULT_EDITION = "https://www.thetimes.com/world"     # <-- This is the one you said works best
START_URL = "https://login.thetimes.co.uk/"            # stable login entry

OUT_DIR = Path("times_dump")
OUT_DIR.mkdir(exist_ok=True)

# -------------------- util --------------------
def log(msg: str) -> None:
    print(msg, flush=True)

def now_iso() -> str:
    return datetime.date.today().isoformat()

# -------------------- driver --------------------
def build_driver(headless: bool = True, page_timeout: int = 90, script_timeout: int = 30) -> webdriver.Chrome:
    """Create a *thin* Chrome with heavy assets blocked."""
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,2400")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    # Fewer renderer processes; disable site isolation trials to reduce processes
    opts.add_argument("--renderer-process-limit=3")
    opts.add_argument("--disable-features=IsolateOrigins,site-per-process,Translate,BackForwardCache,MediaRouter")
    # Block images by default to reduce bandwidth/CPU
    opts.add_argument("--blink-settings=imagesEnabled=false")
    prefs = {
        "profile.managed_default_content_settings.images": 2,
    }
    opts.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(service=ChromeService(), options=opts)
    driver.set_page_load_timeout(page_timeout)
    driver.set_script_timeout(script_timeout)

    # CDP blocking of heavy/irrelevant URLs (best-effort; ignore if not available)
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {
            "urls": [
                "*.png","*.jpg","*.jpeg","*.gif","*.webp","*.svg",
                "*.mp4","*.webm","*.m3u8","*.mp3","*.wav",
                "*.woff","*.woff2","*.ttf","*.otf",
                "*doubleclick.net/*","*googlesyndication.com/*","*scorecardresearch.com/*",
                "*googletagmanager.com/*","*analytics.google.com/*","*facebook.net/*","*hotjar.com/*"
            ]
        })
    except Exception:
        pass

    return driver

# högst upp i filen:
import tempfile, shutil, atexit # This could possibly be removed -- relates to an old build_driver


import os, tempfile, shutil, atexit # This could possibly be removed -- for old build_driver
from selenium import webdriver      # This could possibly be removed -- for old build_driver
from selenium.webdriver.chrome.service import Service as ChromeService # ... and this

# -------------------- login helpers (same spirit as your working one) --------------------
def wait_and_click(driver, xpath, timeout=15):
    elem = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.XPATH, xpath))
    )
    elem.click()
    return elem

def close_cookie_banner(driver):
    # liberal matching — banners vary over time
    try:
        for text in ("Accept all", "Accept", "I agree", "Got it", "Continue"):
            buttons = driver.find_elements(By.XPATH, f"//button[contains(translate(., 'ACEIPT', 'aceipt'),'accept') or contains(., '{text}')]")
            if buttons:
                buttons[0].click()
                time.sleep(0.4)
                return
    except Exception:
        pass

def open_signin_dialog(driver):
    try:
        driver.find_element(By.CSS_SELECTOR, "input[type='email']")
        return
    except NoSuchElementException:
        pass
    # try a generic "Sign in" button if present
    for label in ("Sign in", "Log in", "Sign In", "Log In"):
        try:
            wait_and_click(driver, f"//button[contains(., '{label}') or contains(., '{label.upper()}')]", timeout=8)
            return
        except TimeoutException:
            continue

def find_login_fields(driver, timeout=20):
    """Recursively search iframes for email/password fields."""
    def _scan():
        try:
            email = driver.find_element(By.CSS_SELECTOR, "input[type='email']")
            pwd   = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
            return email, pwd
        except NoSuchElementException:
            pass
        for fr in driver.find_elements(By.TAG_NAME, "iframe"):
            driver.switch_to.frame(fr)
            try:
                res = _scan()
                if res:
                    return res
            finally:
                driver.switch_to.parent_frame()
        return None

    end = time.time() + timeout
    while time.time() < end:
        got = _scan()
        if got:
            return got
        time.sleep(0.4)
    raise RuntimeError("Kunde inte hitta inloggnings­fälten.")

def login_to_times(driver, user: str, password: str) -> None:
    log("🔑 Loggar in …")
    driver.get(START_URL)
    close_cookie_banner(driver)
    open_signin_dialog(driver)
    email_field, pwd_field = find_login_fields(driver, timeout=25)

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", email_field)
    email_field.clear(); email_field.send_keys(user)
    pwd_field.clear();   pwd_field.send_keys(password)
    pwd_field.submit()

    # wait until we are on a post-login page
    WebDriverWait(driver, 30).until(
        lambda d: ("mytimes" in d.current_url) or ("thetimes" in d.current_url and "login" not in d.current_url)
    )
    log("✅ Inloggad.")

# -------------------- collection --------------------
def collect_article_links(driver, edition_url: str) -> List[str]:
    log("🔎 Letar artiklar …")
    driver.get(edition_url)
    time.sleep(1.0)  # let initial HTML settle
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    links = []
    for a in soup.select("a[href]"):
        href = a["href"]
        if "/article/" not in href:
            continue
        # normalize
        if href.startswith("/"):
            # infer scheme+host from edition_url
            m = re.match(r"^https?://[^/]+", edition_url)
            base = m.group(0) if m else "https://www.thetimes.com"
            href = base + href
        if href not in links:
            links.append(href)

    log(f"🔗 Hittade {len(links)} länkar")
    return links

# -------------------- content helpers --------------------
def try_amp(session: requests.Session, url: str, timeout=20) -> Optional[Tuple[str,str]]:
    """Try the public AMP page as a quick fallback."""
    amp_url = url.rstrip("/") + "/amp"
    try:
        r = session.get(amp_url, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        # Title
        title = soup.title.string.strip() if soup.title and soup.title.string else "Untitled"
        # Body candidates
        body_node = soup.find("article") or soup.find("main") or soup.find(attrs={"data-component": "article-body"})
        if not body_node:
            return None
        body_html = str(body_node)
        if len(BeautifulSoup(body_html, "html.parser").get_text(" ").strip()) < 400:
            return None
        return title, body_html
    except Exception:
        return None

def try_jsonld(html: str) -> Optional[Tuple[str,str]]:
    """Parse JSON-LD for articleBody if present."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(tag.string or "")
            except Exception:
                continue
            # schema can be a dict or list
            blobs = data if isinstance(data, list) else [data]
            for obj in blobs:
                if isinstance(obj, dict) and obj.get("@type") in ("NewsArticle", "Article"):
                    title = obj.get("headline") or obj.get("name")
                    body = obj.get("articleBody")
                    if title and body and len(body) > 400:
                        # wrap plain text body
                        body_html = "<article>" + "".join(f"<p>{p.strip()}</p>" for p in body.split("\n") if p.strip()) + "</article>"
                        return title, body_html
        return None
    except Exception:
        return None

def fetch_article(driver, url: str, session: requests.Session, debug=False) -> Optional[Tuple[str,str]]:
    """
    Fetch article HTML via the logged-in driver, with fallbacks:
    1) Driver + Readability (primary)
    2) JSON-LD articleBody (from driver HTML)
    3) Public AMP page (via requests)
    """
    try:
        driver.get(url)
    except TimeoutException as e:
        if debug: log(f"  ↳ get() timeout on {url} ({e})")
        # try to stop navigation to recover the tab
        try: driver.execute_script("window.stop();")
        except Exception: pass
        # we still try to read source (if any) to salvage JSON-LD
    except WebDriverException as e:
        if debug: log(f"  ↳ WebDriverException on get({url}): {e}")
        return None

    # Wait for article-ish content if possible
    try:
        WebDriverWait(driver, 15).until(
            lambda d: d.find_elements(By.TAG_NAME, "article") or d.find_elements(By.TAG_NAME, "main")
        )
    except TimeoutException:
        if debug: log("  ↳ no visible <article>/<main> after 15s")

    # 1) Readability on full HTML
    try:
        html = driver.page_source
        doc = Document(html)
        title = (doc.title() or "").strip() or (BeautifulSoup(html, "html.parser").title.string if BeautifulSoup(html, "html.parser").title else "Untitled")
        body = doc.summary(html_partial=True)
        # sanity: make sure it isn't the paywall teaser
        text_len = len(BeautifulSoup(body, "html.parser").get_text(" ").strip())
        if text_len >= 800:
            return title, body
        if debug: log("  ↳ Readability extract seems short, trying JSON-LD …")
    except WebDriverException as e:
        if debug: log(f"  ↳ page_source error: {e}")

    # 2) JSON-LD articleBody
    try:
        html = driver.page_source
        jsonld = try_jsonld(html)
        if jsonld:
            return jsonld
    except Exception:
        pass

    # 3) AMP fallback (often public)
    amp = try_amp(session, url, timeout=25)
    if amp:
        if debug: log("  ↳ AMP-hack lyckades")
        return amp

    if debug:
        log("  ↳ kunde inte extrahera artikelinnehåll")
    return None

# -------------------- session (requests) --------------------
def requests_session() -> requests.Session:
    s = requests.Session()
    # generic browser UA
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    # retries/backoff
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
    retry = Retry(
        total=4, connect=4, read=4, backoff_factor=0.6,
        status_forcelist=[429,500,502,503,504], allowed_methods=False
    )
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s

# -------------------- build & EPUB --------------------
def build_html(pieces: List[Tuple[str,str]]) -> str:
    parts = []
    for title, body in pieces:
        parts.append(f"<h1>{title}</h1>\n{body}")
    return (
        "<html><head><meta charset='utf-8'>"
        "<style>img{max-width:100%} body{font-family:serif;line-height:1.5}</style>"
        "</head><body>\n" + "\n<hr/>\n".join(parts) + "\n</body></html>"
    )

def create_epub(html_path: Path, title: Optional[str] = None) -> Optional[Path]:
    epub_path = html_path.with_suffix(".epub")
    try:
        subprocess.run(
            ["ebook-convert", str(html_path), str(epub_path),
             "--authors", "The Times",
             "--title", title or f"The Times {html_path.stem[-10:]}"],
            check=True
        )
        return epub_path
    except FileNotFoundError:
        log("ℹ️  calibre’s `ebook-convert` not found — skipped EPUB conversion.")
        return None
    except subprocess.CalledProcessError as e:
        log(f"⚠️  ebook-convert failed: {e}")
        return None

# ------------ Lyx --------------------------------------------------
def _looks_like_corrections(url: str, title: Optional[str]=None) -> bool:
    u = url.lower()
    if "corrections" in u and "clarifications" in u:
        return True
    if title and "corrections and clarifications" in (title or "").lower():
        return True
    return False


# -------------------- main --------------------
def main():
    ap = argparse.ArgumentParser(description="The Times → EPUB (thin Chrome)")
    ap.add_argument("--user", help="Times username (or set TIMES_USER)", default=os.getenv("TIMES_USER"))
    ap.add_argument("--password", help="Times password (or set TIMES_PASS)", default=os.getenv("TIMES_PASS"))
    ap.add_argument("--edition", default=DEFAULT_EDITION, help="Edition/section URL to collect links from")
    ap.add_argument("--headless", action="store_true", help="Run headless Chrome")
    ap.add_argument("--rotate-every", type=int, default=10, help="Restart browser every N articles")
    ap.add_argument("--max", type=int, default=0, help="Max number of articles (0 = all)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if not args.user or not args.password:
        sys.exit("⚠️  Provide credentials via --user/--password or env TIMES_USER/TIMES_PASS")

    log("🚀 Startar Times→EPUB-script …")

    sess = requests_session()
    driver = build_driver(headless=args.headless)
    processed: List[Tuple[str,str]] = []

    try:
        login_to_times(driver, args.user, args.password)
        links = collect_article_links(driver, args.edition)
        links = [u for u in links if not _looks_like_corrections(u)] # Lyx
        if args.max and args.max < len(links):
            links = links[:args.max]

        pbar = tqdm(total=len(links), dynamic_ncols=True, desc="Hämtar artiklar")
        for i, url in enumerate(links, 1):
            # rotate driver to keep it healthy
            if i > 1 and (i-1) % max(1, args.rotate_every) == 0:
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(0.8)
                driver = build_driver(headless=args.headless)
                login_to_times(driver, args.user, args.password)

            try:
                res = fetch_article(driver, url, sess, debug=args.debug)
                if res:
                    processed.append(res)
                else:
                    if args.debug:
                        log(f"⚠️  misslyckades med {url}")
            except Exception as e:
                if args.debug:
                    log(f"⚠️  undantag på {url}: {e}")
            finally:
                pbar.update(1)
                # tiny breather; avoids pegging CPU
                time.sleep(0.15)

        pbar.close()

        if not processed:
            log("⚠️  Inga artiklar samlades in. Avslutar.")
            return

        html_str = build_html(processed)
        out_html = OUT_DIR / f"times_{now_iso()}.html"
        out_html.write_text(html_str, encoding="utf-8")
        log(f"📄 Sparade HTML → {out_html}")

        epub = create_epub(out_html, title=f"The Times {now_iso()}")
        if epub:
            log(f"📚 Klar EPUB → {epub}")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
