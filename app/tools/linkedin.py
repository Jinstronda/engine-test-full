"""LinkedIn tools via Apify actors (no LinkedIn cookies required).

Actors used:
  - dev_fusion/linkedin-company-scraper  (company profiles)
  - harvestapi/linkedin-profile-search   (employee search + profile lookup)

Requires: APIFY_API_TOKEN environment variable.
Install:  pip install apify-client
"""

from __future__ import annotations

import logging
import os

from langchain_core.tools import tool

from app.tools import register

logger = logging.getLogger(__name__)

_COMPANY_ACTOR = "dev_fusion/linkedin-company-scraper"
_SEARCH_ACTOR = "harvestapi/linkedin-profile-search"

_ACTOR_TIMEOUT_SECS = 120
_ACTOR_MEMORY_MBYTES = 512
_ACTOR_WAIT_SECS = 130


# ── Internal helpers ─────────────────────────────────────────────────────────


def _get_apify_client():
    from apify_client import ApifyClientAsync

    token = os.environ.get("APIFY_API_TOKEN", "")
    if not token:
        raise RuntimeError("APIFY_API_TOKEN environment variable is not set.")
    return ApifyClientAsync(
        token=token,
        max_retries=3,
        min_delay_between_retries_millis=1000,
        timeout_secs=30,
    )


async def _run_actor(client, actor_id: str, run_input: dict) -> list[dict]:
    run = await client.actor(actor_id).call(
        run_input=run_input,
        timeout_secs=_ACTOR_TIMEOUT_SECS,
        memory_mbytes=_ACTOR_MEMORY_MBYTES,
        wait_secs=_ACTOR_WAIT_SECS,
    )
    items = []
    async for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        items.append(item)
    return items


def _format_company(data: dict) -> str:
    name = data.get("companyName") or data.get("name", "Unknown")
    industry = data.get("industry", "")
    employees = data.get("employeeCount") or data.get("employeeCountRange", "")
    hq = data.get("headquarter") or ""
    if isinstance(hq, dict):
        parts = [hq.get("city"), hq.get("country")]
        hq = ", ".join(p for p in parts if p)
    website = data.get("websiteUrl", "")
    tagline = data.get("tagline", "")
    description = (data.get("description") or "")[:600]
    founded = data.get("foundedOn", "")
    followers = data.get("followerCount", "")
    lines = [f"Company: {name}"]
    if industry:
        lines.append(f"Industry: {industry}")
    if employees:
        lines.append(f"Employees: {employees}")
    if hq:
        lines.append(f"HQ: {hq}")
    if website:
        lines.append(f"Website: {website}")
    if founded:
        lines.append(f"Founded: {founded}")
    if followers:
        lines.append(f"Followers: {followers:,}" if isinstance(followers, int) else f"Followers: {followers}")
    if tagline:
        lines.append(f"Tagline: {tagline}")
    if description:
        lines.append(f"\nDescription:\n{description}")
    return "\n".join(lines)


def _format_profile(data: dict) -> str:
    name = data.get("name") or data.get("fullName", "Unknown")
    headline = data.get("headline", "")
    location = data.get("location", "")
    summary = (data.get("summary") or "")[:400]

    lines = [f"Name: {name}"]
    if headline:
        lines.append(f"Headline: {headline}")
    if location:
        lines.append(f"Location: {location}")

    # Positions
    positions = data.get("positions") or data.get("experience") or []
    if positions:
        lines.append("\nExperience:")
        for p in positions[:5]:
            title = p.get("title", "")
            company = p.get("companyName") or p.get("company", "")
            start = p.get("startEndDate", {}).get("start", {})
            end = p.get("startEndDate", {}).get("end", {})
            start_str = f"{start.get('year', '')}" if start else ""
            end_str = f"{end.get('year', '')}" if end else "Present"
            period = f"{start_str}–{end_str}" if start_str else ""
            lines.append(f"  • {title} @ {company}" + (f" ({period})" if period else ""))

    # Education
    education = data.get("education") or []
    if education:
        lines.append("\nEducation:")
        for e in education[:3]:
            school = e.get("schoolName") or e.get("school", "")
            degree = e.get("degreeName") or e.get("degree", "")
            field = e.get("fieldOfStudy", "")
            lines.append(f"  • {school}" + (f" — {degree}" if degree else "") + (f", {field}" if field else ""))

    # Skills
    skills = data.get("skills") or []
    if skills:
        skill_names = [s.get("name", s) if isinstance(s, dict) else str(s) for s in skills[:15]]
        lines.append(f"\nSkills: {', '.join(skill_names)}")

    if summary:
        lines.append(f"\nSummary:\n{summary}")

    return "\n".join(lines)


