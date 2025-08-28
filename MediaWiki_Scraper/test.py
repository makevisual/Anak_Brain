
import os
import sys
import json
import argparse
from typing import Dict, Any, List, Optional
import requests
import mwparserfromhell

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

def mw_cleanText(text: str) -> str:
    """
    Convert MediaWiki wikitext to a human-readable plain text.

    Strategy:
    - If mwparserfromhell is available, parse and use strip_code(normalize=True, collapse=True)
      which removes markup, templates, links, emphasis, etc.
    - Remove common control magic words (__TOC__, __NOEDITSECTION__, etc.).
    - Strip <ref>...</ref> footnotes and {{cite ...}} remnants that may linger.
    - Fallback: very light regex cleanup if mwparserfromhell is not installed.
    """
    import re
    try:
        import mwparserfromhell as mwp
    except ImportError:
        mwp = None

    # Remove common magic words
    magic_words = [
        "__TOC__", "__NOTOC__", "__NOEDITSECTION__", "__FORCETOC__", "__NEWSECTIONLINK__",
    ]
    for w in magic_words:
        text = text.replace(w, "")

    # Strip references
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<references\s*/?>", "", text, flags=re.IGNORECASE)

    if mwp is not None:
        try:
            code = mwp.parse(text)
            cleaned = code.strip_code(normalize=True, collapse=True)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
            return cleaned
        except Exception:
            pass

    # Fallback cleanup if mwparserfromhell not installed
    text = re.sub(r"'''(.*?)'''", r"\1", text)  # bold
    text = re.sub(r"''(.*?)''", r"\1", text)    # italics
    text = re.sub(r"^=+\s*(.*?)\s*=+$", r"\1\n" + "-"*40, text, flags=re.MULTILINE)  # headings
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", text)  # links [[A|B]] -> B
    text = re.sub(r"{{[^{}]+}}", "", text)      # simple templates
    text = re.sub(r"<[^>]+>", "", text)         # HTML tags
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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

    # Print all the pages
#    print(f"Fetched {len(titles)} titles:")
#    for t in titles:
#        print(" -", t)


    ######## Test page parsing ########
    curPage = titles[1]
    print("\n ============ Sample page fetch:", curPage)
    curPageContent = (client.get_wikitext(curPage))
    print(curPageContent)



curText = "Rendering After Effects projects through Deadline is essential for optimizing workflow efficiency and meeting production deadlines in collaborative environments. Deadline, a powerful render management tool, allows for distributed rendering across multiple machines, significantly reducing render times. This not only ensures consistent output quality but also frees up workstations for other tasks, improving overall productivity. By automating the rendering process and offering features like error logging and priority management, Deadline minimizes human error and ensures a seamless pipeline, making it an invaluable asset for motion design and animation professionals.


Before we begin, please read [[Introduction to Deadline]].

= MAKE Priority Basics =
2D / Compositing Job Defaults are automatically set to 95. They're fast frames and they take priority over everything else due to how fast they will be finished. No other renders on the farm should pass 95, and probably never pass 90.

= Preparing After Effects Sequences for Deadline =
# Select the comp within the After Effects file you wish to render, and slide it into the 'Render Queue'.
# Select the blue highlighted portion of the 'Output Module'. The 'Output Module Settings' window should appear.
# Set the 'Output Module Settings' to your liking. Once the settings are to your liking, select the 'OK' button. (An example is provided. View Example A image.)
# Select the blue highlighted portion of the 'Output To' labeled as 'Not Yet Specified'. The 'Output Movie To' window should appear.
# Copy and paste the path of the folder you wish to render to into the 'Output Movie To' window. And make sure that the naming convention is correct. (An example is provided. View Example B image.)

[[File:Output Module Settings Deadline Window IMG.png|thumb|311x311px|Ex. A: 'Output Module Settings' Window]]

[[File:Output Movie To Deadline Window IMG.png|thumb|Ex. B: 'Output Movie To' Window]]



















= Submitting After Effects Sequences to Deadline =

# Click 'File'
# Scroll down to 'Scripts'
# Select "DeadlineAfterEffectsClient.jsx". The 'Submit After Effects to Deadline' window should appear. (An example is provided. View Example C image.)
# Once the settings are to your liking, select the 'Submit' button.
# A 'Script Alert' window will pop up. Select the 'Yes' button.
# You can now open Deadline and view your job.[[File:Submit Affter Effects To Deadline Window IMG.png|thumb|Ex. C: 'Submit After Effects To Deadline' Window]] 

= Watch Your Jobs for Problems =
Once you've submitted a job check in on it. Watch for errors, make sure things aren't taking longer than they should, and check frames to see if something is wrong. Basically: try not to waste farm time with broken renders. If you see something wrong, pause or remove the job from the farm and check it so other renders can make it through.

= Clean Up =
Occasionally open up all of the filters on deadline and check if you have a bunch of completed or failed jobs on the farm and delete them. It's up to all of us to keep deadline tidy!"



if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)