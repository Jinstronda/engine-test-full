"""Agent type registry — hardcoded agent type definitions.

The only place where models and tool assignments are defined.
Agent instances in config.yaml reference these types by name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import SystemAgentRef


@dataclass
class AgentTypeDefinition:
    name: str
    description: str
    model: str
    tools: list[str] = field(default_factory=list)


AGENT_TYPE_REGISTRY: dict[str, AgentTypeDefinition] = {
    "researcher": AgentTypeDefinition(
        name="researcher",
        description="Expert at web research and data analysis.",
        model="claude-sonnet-4-20250514",
        tools=[
            "tavily_search",        # real-time web search
            "ashby_fetch_jobs",     # fetch open roles from Ashby ATS
            "ashby_resolve_slug",   # resolve company name → Ashby slug
            "linkedin_company",     # scrape company LinkedIn profile
            "linkedin_employees",   # search current employees at a company
            "parse_document",       # read PDFs, DOCX, URLs
        ],
    ),
    "coder": AgentTypeDefinition(
        name="coder",
        description="Senior software engineer and architect.",
        model="claude-sonnet-4-20250514",
        tools=[
            "calculate",        # evaluate math expressions
            "parse_document",   # read specs, READMEs, or technical docs
        ],
    ),
    "writer": AgentTypeDefinition(
        name="writer",
        description="Creative writer for marketing and content.",
        model="claude-sonnet-4-20250514",
        tools=[
            "parse_document",   # ingest reference material before writing
        ],
    ),
    "analyst": AgentTypeDefinition(
        name="analyst",
        description="Business analyst specialising in structured reasoning.",
        model="claude-sonnet-4-20250514",
        tools=[
            "calculate",        # evaluate math expressions
            "tavily_search",    # real-time web search for market context
            "score_candidate",  # structured job-vs-candidate fit evaluation
            "parse_document",   # ingest reports, CVs, or job descriptions
        ],
    ),
    "validator": AgentTypeDefinition(
        name="validator",
        description="Reviews pipeline output and accepts or rejects it.",
        model="claude-sonnet-4-20250514",
        tools=["accept_output", "reject_output"],
    ),
    "sourcer": AgentTypeDefinition(
        name="sourcer",
        description="Finds and profiles candidates on LinkedIn for a given role.",
        model="claude-sonnet-4-20250514",
        tools=[
            "tavily_search",        # discover candidate profiles and backgrounds
            "linkedin_employees",   # list current employees at a target company
            "linkedin_profile",     # scrape a specific LinkedIn profile
        ],
    ),
    "screener": AgentTypeDefinition(
        name="screener",
        description="Parses resumes and scores candidates against a job description.",
        model="claude-sonnet-4-20250514",
        tools=[
            "parse_document",   # extract text from a resume (PDF/DOCX/URL)
            "score_candidate",  # structured job-vs-candidate fit evaluation
        ],
    ),
    "recruiter": AgentTypeDefinition(
        name="recruiter",
        description="End-to-end recruiting coordinator — discovers roles, sources, and scores candidates.",
        model="claude-sonnet-4-20250514",
        tools=[
            "ashby_resolve_slug",   # resolve company name → Ashby slug
            "ashby_fetch_jobs",     # list open roles from Ashby ATS
            "linkedin_company",     # research the hiring company
            "linkedin_employees",   # find current employees / org context
            "linkedin_profile",     # deep-dive on a specific candidate
            "score_candidate",      # evaluate candidate fit against a role
        ],
    ),
    "notifier": AgentTypeDefinition(
        name="notifier",
        description="Sends notifications via email (Resend) or Telegram based on the requested channel.",
        model="claude-sonnet-4-20250514",
        tools=[
            "send_email",              # send transactional email via Resend
            "send_telegram_message",   # send a message via Telegram Bot API
        ],
    ),
    "payments": AgentTypeDefinition(
        name="payments",
        description="Handles Stripe payments, customers, invoices, and subscriptions.",
        model="claude-sonnet-4-20250514",
        tools=[
            "stripe_create_payment_intent",
            "stripe_create_customer",
            "stripe_get_customer",
            "stripe_list_charges",
            "stripe_create_invoice",
            "stripe_create_subscription",
        ],
    ),
}


@dataclass
class ResolvedAgent:
    name: str        # auto-generated: "{type}_{index}" e.g. "researcher_0"
    type: str
    description: str
    model: str
    tools: list[str]
    prompt: str      # the instance-level system prompt from config


def resolve_agent_type(type_name: str) -> AgentTypeDefinition:
    """Look up an agent type by name. Raises ValueError if not found."""
    if type_name not in AGENT_TYPE_REGISTRY:
        raise ValueError(
            f"Unknown agent type '{type_name}'. "
            f"Available types: {list(AGENT_TYPE_REGISTRY.keys())}"
        )
    return AGENT_TYPE_REGISTRY[type_name]


def merge_agent(ref: SystemAgentRef, index: int) -> ResolvedAgent:
    """Merge a config agent reference with its type definition.

    Generates the agent name as "{type}_{index}".
    """
    typedef = resolve_agent_type(ref.type)
    return ResolvedAgent(
        name=f"{ref.type}_{index}",
        type=ref.type,
        description=typedef.description,
        model=typedef.model,
        tools=typedef.tools,
        prompt=ref.prompt,
    )
