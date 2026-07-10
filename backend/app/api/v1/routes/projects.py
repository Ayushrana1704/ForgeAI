import dataclasses
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_current_user, get_project_service
from app.application.services.project_service import ProjectService
from app.domain.entities.user import User
from app.domain.value_objects.project_status import ProjectStatus
from app.schemas.common import MessageResponse
from app.schemas.project import (
    CreateProjectRequest,
    ProjectListResponse,
    ProjectResponse,
    UpdateProjectRequest,
)

router = APIRouter()


def _project_response(project) -> ProjectResponse:  # type: ignore[no-untyped-def]
    return ProjectResponse.model_validate(dataclasses.asdict(project))


@router.get("", response_model=ProjectListResponse, summary="List projects for the current user")
async def list_projects(
    status: ProjectStatus | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectListResponse:
    projects, total = await project_service.list_for_owner(
        current_user, status=status, offset=offset, limit=limit
    )
    return ProjectListResponse(
        items=[_project_response(p) for p in projects],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
)
async def create_project(
    body: CreateProjectRequest,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    project = await project_service.create(body, current_user)
    return _project_response(project)


@router.get("/{project_id}", response_model=ProjectResponse, summary="Get a project by ID")
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    project = await project_service.get_by_id(project_id, current_user)
    return _project_response(project)


@router.patch("/{project_id}", response_model=ProjectResponse, summary="Partially update a project")
async def update_project(
    project_id: UUID,
    body: UpdateProjectRequest,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    project = await project_service.update(project_id, body, current_user)
    return _project_response(project)


@router.delete(
    "/{project_id}",
    response_model=MessageResponse,
    summary="Delete a project",
)
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> MessageResponse:
    await project_service.delete(project_id, current_user)
    return MessageResponse(message="Project deleted successfully")
