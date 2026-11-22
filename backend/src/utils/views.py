from src.utils.time import iso


def dataset(item):
    return {'id': item.id, 'name': item.name, 'filename': item.filename, 'row_count': item.row_count,
            'checksum': item.checksum, 'author': item.author, 'created_at': iso(item.created_at)}


def run(item, detail=False):
    item_view = {'id': item.id, 'dataset_id': item.dataset_id, 'name': item.name, 'status': item.status,
                 'author': item.author, 'review': item.review, 'decision': item.decision,
                 'created_at': iso(item.created_at), 'finished_at': iso(item.finished_at),
                 'scheduled_at': iso(item.scheduled_at), 'schedule_id': item.schedule_id,
                 'has_export': bool(item.export_file), 'error': item.error}
    if detail:
        item_view.update(params=item.params, result=item.result, review_note=item.review_note)
    return item_view


def schedule(item):
    from src.domain.spec import SPEC
    return {'id': item.id, 'name': item.name, 'dataset_id': item.dataset_id, 'recipient': item.recipient,
            'next_at': iso(item.next_at), 'repeat_daily': item.repeat_daily, 'enabled': item.enabled,
            'next_report_day': item.params.get(SPEC['schedule_date_param']) if item.enabled else None}


def delivery(item):
    return {'id': item.id, 'run_id': item.run_id, 'recipient': item.recipient,
            'state': item.state, 'detail': item.detail, 'created_at': iso(item.created_at)}


def package(item):
    from src.domain.delivery_pack import KIND_LABELS, OP_LABELS
    return {'id': item.id, 'partner': item.partner, 'baseline_version': item.baseline_version,
            'target_version': item.target_version, 'kind': item.kind,
            'kind_label': KIND_LABELS.get(item.kind, item.kind), 'checksum': item.checksum,
            'pending': item.pending_key is not None, 'operation_count': len(item.operations),
            'operations': [{'op': op['op'], 'op_label': OP_LABELS.get(op['op'], op['op']),
                            'key': op['key'], 'value': op.get('value')} for op in item.operations],
            'has_export': bool(item.export_file), 'created_at': iso(item.created_at),
            'confirmed_at': iso(item.confirmed_at)}


def partner(name, confirmed_version, latest_version, pending):
    return {'name': name, 'confirmed_version': confirmed_version, 'latest_version': latest_version,
            'up_to_date': latest_version is not None and confirmed_version >= latest_version,
            'pending': package(pending) if pending else None}
