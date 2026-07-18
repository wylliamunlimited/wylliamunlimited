"""Fill README.template.md placeholders with live GitHub stats.

Run by .github/workflows/readme.yml. Writes README.md.

Fails soft: if a stat can't be fetched, that placeholder is left showing
"n/a" and the rest of the README still renders. A broken API call should
never leave the profile blank.
"""

import os
import re
import sys
from datetime import date, datetime, timezone

import requests

USER = os.environ["GH_USER"]
TOKEN = os.environ["GH_TOKEN"]

API = "https://api.github.com"
GQL = "https://api.github.com/graphql"
HEAD = {"Authorization": f"bearer {TOKEN}", "Accept": "application/vnd.github+json"}


def account_created() -> date:
    r = requests.get(f"{API}/users/{USER}", headers=HEAD, timeout=30)
    r.raise_for_status()
    return datetime.fromisoformat(
        r.json()["created_at"].replace("Z", "+00:00")
    ).date()


def uptime() -> str:
    """Account age: today minus the GitHub account creation date."""
    start = account_created()
    t = date.today()
    y, m, d = t.year - start.year, t.month - start.month, t.day - start.day
    if d < 0:
        m -= 1
        d += (t.replace(day=1) - date.resolution).day
    if m < 0:
        y -= 1
        m += 12
    return f"{y} years, {m} months, {d} days"


def repo_count() -> str:
    """Count public repos the user owns, excluding forks."""
    count = 0
    page = 1
    while True:
        r = requests.get(
            f"{API}/users/{USER}/repos",
            headers=HEAD,
            params={"per_page": 100, "page": page, "type": "owner"},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        count += sum(1 for repo in batch if not repo["fork"])
        page += 1
    return f"{count:,}"


def lifetime_commits() -> str:
    """Sum commit contributions year by year.

    contributionsCollection accepts at most a one-year window, so we walk
    from account creation to now. restrictedContributionsCount covers
    private repos and requires a PAT plus "Include private contributions"
    enabled in GitHub profile settings.
    """
    meta = requests.get(f"{API}/users/{USER}", headers=HEAD, timeout=30)
    meta.raise_for_status()
    start_year = datetime.fromisoformat(
        meta.json()["created_at"].replace("Z", "+00:00")
    ).year
    now = datetime.now(timezone.utc)

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
    total = 0
    for yr in range(start_year, now.year + 1):
        frm = datetime(yr, 1, 1, tzinfo=timezone.utc)
        to = min(datetime(yr, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        res = requests.post(
            GQL,
            json={"query": q, "variables": {
                "user": USER, "from": frm.isoformat(), "to": to.isoformat()}},
            headers=HEAD,
            timeout=30,
        )
        res.raise_for_status()
        payload = res.json()
        if payload.get("errors"):
            raise RuntimeError(f"GraphQL: {payload['errors'][0].get('message')}")
        c = payload["data"]["user"]["contributionsCollection"]
        total += c["totalCommitContributions"] + c["restrictedContributionsCount"]
    return f"{total:,}"


def safe(name, fn):
    try:
        v = fn()
        print(f"  {name}: {v}")
        return v
    except Exception as exc:
        print(f"  {name}: FAILED ({exc})", file=sys.stderr)
        return "n/a"


def main() -> None:
    print(f"Rendering for user: {USER}")
    values = {
        "uptime": safe("uptime", uptime),
        "repos": safe("repos", repo_count),
        "commits": safe("commits", lifetime_commits),
        # Static, env-driven field (no API call). Set PAPER in the workflow.
        "paper": os.environ.get("PAPER", "n/a"),
    }

    tpl = open("README.template.md", encoding="utf-8").read()

    def sub(match: re.Match) -> str:
        key = match.group(1).strip().lower()
        if key not in values:
            return match.group(0)
        # pad to the placeholder's width so the ASCII columns stay aligned
        return values[key].ljust(len(match.group(0)))

    open("README.md", "w", encoding="utf-8").write(
        re.sub(r"\{\{\s*(\w+)\s*\}\}", sub, tpl)
    )
    print("Wrote README.md")


if __name__ == "__main__":
    main()