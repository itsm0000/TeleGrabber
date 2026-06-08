from pydantic import BaseModel
from typing import Literal, List
from typing import Optional
from datetime import date
from uuid import UUID
from datetime import datetime

LinkType = Literal["public_channel", "private_chat", "topic_thread", "invite_link"]

# ── Extraction Filter Types ────────────────────────────────────────────────

# Content type filters - what kinds of media to include
MediaType = Literal[
    "text", "image", "video", "document", "audio", "sticker", "gif", "poll"
]

# Keyword match mode
MatchMode = Literal["any", "all"]  # any = OR, all = AND


class ExtractionFilters(BaseModel):
    """Comprehensive filter options for extraction control."""

    # ── Time Scope ──────────────────────────────────────────────────────
    date_from: Optional[date] = None  # ISO date (YYYY-MM-DD)
    date_to: Optional[date] = None  # ISO date (YYYY-MM-DD)

    # ── Content Type ────────────────────────────────────────────────────
    # Which types of messages/media to include
    # Empty list or None = include all
    media_types: Optional[List[MediaType]] = None

    # ── File Extension Filter ───────────────────────────────────────────
    # Only include files with these extensions (case-insensitive)
    # Example: [".pdf", ".docx", ".pptx"]
    file_extensions: Optional[List[str]] = None

    # ── Sender Filter ───────────────────────────────────────────────────
    # Include only messages from these senders (usernames or IDs)
    senders: Optional[List[str]] = None
    # Exclude messages from these senders
    exclude_senders: Optional[List[str]] = None

    # ── Content Search ──────────────────────────────────────────────────
    # Filter by keywords in message text
    keywords: Optional[List[str]] = None
    # "any" = match if ANY keyword present (OR), "all" = match ALL keywords (AND)
    keywords_match: MatchMode = "any"

    # ── Hashtag Filter ──────────────────────────────────────────────────
    # Only messages containing these hashtags
    hashtags: Optional[List[str]] = None

    # ── Link Filter ─────────────────────────────────────────────────────
    # Only messages containing URLs
    has_links: Optional[bool] = None

    # ── Media Properties ────────────────────────────────────────────────
    # File size limits (in bytes)
    min_file_size: Optional[int] = None
    max_file_size: Optional[int] = None

    # Video duration limits (in seconds)
    min_video_duration: Optional[int] = None
    max_video_duration: Optional[int] = None

    # ── Message Properties ──────────────────────────────────────────────
    # Only messages with minimum view count
    min_views: Optional[int] = None

    # ── Limits ──────────────────────────────────────────────────────────
    # Maximum number of messages to extract
    max_messages: Optional[int] = None
    # Maximum number of media files to download
    max_media_count: Optional[int] = None
    # Maximum total size of downloaded media (in bytes)
    max_total_size: Optional[int] = None


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
    filters: Optional[ExtractionFilters] = None  # Comprehensive extraction filters
    # Keep max_messages for backward compatibility
    max_messages: Optional[int] = None


class StartExtractionResponse(BaseModel):
    job_id: UUID


class StopExtractionResponse(BaseModel):
    job_id: UUID
    status: str  # "stopped"
    message_count: int


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    message_count: int
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    max_messages: Optional[int] = None
    filters_json: Optional[dict] = None


class ExtractedMessageOut(BaseModel):
    id: UUID
    job_id: UUID
    message_id: int
    text: Optional[str]
    sender: Optional[str]
    sender_id: Optional[str]
    date: datetime
    reply_to_msg_id: Optional[int] = None
    media_path: Optional[str] = None
    media_type: Optional[str] = None
    has_media: Optional[bool] = False
    category: Optional[str] = None
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
