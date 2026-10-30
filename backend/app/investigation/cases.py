from fastapi import APIRouter, Depends

from app.security import Principal, get_principal
from .common import connect, json_safe, require_case

router = APIRouter(prefix='/api/cases', tags=['cases'])


@router.get('')
def cases(principal: Principal = Depends(get_principal)):
    with connect() as conn:
        if principal.is_admin:
            rows = conn.execute('SELECT * FROM inv.cases ORDER BY case_id').fetchall()
        else:
            rows = conn.execute('''SELECT c.* FROM inv.cases c JOIN inv.case_members m
                ON m.case_id=c.case_id WHERE m.user_id=%s ORDER BY c.case_id''', (principal.user_id,)).fetchall()
    return json_safe(rows)


@router.get('/{case_id}')
def case(case_id: str):
    return json_safe(require_case(case_id))
