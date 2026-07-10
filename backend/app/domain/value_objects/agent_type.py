from enum import StrEnum


class AgentType(StrEnum):
    REQUIREMENTS_ANALYST = "requirements_analyst"
    ARCHITECT = "architect"
    TASK_PLANNER = "task_planner"
    DATABASE_DESIGNER = "database_designer"
    BACKEND_GENERATOR = "backend_generator"
    FRONTEND_GENERATOR = "frontend_generator"
    CODE_GENERATOR = "code_generator"
    TEST_WRITER = "test_writer"
    REVIEWER = "reviewer"
    REFINER = "refiner"
    ARTIFACT_PACKAGER = "artifact_packager"
    DOC_WRITER = "doc_writer"
