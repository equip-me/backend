from typing import Annotated

from dadata import Dadata
from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user
from app.organizations import service
from app.organizations.dependencies import get_dadata_client
from app.organizations.schemas import OrganizationCreate, OrganizationRead
from app.users.models import User

router = APIRouter()


@router.post("/organizations/", response_model=OrganizationRead)
async def create_organization(
    data: OrganizationCreate,
    user: Annotated[User, Depends(require_active_user)],
    dadata: Annotated[Dadata, Depends(get_dadata_client)],
) -> OrganizationRead:
    return await service.create_organization(data, user, dadata)
