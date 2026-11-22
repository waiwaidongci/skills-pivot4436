import {feedback, field} from '../components/common/fields.js';
import {empty, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {REVIEW} from '../constants/enums.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, link, p} from '../utils/dom.js';
import {date, value} from '../utils/format.js';

const KIND = {full:'整表', delta:'差量'};

function packageSummary(item) {
  return el('dl', {class:'dictionary'},
    el('div',{},el('dt',{},'交付方式'),el('dd',{},KIND[item.kind] || item.kind)),
    el('div',{},el('dt',{},'起始版本'),el('dd',{},item.baseline_version ? `公开版 ${item.baseline_version}` : '尚未入库（整表）')),
    el('div',{},el('dt',{},'目标版本'),el('dd',{},`公开版 ${item.target_version}`)),
    el('div',{},el('dt',{},'变动格数'),el('dd',{},item.operation_count)),
    el('div',{},el('dt',{},'校验指纹'),el('dd',{},item.checksum)));
}

function operationTable(operations) {
  return table([
    {key:'op_label', label:'操作'},
    {key:'key', label:'单元格'},
    {label:'值', render:row => row.op === 'remove' ? el('span',{},'—') : value(row.value)},
  ], operations, {caption:'本包变动单元格', empty:'本包没有需要变动的单元格。'});
}

function downloadButton(item, message) {
  const control = button('下载交付包', {class:'quiet', 'data-testid':'download-package'});
  control.addEventListener('click', handler(control, message, () =>
    workspace.download(`/packages/${item.id}/export`,
      `${workspace.spec.short_name}-${item.partner}-v${item.baseline_version}-v${item.target_version}.csv`)));
  return control;
}

function claimBlock(partner, message, refresh) {
  const control = session.canWrite && button('领取最新公开版', {class:'primary', 'data-testid':'claim'});
  control && control.addEventListener('click', handler(control, message, async () => {
    await workspace.claim(partner.name);
    await refresh();
  }));
  return el('div', {},
    partner.up_to_date
      ? p(`已入库公开版 ${partner.confirmed_version}，暂无更新的公开版本。`, 'subtle')
      : p(`当前已入库公开版 ${partner.confirmed_version || '—'}，可领取补齐至公开版 ${partner.latest_version}。`, 'intro-copy'),
    el('div',{class:'actions'}, control), message);
}

function pendingBlock(partner, message, refresh) {
  const item = partner.pending;
  const download = downloadButton(item, message);
  const confirm = session.canWrite && button('确认已入库', {class:'primary', 'data-testid':'confirm'});
  confirm && confirm.addEventListener('click', handler(confirm, message, async () => {
    await workspace.confirm(partner.name, item.id, item.checksum);
    await refresh();
  }));
  return el('div', {},
    p('这份待确认包已锁定：确认前重复领取都会原样返回本包，期间出现的新版本不会替换它。','subtle'),
    packageSummary(item),
    item.operations.length ? operationTable(item.operations) : p('本包只需确认版本，无变动单元格。','subtle'),
    el('div',{class:'actions'}, download, confirm), message);
}

function partnerPanel(partner, refresh) {
  const message = feedback();
  return el('section', {class:'panel'},
    el('div',{class:'activity'}, el('h2',{},partner.name),
      pill(partner.up_to_date ? '已是最新' : '可补齐', partner.up_to_date ? 'accepted' : 'pending')),
    p(`已入库公开版 ${partner.confirmed_version || '—'} · 最新公开版 ${partner.latest_version ?? '—'}`, 'filename'),
    partner.pending ? pendingBlock(partner, message, refresh) : claimBlock(partner, message, refresh));
}

function partnerForm(partners, refresh) {
  const message = feedback();
  const submit = button('新增合作方', {class:'primary', type:'submit', 'data-testid':'add-partner'});
  const form = el('form', {class:'fields', onSubmit:handler(submit, message, async event => {
    const data = new FormData(event.target);
    const name = data.get('name')?.trim();
    if (!name) throw new Error('请填写合作方名称');
    if (partners.some(item => item.name === name)) throw new Error('该合作方已在名册中');
    await workspace.addPartner(name);
    await refresh();
  })}, field({key:'name', label:'合作方名称', type:'string', max_length:100}), submit, message);
  return form;
}

export async function deliveryPage(route, refresh) {
  const {spec, runs} = workspace;
  const message = feedback();
  const [partners, publications] = await Promise.all([workspace.partners(), workspace.publications()]);
  const versionList = panel('公开版本', table([
    {label:'版本', render:row=>`公开版 ${row.version}`},
    {key:'period', label:'统计月份'},
    {key:'headline', label:'标题'},
    {label:'运行', render:row=>link(`运行 ${row.run_id}`, `#results/${row.run_id}`)},
    {label:'登记时间', render:row=>date(row.created_at)},
  ], publications, {caption:'复核通过的公开版本', empty:'复核通过后会登记公开版本。'}));
  const artifacts = table([
    {label:'报告', render:row=>link(row.name,`#results/${row.id}`)},
    {label:'复核', render:row=>pill(REVIEW[row.review],row.review)},
    {label:'计算时间', render:row=>date(row.finished_at)},
    {label:'下载', render:row=>{
      const download = button('下载 CSV',{class:'quiet'});
      download.addEventListener('click', handler(download,message,() =>
        workspace.download(`/runs/${row.id}/export`,`${spec.short_name}-${row.id}.csv`)));
      return download;
    }},
  ], runs.filter(row=>row.status==='complete'), {caption:'可导出的结果', empty:'完成计算后会生成对应的报告。'});
  const delivery = spec.scheduled ? panel('站内分发回执', table([
    {key:'recipient',label:'收件团队'},
    {label:'回执',render:row=>pill(row.state==='delivered'?'已投递':'已拦截',row.state)},
    {key:'detail',label:'说明'}, {label:'时间',render:row=>date(row.created_at)},
    {label:'查看',render:row=>link(`运行 ${row.run_id}`,`#results/${row.run_id}`)},
  ],await workspace.deliveries(),{caption:'站内收件箱',empty:'计划到时执行，回执将在此更新。'})) : null;
  return el('div',{},
    panel(spec.pages[5],
      p('每家合作方以自己确认入库的版本为起点。首次领取整表，之后只领取变动，撤下的格子只标移除。','subtle'),
      message),
    el('div',{class:'two-col'},
      el('div',{class:'wide-panel'},
        partners.length
          ? partners.map(partner=>partnerPanel(partner, refresh))
          : panel('合作方名册', empty('先添加合作方，再按版本领取公开表。')),
        session.canReview ? panel('新增合作方', partnerForm(partners, refresh)) : null),
      el('aside',{class:'sidebar-panel'}, versionList, delivery)),
    panel('复核通过的运行结果',
      p('单次运行 CSV 仍可从每次运行下载；合作方的整表或差量请使用上方交付包。','subtle'), artifacts));
}
