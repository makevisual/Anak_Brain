
import os
import sys
import json
import argparse
from typing import Dict, Any, List, Optional
import requests

API_URL     = "https://makevisual.com/brain/mediawiki/api.php"
BOT_USER    = "Aaron Dabelow@Anak_Brain"
BOT_PASS    = "4qev3mk00233bcioss8hguslkerdoghk"
USER_AGENT  = "AnakBrainBot/0.1 (+contact: aarond@makevisual.com)"

# MediaWikiClient Class
class MWClient:
    def __init__(self, api_url: str, user: str, password: str, user_agent: str = USER_AGENT):
        if not api_url.endswith("api.php"):
            raise ValueError("API URL must point to .../api.php")
        self.api_url = api_url
        self.user = user
        self.password = password
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent})
        self.csrf_token: Optional[str] = None

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params = dict(params)
        params.setdefault("format", "json")
        r = self.s.get(self.api_url, params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def _post(self, data: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(data)
        data.setdefault("format", "json")
        r = self.s.post(self.api_url, data=data, timeout=60)
        r.raise_for_status()
        return r.json()

    def login_bot(self) -> None:
        """
        Log in using a Bot Password (username looks like 'RealUser@BotName').
        Flow:
          1) Fetch login token (type=login)
          2) POST action=login with lgname, lgpassword, lgtoken
        """
        # Step 1: login token
        token_resp = self._get({
            "action": "query",
            "meta": "tokens",
            "type": "login",
        })
        login_token = token_resp["query"]["tokens"]["logintoken"]

        # Step 2: perform login
        login_resp = self._post({
            "action": "login",
            "lgname": self.user,
            "lgpassword": self.password,
            "lgtoken": login_token,
        })
        status = login_resp.get("login", {}).get("result")
        if status != "Success":
            raise RuntimeError(f"Login failed: {login_resp}")

    def ensure_csrf(self) -> str:
        if self.csrf_token:
            return self.csrf_token
        token_resp = self._get({
            "action": "query",
            "meta": "tokens",
            "type": "csrf",
        })
        self.csrf_token = token_resp["query"]["tokens"]["csrftoken"]
        return self.csrf_token

    def get_all_pages(self, namespace: int = 0, limit: int = 5000) -> List[str]:
        """
        Returns a list of page titles. Uses pagination via 'apcontinue'.
        """
        titles: List[str] = []
        apcontinue = None
        while True:
            params = {
                "action": "query",
                "list": "allpages",
                "apnamespace": namespace,
                "aplimit": min(limit, 5000),  # max per request
            }
            if apcontinue:
                params["apcontinue"] = apcontinue

            data = self._get(params)
            pages = data.get("query", {}).get("allpages", [])
            titles.extend([p["title"] for p in pages])

            apcontinue = data.get("continue", {}).get("apcontinue")
            if not apcontinue:
                break
        return titles

    def get_wikitext(self, title: str) -> str:
        """
        Fetch page wikitext using revisions API.
        Uses formatversion=2 and rvslots=main for modern MW.
        """
        data = self._get({
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "rvprop": "content",
            "rvslots": "main",
            "formatversion": "2",
        })
        pages = data.get("query", {}).get("pages", [])
        if not pages or "missing" in pages[0]:
            raise FileNotFoundError(f"Page not found: {title}")
        revs = pages[0].get("revisions", [])
        if not revs:
            return ""
        slots = revs[0].get("slots", {})
        return slots.get("main", {}).get("content", "")

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Anak Brain – MediaWiki bot utility")
    p.add_argument("--list", action="store_true", help="List all page titles")
    p.add_argument("--get", metavar="TITLE", help="Fetch wikitext for a page")
    p.add_argument("--edit", nargs=2, metavar=("TITLE", "FILE"), help="Replace page content with FILE contents")
    p.add_argument("--namespace", type=int, default=0, help="Namespace to list (default: 0)")
    p.add_argument("--limit", type=int, default=5000, help="Max pages per batch (default: 5000)")
    return p.parse_args()

def require_env():
    missing = []
    if not API_URL:
        missing.append("MW_API_URL")
    if not BOT_USER:
        missing.append("MW_BOT_USERNAME")
    if not BOT_PASS:
        missing.append("MW_BOT_PASSWORD")
    if missing:
        raise SystemExit("Missing environment variables: " + ", ".join(missing))

def mw_cleanText():
    pass

def main():
    require_env()
    client = MWClient(API_URL, BOT_USER, BOT_PASS)
    client.login_bot()

    args = parse_args()

    if args.list:
        titles = client.get_all_pages(namespace=args.namespace, limit=args.limit)
        print(json.dumps({"count": len(titles), "titles": titles}, ensure_ascii=False, indent=2))
        return

    if args.get:
        text = client.get_wikitext(args.get)
        print(text)
        return

    titles = client.get_all_pages()

    print(f"Fetched {len(titles)} titles:")
    for t in titles:
        print(" -", t)


    # Test page parsing
    curPage = titles[1]
    print("\nSample page fetch:", curPage)
    curPageContent = (client.get_wikitext(curPage))
    print(curPageContent)
    curPageContentClean = mw_cleanText(curPageContent)
    print(curPageContent)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)