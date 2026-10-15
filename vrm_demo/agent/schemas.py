"""All tool and HTTP inputs are allow-listed and reject unknown fields."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

ID_PATTERN = r"^[0-9a-f]{32}$"

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class ChatInput(StrictModel):
    text: str = Field(min_length=1, max_length=500)
    request_id: str = Field(pattern=ID_PATTERN)
    new_task: bool = False
    avatar_id: str | None = Field(default=None, max_length=255)
    voice_gender: Literal["auto", "male", "female"] = "auto"

class DecisionInput(StrictModel):
    request_id: str = Field(pattern=ID_PATTERN)
    proposal_id: str = Field(pattern=ID_PATTERN)
    confirmation_token: str = Field(min_length=32, max_length=128)
    decision: Literal["approve", "reject"]
    avatar_id: str | None = Field(default=None, max_length=255)
    voice_gender: Literal["auto", "male", "female"] = "auto"

class EmptyArgs(StrictModel):
    pass

class SlotArgs(StrictModel):
    department: str = Field(min_length=1, max_length=50)
    service_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    period: Literal["any", "morning", "afternoon"] = "any"

class RecordArgs(StrictModel):
    keyword: Literal["血压", "血糖"] | None = None

class KnowledgeArgs(StrictModel):
    query: str = Field(min_length=1, max_length=200)

class PrepareArgs(StrictModel):
    schedule_id: str = Field(min_length=1, max_length=120)
