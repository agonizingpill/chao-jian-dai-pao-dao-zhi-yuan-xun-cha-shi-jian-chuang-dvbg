from fastapi import APIRouter, Depends

from core.auth import actor, allow
from core.audit import record
from core.db import transaction
from core.records import scan
from domain import rework_batches_service as service
from domain.rework_batches_model import rework_batches
from domain.rework_batches_schemas import ReworkConfirm, ReworkPlan

router = APIRouter()


@router.get('/rework_batches')
def list_rework_batches(user=Depends(actor)):
    with transaction() as conn:
        return scan(conn, rework_batches)


@router.post('/lead_shifts/rework-plan')
def rework_plan(data: ReworkPlan, user=Depends(actor)):
    allow(user, ('operator', 'reviewer'))
    with transaction() as conn:
        return service.preview_plan(conn, user, data)


@router.post('/lead_shifts/rework-confirm')
def rework_confirm(data: ReworkConfirm, user=Depends(actor)):
    allow(user, ('operator', 'reviewer'))
    with transaction() as conn:
        output = service.confirm_rework(conn, user, data)
        record(conn, user, 'lead_shifts.rework_confirm')
        return output
