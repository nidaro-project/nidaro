"""School domain: subjects, materialized lesson days, grades, homework per kid."""

from nidaro.school.repository import SchoolRepository
from nidaro.school.service import SchoolService

__all__ = ["SchoolRepository", "SchoolService"]