# ── Tools ────────────────────────────────────────────────────────────────────


@register
@tool
async def linkedin_company(company_name: str) -> str:
    """Scrape a company's LinkedIn profile to get size, HQ, industry, and description.

    Uses Apify — no LinkedIn cookies needed.

    Args:
        company_name: Company name (e.g. "Granola") or a full LinkedIn company
            URL (e.g. "https://www.linkedin.com/company/granola-hq/").

    Returns:
        Formatted company profile: name, industry, headcount, HQ, website,
        tagline, and description.
    """
    try:
        client = _get_apify_client()
    except RuntimeError as e:
        return str(e)

    try:
        if company_name.startswith("https://"):
            url = company_name
        else:
            slug = company_name.lower().replace(" ", "-")
            url = f"https://www.linkedin.com/company/{slug}/"

        items = await _run_actor(client, _COMPANY_ACTOR, {"profileUrls": [url]})
        if not items:
            return f"No LinkedIn company data found for '{company_name}'."
        return _format_company(items[0])
    except Exception as e:
        logger.warning("linkedin_company failed for %r: %s", company_name, e)
        return f"LinkedIn company scrape failed for '{company_name}': {e}"


@register
@tool
async def linkedin_employees(company_name: str) -> str:
    """Search for current employees of a company on LinkedIn.

    Returns up to 10 current employees with their names and headlines.
    Uses Apify — no LinkedIn cookies needed.

    Args:
        company_name: The company name to search for (e.g. "Granola").

    Returns:
        A numbered list of current employees with name, headline, and
        LinkedIn URL where available.
    """
    try:
        client = _get_apify_client()
    except RuntimeError as e:
        return str(e)

    try:
        run_input = {
            "searchQuery": f"current employees at {company_name}",
            "maxItems": 10,
        }
        items = await _run_actor(client, _SEARCH_ACTOR, run_input)
        if not items:
            return f"No current employees found for '{company_name}'."

        lines = [f"Current employees at {company_name} ({len(items)} results):\n"]
        for i, person in enumerate(items, 1):
            name = person.get("name") or person.get("fullName", "Unknown")
            headline = person.get("headline", "")
            profile_url = person.get("profileUrl") or person.get("linkedinUrl", "")
            lines.append(
                f"{i}. {name}"
                + (f" — {headline}" if headline else "")
                + (f"\n   {profile_url}" if profile_url else "")
            )
        return "\n".join(lines)
    except Exception as e:
        logger.warning("linkedin_employees failed for %r: %s", company_name, e)
        return f"LinkedIn employee search failed for '{company_name}': {e}"


@register
@tool
async def linkedin_profile(profile_url: str) -> str:
    """Scrape a LinkedIn profile by URL to get work history, education, and skills.

    Uses Apify — no LinkedIn cookies needed.

    Args:
        profile_url: Full LinkedIn profile URL
            (e.g. "https://www.linkedin.com/in/johndoe/").

    Returns:
        Formatted profile: name, headline, experience, education, skills,
        and summary.
    """
    try:
        client = _get_apify_client()
    except RuntimeError as e:
        return str(e)

    try:
        run_input = {"searchQuery": profile_url, "maxItems": 1}
        items = await _run_actor(client, _SEARCH_ACTOR, run_input)
        if not items:
            return f"No profile data found for '{profile_url}'."
        return _format_profile(items[0])
    except Exception as e:
        logger.warning("linkedin_profile failed for %r: %s", profile_url, e)
        return f"LinkedIn profile scrape failed for '{profile_url}': {e}"
