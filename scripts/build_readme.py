"""Fill README.template.md placeholders with live GitHub stats.

Run by .github/workflows/readme.yml. Writes README.md.
Placeholders are padded to the same visual width they replace so the
two-column ASCII layout never shifts.
"""

import os
import re
from datetime import date, datetime, timezone

import requests

USER = os.environ["GH_USER"]
TOKEN = os.environ["GH_TOKEN"]
START = datetime.fromisoformat(os.environ.get("START_DATE", "2000-01-01")).date()

API = "https://api.github.com"
GQL = "https://api.github.com/graphql"
HEAD = {"Authorization": f"bearer {TOKEN}", "Accept": "application/vnd.github+json"}


def uptime() -> str:
    """Human 'N years, N months, N days' since START."""
    t = date.today()
    y = t.year - START.year
    m = t.month - START.month
    d = t.day - START.day
    if d < 0:
        m -= 1
        prev = (t.replace(day=1) - date.resolution)
        d += prev.day
    if m < 0:
        y -= 1
        m += 12
    return f"{y} years, {m} months, {d} days"


def repo_count() -> int:
    """Public repos owned by USER."""
    r = requests.get(f"{API}/users/{USER}", headers=HEAD, timeout=30)
    r.raise_for_status()
    return r.json()["public_repos"]


def lifetime_commits() -> int:
    """Total commit contributions.

    contributionsCollection accepts at most a one-year window, so we walk
    year by year from account creation to now and sum.
    """
    created = requests.get(f"{API}/users/{USER}", headers=HEAD, timeout=30).json()["created_at"]
    start_year = datetime.fromisoformat(created.replace("Z", "+00:00")).year
    now = datetime.now(timezone.utc)
    total = 0

    q = """
    query($user:String!, $from:DateTime!, $to:DateTime!) {
      user(login:$user) {
        contributionsCollection(from:$from, to:$to) {
          totalCommitContributions
          restrictedContributionsCount
        }
      }
    }
    """
    for yr in range(start_year, now.year + 1):
        frm = datetime(yr, 1, 1, tzinfo=timezone.utc)
        to = min(datetime(yr, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        res = requests.post(
            GQL,
            json={"query": q, "variables": {
                "user": USER,
                "from": frm.isoformat(),
                "to": to.isoformat(),
            }},
            headers=HEAD,
            timeout=30,
        )
        res.raise_for_status()
        c = res.json()["data"]["user"]["contributionsCollection"]
        total += c["totalCommitContributions"] + c["restrictedContributionsCount"]
    return total


def main() -> None:
    values = {
        "uptime": uptime(),
        "repos": f"{repo_count():,}",
        "commits": f"{lifetime_commits():,}",
    }

    tpl = open("README.template.md", encoding="utf-8").read()

    # Replace each {{ key }} and pad so the right column keeps its width.
    def sub(match: re.Match) -> str:
        key = match.group(1).strip().lower()
        if key not in values:
            return match.group(0)
        return values[key].ljust(len(match.group(0)))

    out = re.sub(r"\{\{\s*(\w+)\s*\}\}", sub, tpl)
    open("README.md", "w", encoding="utf-8").write(out)


if __name__ == "__main__":
    main()