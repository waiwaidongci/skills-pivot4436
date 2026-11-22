"""合作方公开版本的增量交付。

规则：
- 首次交付为整表；之后以合作方已确认入库的版本为基线，只交付变动，
  撤下的格子记为移除。
- 领取时尽可能补齐到最新公开版本；若已有待确认包，则原样返回该包，
  即使期间出现了更新的公开版本。
- 确认只推进待确认包的目标版本；重复、过期或乱序的回执不会回退版本，
  也不会把尚未入库的版本当作新基线。
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.domain import delivery_pack
from src.models.jobs import DeliveryPackage, Partner, Publication
from src.utils.exports import write_package
from src.utils.time import now


class PartnerMissing(Exception):
    pass


class PackageMissing(Exception):
    pass


class PackageConflict(Exception):
    pass


def publish(db, run):
    """复核通过时登记不可变的公开版本。重复调用返回既有版本。"""
    existing = db.scalar(select(Publication).where(Publication.run_id == run.id))
    if existing:
        return existing
    item = Publication(run_id=run.id, snapshot=delivery_pack.snapshot(run.result, run.params))
    db.add(item)
    db.flush()
    return item


def latest_version(db):
    return db.scalar(select(Publication).order_by(Publication.version.desc()).limit(1))


def create_partner(db, name):
    item = db.get(Partner, name)
    if item:
        return item, False
    item = Partner(name=name, confirmed_version=0)
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.get(Partner, name, with_for_update=True)
        if existing:
            return existing, False
        raise
    return item, True


def require_partner(db, name, lock=False):
    item = db.get(Partner, name, with_for_update=lock)
    if not item:
        raise PartnerMissing(name)
    return item


def pending_for(db, name, lock=False):
    query = select(DeliveryPackage).where(DeliveryPackage.partner == name,
                                          DeliveryPackage.pending_key.is_not(None))
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def claim(db, name):
    """领取交付包。返回 (包, 是否新建)；已是最新时返回 (None, False)。

    并发领取由唯一 pending_key 兜底：竞争失败的一方在保存点内回滚后，
    只会看到另一方建立的同一份待确认包。
    """
    partner = require_partner(db, name, lock=True)
    pending = pending_for(db, name, lock=True)
    if pending:
        # 旧包未确认：即使有新版，重试也原样给旧包。
        return pending, False
    target = latest_version(db)
    if target is None or target.version <= partner.confirmed_version:
        return None, False
    baseline = db.get(Publication, partner.confirmed_version) if partner.confirmed_version else None
    if partner.confirmed_version and baseline is None:
        raise PackageConflict("找不到合作方已确认版本的公开快照")
    built = delivery_pack.build(name, partner.confirmed_version,
                                baseline.snapshot if baseline else None,
                                target.version, target.snapshot)
    package = DeliveryPackage(partner=name, baseline_version=partner.confirmed_version,
                              target_version=target.version, kind=built["kind"],
                              operations=built["operations"], checksum=built["checksum"],
                              pending_key=name)
    try:
        with db.begin_nested():
            db.add(package)
            db.flush()
    except IntegrityError:
        # 另一个并发请求已建立待确认包，它才是唯一可领取的那份。
        pending = pending_for(db, name, lock=True)
        if pending:
            return pending, False
        raise
    package.export_file = write_package(package)
    db.flush()
    return package, True


def confirm(db, name, package_id, signature):
    """确认交付包已入库。返回 (包, 是否推进了确认版本)。"""
    partner = require_partner(db, name, lock=True)
    package = db.get(DeliveryPackage, package_id, with_for_update=True)
    if not package or package.partner != name:
        raise PackageMissing(package_id)
    if package.checksum != signature:
        raise PackageConflict("交付包校验不一致，请重新下载")
    if package.pending_key is None:
        # 重复或迟到的回执：已确认过，不回退版本，也不清除其他待确认包。
        return package, False
    pending = pending_for(db, name, lock=True)
    if not pending or pending.id != package.id:
        # 成交付期间状态被替换，不能把未经确认的目标版本当基线。
        raise PackageConflict("该包已不是当前待确认包，请重新领取")
    if package.target_version > partner.confirmed_version:
        partner.confirmed_version = package.target_version
    package.pending_key = None
    package.confirmed_at = now()
    db.flush()
    return package, True
