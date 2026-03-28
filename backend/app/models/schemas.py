from pydantic import BaseModel
from typing import Literal
from typing import Optional
from uuid import UUID
from datetime import datetime

LinkType = Literal["public_channel", "private_chat", "topic_thread", "invite_link"]

class ParseLinkRequest(BaseModel):
    url: str

class ParsedLinkResponse(BaseModel):
    original_url: str
    link_type: LinkType
    entity_ref: str
    msg_id: Optional[int] = None
    topic_id: Optional[int] = None
    invite_hash: Optional[str] = None

class SendCodeRequest(BaseModel):
    phone: str

class SendCodeResponse(BaseModel):
    phone_code_hash: str
    message: Optional[str] = None

class VerifyCodeRequest(BaseModel):
    phone: str
    code: str
    phone_code_hash: Optional[str] = None

class Verify2FARequest(BaseModel):
    phone: str
    password: str

class AuthStatusResponse(BaseModel):
    phone: str
    authenticated: bool
    message: str

class StartExtractionRequest(BaseModel):
    phone: str
    url: str

class StartExtractionResponse(BaseModel):
    job_id: UUID

class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    message_count: int
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class ExtractedMessageOut(BaseModel):
    id: int
    job_id: UUID
    message_id: int
    text: Optional[str]
    sender: Optional[str]
    sender_id: Optional[str]
    date: datetime
    reply_to_msg_id: Optional[int] = None
    media_path: Optional[str] = None
    is_transcribed: bool = False

class JobResultsResponse(BaseModel):
    job_id: UUID
    total: int
    messages: list[ExtractedMessageOut]


# ── Phase 4: Export & Categorization ─────────────────────────────────────────

ExportFormat = Literal["markdown", "txt"]

CategoryLabel = Literal[
    "lecture_notes",
    "past_exam",
    "solved_problems",
    "homework_assignment",
    "textbook_material",
    "summary_cheatsheet",
    "subject_media",
    "other",
]


class CategorizeRequest(BaseModel):
    job_id: UUID
    phone: str


class CategorizeResponse(BaseModel):
    job_id: UUID
    categories_written: int


class ExportRequest(BaseModel):
    job_id: UUID
    format: ExportFormat = "markdown"


class ExportResponse(BaseModel):
    job_id: UUID
    filename: str
    size_bytes: int


class DriveUploadRequest(BaseModel):
    job_id: UUID


class DriveUploadResponse(BaseModel):
    job_id: UUID
    drive_folder_id: str
    drive_link: str
