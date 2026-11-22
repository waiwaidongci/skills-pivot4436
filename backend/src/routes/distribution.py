from datetime import UTC, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import connection
from src.config.settings import ARTIFACTS
from src.constants.enums import Role
from src.controllers.auth import allow, current
from src.domain.spec import SPEC
from src.models.identity import User
from src.models.jobs import Delivery, DeliveryPackage, Partner, Publication, Schedule
from src.models.source import Dataset
from src.schemas.requests import ClaimRequest, ConfirmRequest, PartnerRequest, ScheduleRequest
from src.services.audit import record
from src.services.delivery import (PackageConflict, PackageMissing, PartnerMissing, claim, confirm,
                                   create_partner, latest_version, pending_for)
from src.services.validation import normalize_params
from src.utils import views
from src.utils.time import iso, now
from src.utils.wakeup import wake

router = APIRouter()


@router.get('/schedules')
def schedules(db: Session = Depends(connection), actor: User = Depends(current)):
    return [views.schedule(item) for item in db.scalars(select(Schedule).order_by(Schedule.id.desc()).limit(100))]


@router.post('/schedules', status_code=201)
def add(body: ScheduleRequest, db: Session = Depends(connection), actor: User = Depends(allow(Role.ADMIN))):
    if not db.get(Dataset, body.dataset_id):
        raise HTTPException(404, '找不到指定的数据批次')
    if body.first_at.utcoffset() is None:
        raise ValueError('首次运行时间需要明确时区')
    first = body.first_at.astimezone(UTC).replace(tzinfo=None)
    stamp = now()
    if first < stamp - timedelta(seconds=30) or first > stamp + timedelta(days=366):
        raise ValueError('请选择从现在起一年内的首次运行时间')
    item = Schedule(dataset_id=body.dataset_id, params=normalize_params(body.params), name=body.name,
                    recipient=body.recipient, next_at=first, repeat_daily=body.repeat_daily, author=actor.username)
    db.add(item)
    db.flush()
    record(db, actor.username, 'schedule.created', item.id, recipient=item.recipient)
    db.commit()
    wake()
    return views.schedule(item)


@router.post('/schedules/{schedule_id}/disable')
def disable(schedule_id: int, db: Session = Depends(connection), actor: User = Depends(allow(Role.ADMIN))):
    item = db.get(Schedule, schedule_id, with_for_update=True)
    if not item:
        raise HTTPException(404, '找不到该分发计划')
    if item.enabled:
        item.enabled = False
        record(db, actor.username, 'schedule.disabled', item.id)
        db.commit()
    return views.schedule(item)


@router.get('/deliveries')
def outbox(db: Session = Depends(connection), actor: User = Depends(current)):
    return [views.delivery(item) for item in db.scalars(select(Delivery).order_by(Delivery.id.desc()).limit(100))]


@router.get('/publications')
def publications(db: Session = Depends(connection), actor: User = Depends(current)):
    return [{'version': item.version, 'run_id': item.run_id, 'period': item.snapshot.get('period'),
             'headline': item.snapshot.get('headline'), 'created_at': iso(item.created_at)}
            for item in db.scalars(select(Publication).order_by(Publication.version.desc()).limit(100))]


@router.get('/partners')
def partners(db: Session = Depends(connection), actor: User = Depends(current)):
    target = latest_version(db)
    return [views.partner(item.name, item.confirmed_version, target.version if target else None,
                          pending_for(db, item.name))
            for item in db.scalars(select(Partner).order_by(Partner.name))]


@router.post('/partners', status_code=201)
def register_partner(body: PartnerRequest, db: Session = Depends(connection),
                     actor: User = Depends(allow(Role.ADMIN))):
    item, created = create_partner(db, body.name.strip())
    if created:
        record(db, actor.username, 'partner.created', item.name)
    db.commit()
    target = latest_version(db)
    return views.partner(item.name, item.confirmed_version, target.version if target else None, None)


@router.post('/claims')
def claim_package(body: ClaimRequest, db: Session = Depends(connection),
                  actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    try:
        item, created = claim(db, body.name.strip())
    except PartnerMissing:
        raise HTTPException(404, '找不到该合作方') from None
    except PackageConflict as error:
        raise HTTPException(409, str(error)) from None
    if item is None:
        partner = db.get(Partner, body.name.strip())
        target = latest_version(db)
        return {'package': None, 'created': False,
                'partner': views.partner(partner.name, partner.confirmed_version,
                                         target.version if target else None, None)}
    if created:
        record(db, actor.username, 'package.claimed', item.id, partner=item.partner,
               baseline_version=item.baseline_version, target_version=item.target_version)
        db.commit()
    else:
        record(db, actor.username, 'package.reused', item.id, partner=item.partner,
               target_version=item.target_version)
        db.commit()
    return {'package': views.package(item), 'created': created}


@router.get('/packages/{package_id}/export')
def export_package(package_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    item = db.get(DeliveryPackage, package_id)
    if not item:
        raise HTTPException(404, '找不到该交付包')
    if not item.export_file:
        raise HTTPException(409, '此交付包尚无可下载文件')
    path = ARTIFACTS / item.export_file
    if not path.is_file():
        raise HTTPException(410, '交付文件已不可用，请重新领取')
    name = f'{SPEC["short_name"]}-{item.partner}-v{item.baseline_version}-v{item.target_version}.csv'
    return FileResponse(path, media_type='text/csv', filename=name)


@router.post('/confirmations')
def confirm_package(body: ConfirmRequest, db: Session = Depends(connection),
                    actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    try:
        item, advanced = confirm(db, body.name.strip(), body.package_id, body.checksum)
    except PartnerMissing:
        raise HTTPException(404, '找不到该合作方') from None
    except PackageMissing:
        raise HTTPException(404, '找不到该交付包') from None
    except PackageConflict as error:
        raise HTTPException(409, str(error)) from None
    record(db, actor.username, 'package.confirmed' if advanced else 'package.replayed', item.id,
           partner=item.partner, target_version=item.target_version)
    db.commit()
    partner = db.get(Partner, body.name.strip())
    target = latest_version(db)
    return {'package': views.package(item), 'advanced': advanced,
            'partner': views.partner(partner.name, partner.confirmed_version,
                                     target.version if target else None, pending_for(db, partner.name))}
