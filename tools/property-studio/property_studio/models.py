from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator


def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True, validate_assignment=True)


class Source(Record):
    id: str = Field(default_factory=uid)
    title: str
    url: str | None = None
    kind: Literal["listing", "public_record", "document", "user", "synthetic", "search"] = "user"
    retrieved_at: str = Field(default_factory=now)
    event_date: str | None = None
    feed: str | None = None
    sha256: str | None = None
    excerpt: str = ""
    artifact: str | None = None


class Property(Record):
    id: str = Field(default_factory=uid)
    address: str
    unit: str | None = None
    parcel: str | None = None
    association: str | None = None
    kind: str = "condo"
    facts: dict = Field(default_factory=dict)
    identity_status: Literal["user_confirmed", "resolved", "needs_review", "synthetic"] = "needs_review"


class Claim(Record):
    id: str = Field(default_factory=uid)
    property_id: str
    text: str
    kind: Literal["reported", "visual", "assumption", "calculated", "hypothesis"]
    source_ids: list[str] = Field(default_factory=list)
    media_ids: list[str] = Field(default_factory=list)
    status: Literal["supported", "needs_review", "conflicted", "rejected"] = "needs_review"
    limitation: str = ""


class Media(Record):
    id: str = Field(default_factory=uid)
    source_id: str
    filename: str
    sha256: str
    original_url: str | None = None
    permission: Literal["user_authorized", "review_required", "synthetic"] = "review_required"


class VisualCriterion(Record):
    criterion: str
    observation: str
    evidence: str


class PhotoAnalysis(Record):
    description: str
    room: str
    criteria: list[VisualCriterion]
    limitations: list[str]


class Observation(PhotoAnalysis):
    media_id: str
    provider: str = "cosmos"
    model: str = ""
    rubric_version: str = "1"
    reviewed: bool = False


class Comparable(Record):
    id: str = Field(default_factory=uid)
    address: str
    category: Literal["sale", "rent"]
    price: Decimal = Field(gt=0)
    price_type: Literal["current_ask", "historical_ask", "executed", "algorithmic", "scenario"]
    event_date: str | None = None
    status: str = "unknown"
    source_id: str
    feed: str | None = None
    beds: float | None = None
    baths: float | None = None
    sqft: float | None = None
    differences: list[str] = Field(default_factory=list)
    included: bool = False
    rationale: str = "Candidate only; verify identity, date and terms."
    concessions: Decimal | None = None
    lease_months: int | None = None
    distance_miles: float | None = None


class Assumptions(Record):
    purchase_price: Decimal | None = Field(default=None, gt=0, le=100_000_000)
    down_payment_pct: Decimal = Field(default=Decimal("0.2"), ge=0, le=1)
    annual_rate: Decimal | None = Field(default=None, ge=0, le=1)
    term_years: int = Field(default=30, ge=1, le=40)
    rent_monthly: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    vacancy_pct: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    other_income_monthly: Decimal = Field(default=0, ge=0)
    tax_annual: Decimal | None = Field(default=None, ge=0)
    insurance_annual: Decimal | None = Field(default=None, ge=0)
    hoa_monthly: Decimal | None = Field(default=None, ge=0)
    repairs_monthly: Decimal | None = Field(default=None, ge=0)
    management_pct: Decimal = Field(default=Decimal("0.08"), ge=0, le=1)
    utilities_monthly: Decimal | None = Field(default=None, ge=0)
    capex_monthly: Decimal | None = Field(default=None, ge=0)
    pmi_monthly: Decimal = Field(default=0, ge=0)
    points_pct: Decimal = Field(default=0, ge=0, le=1)
    closing_cost_pct: Decimal = Field(default=Decimal("0.03"), ge=0, le=1)
    assessment_upfront: Decimal = Field(default=0, ge=0)
    assessment_monthly: Decimal = Field(default=0, ge=0)
    assessment_months: int = Field(default=0, ge=0, le=480)
    holding_years: int = Field(default=5, ge=1, le=30)
    appreciation_pct: Decimal = Field(default=0, ge=Decimal("-0.5"), le=1)
    rent_growth_pct: Decimal = Field(default=0, ge=Decimal("-0.5"), le=1)
    expense_growth_pct: Decimal = Field(default=0, ge=Decimal("-0.5"), le=1)
    investment_return_pct: Decimal = Field(default=0, ge=Decimal("-0.5"), le=1)
    selling_cost_pct: Decimal = Field(default=Decimal("0.06"), ge=0, le=1)
    renter_insurance_monthly: Decimal = Field(default=0, ge=0)
    source_notes: dict[str, str] = Field(default_factory=dict)


class RunInput(Record):
    address: str = Field(default="", max_length=500)
    url: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=50)
    association: str | None = Field(default=None, max_length=200)
    confirm_identity: bool = True
    authorize_images: bool = True
    image_urls: list[str] = Field(default_factory=list, max_length=12)
    source_urls: list[str] = Field(default_factory=list, max_length=20)
    use_homeharvest: bool = True
    mode: Literal["live", "synthetic"] = "live"
    render_video: bool = True
    assumptions: Assumptions = Field(default_factory=Assumptions)

    @model_validator(mode="after")
    def identity_required(self):
        if self.address.strip().lower().startswith(("https://", "http://")):
            object.__setattr__(self,"url",self.address.strip())
            object.__setattr__(self,"address","")
        if self.mode == "live" and not (self.address.strip() or self.url):
            raise ValueError("Provide an address or a listing URL")
        return self


class Scene(Record):
    narration: str
    overlay: str = ""
    media_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    seconds: int = Field(default=10, ge=1, le=90)


class Story(Record):
    hooks: list[str]
    scenes: list[Scene]
    caption: str
    cta: str
    dm_reply: str
    provider: str = "template"
    state: Literal["draft", "reviewed"] = "draft"
    version: int = 1


class Run(Record):
    id: str = Field(default_factory=uid)
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    version: int = 1
    request: RunInput
    property: Property
    state: str = "pending"
    stages: dict[str, dict] = Field(default_factory=dict)
    sources: list[Source] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    media: list[Media] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    comparables: list[Comparable] = Field(default_factory=list)
    questions: list[dict[str, str]] = Field(default_factory=list)
    finance: dict = Field(default_factory=dict)
    story: Story | None = None
    audit: list[dict[str, str]] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
