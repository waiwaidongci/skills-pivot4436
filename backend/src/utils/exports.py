import csv
from src.config.settings import ARTIFACTS


def safe_cell(value):
    if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@'))
                                   or value.startswith(('\t', '\r', '\n'))):
        return "'" + value
    return value


def write_report(run_id, attempt, result):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    name = f'analysis-{run_id}-{attempt}.csv'
    path = ARTIFACTS / name
    staging = path.with_suffix('.tmp')
    with staging.open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.writer(output)
        writer.writerow([safe_cell(result['headline'])])
        writer.writerow([safe_cell(result.get('note', ''))])
        for metric in result['metrics']:
            writer.writerow([safe_cell(metric['label']), safe_cell(metric['value']), safe_cell(metric.get('detail', ''))])
        for table in result['tables']:
            writer.writerow([])
            writer.writerow([safe_cell(table['title'])])
            columns = table['columns']
            writer.writerow([safe_cell(column['label']) for column in columns])
            writer.writerows([safe_cell(row.get(column['key'])) for column in columns] for row in table['rows'])
    staging.replace(path)
    return name


def write_package(package):
    """写出合作方交付包：整表或差量，撤下的格子只标移除。"""
    from src.domain.delivery_pack import KIND_LABELS, OP_LABELS
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    stem = f'package-{package.id}-v{package.baseline_version}-v{package.target_version}'
    name = f'{stem}.csv'
    path = ARTIFACTS / name
    staging = path.with_suffix('.tmp')
    with staging.open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.writer(output)
        writer.writerow([safe_cell('合作方'), safe_cell(package.partner)])
        writer.writerow([safe_cell('起始版本'), package.baseline_version,
                         safe_cell('目标版本'), package.target_version])
        writer.writerow([safe_cell('交付方式'), safe_cell(KIND_LABELS.get(package.kind, package.kind))])
        writer.writerow([safe_cell('校验指纹'), safe_cell(package.checksum)])
        writer.writerow([])
        writer.writerow([safe_cell('操作'), safe_cell('单元格'), safe_cell('值')])
        for operation in package.operations:
            writer.writerow([safe_cell(OP_LABELS.get(operation['op'], operation['op'])),
                             safe_cell(operation['key']), safe_cell(operation.get('value'))])
    staging.replace(path)
    return name
