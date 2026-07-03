from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, Any
from enum import Enum


# ── Enums ────────────────────────────────────────────────

class CaseType(str, Enum):
    CIVIL = "civil"
    CRIMINAL = "criminal"
    ADMINISTRATIVE = "administrative"
    COMMERCIAL = "commercial"
    LABOR = "labor"
    IP = "intellectual_property"


class PartyRole(str, Enum):
    PLAINTIFF = "plaintiff"
    DEFENDANT = "defendant"


class SimulationMode(str, Enum):
    ADVERSARIAL = "adversarial"
    FULL_TRIAL = "full_trial"
    WITNESS_EXAM = "witness_exam"
    ARGUMENT_ANALYSIS = "argument_analysis"


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


# ── User Models ──────────────────────────────────────────

class UserRegister(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)
    display_name: str = Field("", max_length=100)
    role: UserRole = Field(UserRole.USER)


class UserLogin(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str
    role: UserRole
    created_at: Any


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[UserRole] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo


# ── Case Models ──────────────────────────────────────────

class CaseCreate(BaseModel):
    title: str = Field(..., description="案件名称")
    case_type: CaseType = Field(..., description="案件类型")
    court_name: str = Field("", description="受理法院")
    our_role: PartyRole = Field(..., description="我方立场（原告/被告）")
    case_facts: str = Field(..., description="案件事实概要")
    our_claims: str = Field("", description="我方诉讼请求/答辩意见")
    our_evidence: str = Field("", description="我方证据清单及说明")
    our_legal_basis: str = Field("", description="我方法律依据")
    opposing_claims: str = Field("", description="对方已知诉讼请求/答辩意见")
    opposing_evidence: str = Field("", description="对方已知证据")
    opposing_legal_basis: str = Field("", description="对方已知法律依据")
    judge_tendencies: str = Field("", description="法官审判风格/倾向（如已知）")
    additional_context: str = Field("", description="其他补充信息")


class CaseUpdate(BaseModel):
    title: Optional[str] = None
    case_type: Optional[CaseType] = None
    court_name: Optional[str] = None
    our_role: Optional[PartyRole] = None
    case_facts: Optional[str] = None
    our_claims: Optional[str] = None
    our_evidence: Optional[str] = None
    our_legal_basis: Optional[str] = None
    opposing_claims: Optional[str] = None
    opposing_evidence: Optional[str] = None
    opposing_legal_basis: Optional[str] = None
    judge_tendencies: Optional[str] = None
    additional_context: Optional[str] = None


class CaseInfo(CaseCreate):
    id: int
    user_id: int
    created_at: Any


class DocumentRequest(BaseModel):
    doc_type: str = Field(..., description="文书类型")


class DocumentResponse(BaseModel):
    id: int
    case_id: int
    doc_type: str
    doc_title: str
    content: str
    created_at: Any


class SimulationRequest(BaseModel):
    case_id: int
    mode: SimulationMode
    user_message: str = Field(..., description="律师的发言/提问")
    session_id: Optional[str] = Field(None, description="会话ID，用于维持上下文")


class SimulationResponse(BaseModel):
    session_id: str
    role: str
    content: str
    analysis: Optional[str] = None


class AnalysisRequest(BaseModel):
    case_id: int
    focus: str = Field("comprehensive", description="分析重点")


class AnalysisResponse(BaseModel):
    analysis: str
    key_risks: list[str] = []
    recommendations: list[str] = []


# ── Backup Models ────────────────────────────────────────

class BackupInfo(BaseModel):
    filename: str
    size_bytes: int
    created_at: Any


class BackupSchedule(BaseModel):
    enabled: bool = True
    cron_hour: int = Field(2, ge=0, le=23)
    cron_minute: int = Field(0, ge=0, le=59)
    keep_count: int = Field(7, ge=1, le=100)
