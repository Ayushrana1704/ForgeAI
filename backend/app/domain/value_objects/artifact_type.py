from enum import StrEnum


class ArtifactType(StrEnum):
    SOURCE_CODE = "source_code"
    TEST = "test"
    CONFIG = "config"
    DOCUMENTATION = "documentation"
    ARCHIVE = "archive"
