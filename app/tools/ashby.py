"""Ashby ATS tools — fetch open roles from Ashby's public job board API.

No authentication required. Ashby exposes job data publicly.
Install: pip install httpx
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from langchain_core.tools import tool

from app.tools import register

logger = logging.getLogger(__name__)

# ── Ashby constants ──────────────────────────────────────────────────────────

_ASHBY_BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"
_TIMEOUT = 15.0
_ASHBY_JOB_URL_RE = re.compile(r"https?://jobs\.ashbyhq\.com/([^/\"'?#\s]+)")

_EMPLOYMENT_TYPE_LABELS = {
    "FullTime": "Full-time",
    "PartTime": "Part-time",
    "Contract": "Contract",
    "Intern": "Internship",
}


# ── Internal helpers (inlined from ashby_scraper.py) ────────────────────────


def _normalize_compensation(comp: Optional[dict]) -> Optional[dict]:
    if not comp:
        return None
    for tier in comp.get("compensationTiers") or []:
        for component in tier.get("components") or []:
            if component.get("compensationType") == "Salary":
                salary_min = component.get("minValue")
                salary_max = component.get("maxValue")
                if salary_min is None and salary_max is None:
                    continue
                return {
                    "salary_min": salary_min,
                    "salary_max": salary_max,
                    "currency": component.get("currencyCode"),
                }
    return None


def _normalize_job(raw: dict) -> dict:
    return {
        "title": raw.get("title", ""),
        "department": raw.get("departmentName", ""),
        "team": raw.get("teamName", ""),
        "employment_type": raw.get("employmentType", ""),
        "location": raw.get("location", ""),
        "is_remote": raw.get("isRemote", False),
        "compensation": _normalize_compensation(raw.get("compensation")),
        "description_plain": raw.get("descriptionPlain", ""),
        "job_url": raw.get("jobUrl", ""),
        "published_at": raw.get("publishedAt", ""),
    }


async def _fetch_ashby_jobs_raw(company_slug: str) -> dict:
    url = f"{_ASHBY_BASE_URL}/{company_slug}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params={"includeCompensation": "true"})
        resp.raise_for_status()
    data = resp.json()
    return [_normalize_job(j) for j in data.get("jobs", [])]


def _derive_ashby_slug(company_name: str) -> str:
    slug = company_name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


async def _resolve_ashby_slug_from_website(website_url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT) as client:
            resp = await client.get(website_url, headers={"User-Agent": "fabriq-bot/1.0"})
            resp.raise_for_status()
        m = _ASHBY_JOB_URL_RE.search(resp.text)
        return m.group(1) if m else None
    except Exception as e:
        logger.warning("Failed to resolve Ashby slug from %s: %s", website_url, e)
        return None


def _format_jobs(jobs: list[dict], slug: str) -> str:
    if not jobs:
        return f"No open roles found on Ashby board '{slug}'."

    lines = [f"Open roles on Ashby board '{slug}' ({len(jobs)} total):\n"]
    for i, job in enumerate(jobs, 1):
        emp = _EMPLOYMENT_TYPE_LABELS.get(job["employment_type"], job["employment_type"])
        loc = job["location"] or ("Remote" if job["is_remote"] else "Not specified")
        if job["is_remote"] and job["location"]:
            loc = f"{job['location']} (Remote)"
        comp_str = ""
        if job["compensation"]:
            c = job["compensation"]
            lo, hi, cur = c.get("salary_min"), c.get("salary_max"), c.get("currency", "USD")
            if lo and hi:
                comp_str = f" | {cur} {lo:,}–{hi:,}"
            elif lo:
                comp_str = f" | {cur} {lo:,}+"
        dept = f" [{job['department']}]" if job["department"] else ""
        lines.append(
            f"{i}. {job['title']}{dept}\n"
            f"   Type: {emp} | Location: {loc}{comp_str}\n"
            f"   URL: {job['job_url']}\n"
        )
    return "\n".join(lines)


# ── Tools ────────────────────────────────────────────────────────────────────


@register
@tool
async def ashby_fetch_jobs(company_slug: str) -> str:
    """Fetch all open job postings from a company's Ashby ATS board.

    Ashby is a popular Applicant Tracking System. Many startups post jobs there.
    Use ashby_resolve_slug first if you only have a company name.

    Args:
        company_slug: The Ashby board slug (e.g. "granola", "linear", "notion").
            This is the identifier in jobs.ashbyhq.com/{slug}.

    Returns:
        A formatted list of open roles with titles, types, locations,
        compensation (if available), and direct application URLs.
    """
    try:
        jobs = await _fetch_ashby_jobs_raw(company_slug)
        return _format_jobs(jobs, company_slug)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Company '{company_slug}' not found on Ashby (404). Try a different slug or check if they use Ashby."
        return f"Ashby API error for '{company_slug}': {e}"
    except Exception as e:
        logger.warning("ashby_fetch_jobs failed for %r: %s", company_slug, e)
        return f"Failed to fetch Ashby jobs for '{company_slug}': {e}"


@register
@tool
async def ashby_resolve_slug(company_name: str) -> str:
    """Derive or discover the Ashby job board slug for a company.

    First tries converting the company name directly to a slug (e.g.
    "Acme Corp" → "acme-corp"). If that 404s, tries to find the slug by
    fetching the company's website URL (if it looks like a URL) and scanning
    for jobs.ashbyhq.com links.

    Args:
        company_name: Company name (e.g. "Granola") OR a company website URL
            (e.g. "https://granola.so") to scan for the Ashby link.

    Returns:
        The resolved Ashby slug string, or an error message if not found.
    """
    # If it looks like a URL, scrape it directly for the slug
    if company_name.startswith("http://") or company_name.startswith("https://"):
        slug = await _resolve_ashby_slug_from_website(company_name)
        if slug:
            return slug
        return f"No Ashby job board link found on {company_name}."

    # Try the derived slug first via a quick probe
    derived = _derive_ashby_slug(company_name)
    try:
        url = f"{_ASHBY_BASE_URL}/{derived}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params={"includeCompensation": "false"})
        if resp.status_code == 200:
            return derived
        if resp.status_code != 404:
            resp.raise_for_status()
    except Exception as e:
        logger.warning("Slug probe failed for %r: %s", derived, e)

    return (
        f"Could not resolve an Ashby slug for '{company_name}'. "
        f"Tried slug '{derived}' — got 404. "
        f"Pass the company website URL to scan for jobs.ashbyhq.com links instead."
    )
