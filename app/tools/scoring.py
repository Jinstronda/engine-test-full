"""Candidate scoring tool — structures a job vs. candidate comparison.

This tool formats the inputs into a clear comparison scaffold that the
calling agent's LLM evaluates. No nested LLM calls — pure formatting.
"""

from __future__ import annotations

from langchain_core.tools import tool

from app.tools import register


@register
@tool
def score_candidate(job_summary: str, candidate_summary: str) -> str:
    """Structure a job description and candidate profile for fit evaluation.

    Formats both inputs side-by-side so the agent can reason about match
    quality, identify gaps, and produce a score with clear justification.
    Call this once per role you want to evaluate the candidate against.

    Args:
        job_summary: A summary of the open role — title, required skills,
            location/remote, compensation, team context, etc. Can be the
            raw output from ashby_fetch_jobs or a curated excerpt.
        candidate_summary: A summary of the candidate — work history,
            skills, education, location, seniority level. Can come from
            linkedin_profile or parse_document output.

    Returns:
        A structured comparison block. Evaluate it to produce:
        - An overall fit score (1–10)
        - A list of matching strengths
        - A list of gaps or concerns
        - A one-paragraph recommendation
    """
    divider = "─" * 60
    return (
        f"CANDIDATE FIT EVALUATION\n"
        f"{divider}\n\n"
        f"JOB REQUIREMENTS\n"
        f"{divider}\n"
        f"{job_summary.strip()}\n\n"
        f"{divider}\n\n"
        f"CANDIDATE PROFILE\n"
        f"{divider}\n"
        f"{candidate_summary.strip()}\n\n"
        f"{divider}\n\n"
        f"EVALUATION INSTRUCTIONS\n"
        f"Using the job requirements and candidate profile above, provide:\n"
        f"1. Fit Score: X/10\n"
        f"2. Strengths: bullet list of matching qualifications\n"
        f"3. Gaps: bullet list of missing or weak areas\n"
        f"4. Recommendation: one paragraph summary\n"
    )
