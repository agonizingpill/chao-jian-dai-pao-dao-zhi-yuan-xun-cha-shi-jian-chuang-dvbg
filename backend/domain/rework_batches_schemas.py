from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class ReworkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class ReworkConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    route: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    request_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
