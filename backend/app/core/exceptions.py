from fastapi import status


class AppException(Exception):
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "An unexpected error occurred"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


class NotFoundException(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Resource not found"


class UnauthorizedException(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Authentication required"


class ForbiddenException(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    detail = "Insufficient permissions"


class ConflictException(AppException):
    status_code = status.HTTP_409_CONFLICT
    detail = "Resource already exists"


class BadRequestException(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    detail = "Bad request"


class LLMException(AppException):
    """LLM provider returned an error response (e.g. rate-limit, invalid request)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    detail = "LLM provider error"


class LLMUnavailableException(LLMException):
    """LLM provider is unreachable or timed out."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detail = "LLM provider unavailable"
