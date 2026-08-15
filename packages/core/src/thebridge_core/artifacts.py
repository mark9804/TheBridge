from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArtifactRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    uri: str
    revision: str | None = None
    required_paths: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_revision(self) -> ArtifactRequirement:
        scheme = urlparse(self.uri).scheme
        if scheme not in {"file", "modelscope"}:
            raise ValueError("artifact uri must use file:// or modelscope://")
        if scheme == "modelscope" and not self.revision:
            raise ValueError("modelscope artifacts require an immutable revision")
        return self


class ArtifactStore:
    def __init__(self, root: Path | None = None) -> None:
        configured = os.environ.get("THEBRIDGE_DATA_DIR")
        self.root = root or Path(configured or Path.home() / ".thebridge") / "artifacts"

    def resolve(self, requirement: ArtifactRequirement) -> Path:
        parsed = urlparse(requirement.uri)
        if parsed.scheme == "file":
            return Path(unquote(parsed.path)).expanduser()
        assert requirement.revision is not None
        return self.root / requirement.id / requirement.revision

    def missing(self, requirements: tuple[ArtifactRequirement, ...]) -> list[str]:
        missing: list[str] = []
        for requirement in requirements:
            base = self.resolve(requirement)
            expected = requirement.required_paths or (".",)
            for relative in expected:
                if not (base / relative).exists():
                    missing.append(f"{requirement.id}:{relative}")
        return missing
