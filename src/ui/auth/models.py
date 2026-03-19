from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

class Role(str, Enum):
    CA_STAFF = "CA_STAFF"
    ADMIN = "ADMIN"
    REVIEWER = "REVIEWER"

class User(BaseModel):
    uid: str
    email: str
    name: Optional[str] = None
    role: Role = Role.REVIEWER
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        # Ensure role is saved as string
        if "role" in data and isinstance(data["role"], Role):
            data["role"] = data["role"].value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        if "role" in data:
            data["role"] = Role(data["role"])
        return cls(**data)
