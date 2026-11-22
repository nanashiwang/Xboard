// Integrated with the pinned admin React table by patch-admin-node-lines.php.
function groupAdminNodeLines(nodes) {
  const byId = new Map(nodes.map(node => [Number(node.id), node]));
  const referenced = new Set(nodes.map(node => Number(node.parent_id)));
  const children = new Map();
  for (const node of nodes) {
    const parent = byId.get(Number(node.parent_id));
    // Only fold simple hidden roots. Standalone nodes, public parents, chains
    // and broken references remain individually manageable.
    if (!parent || parent === node || Number(parent.parent_id) || Number(parent.show)) continue;
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(node);
  }
  const details = new Map();
  const folded = new Set();
  for (const [backend, entries] of children) {
    // If an intermediate node has children, leave this topology flat.
    if (entries.some(entry => referenced.has(Number(entry.id)))) continue;
    const visible = entries.filter(entry => Number(entry.show));
    const choices = visible.length ? visible : entries;
    const primary = choices.find(entry => !Number(entry.dedicated_exit_id)) || choices[0];
    const others = entries.filter(entry => entry !== primary);
    details.set(primary.id, {backend, others});
    folded.add(backend);
    for (const entry of others) folded.add(entry);
  }
  return {rows: nodes.filter(node => !folded.has(node)), details};
}

const adminLineLabels = {
  zh: ['按线路', '全部记录', '后端详情', '后端', '关联入口', '编辑'],
  en: ['Lines', 'All records', 'Backend details', 'Backend', 'Linked entry', 'Edit'],
  ru: ['Линии', 'Все записи', 'Подробнее о бэкенде', 'Бэкенд', 'Связанный узел', 'Изменить'],
};

function useAdminNodeLines(nodes, filters, sortingMode, translate) {
  const groups = H.useMemo(() => groupAdminNodeLines(nodes), [nodes]);
  const [allRecords, setAllRecords] = H.useState(false);
  const [expanded, setExpanded] = H.useState(null);
  const {i18n} = jy('server');
  const labels = adminLineLabels[(i18n.resolvedLanguage || i18n.language || 'en').split('-')[0]] || adminLineLabels.en;
  const filtering = filters.length > 0;
  const grouped = !allRecords && !filtering && !sortingMode;
  return {
    rows: grouped ? groups.rows : nodes, details: grouped ? groups.details : null,
    groupCount: groups.rows.length, total: nodes.length, translate, labels,
    grouped, showModes: !filtering && !sortingMode && groups.details.size > 0,
    expanded, setExpanded, setAllRecords,
  };
}

function AdminNodeLineModes({table}) {
  const view = table.options.meta;
  if (!view.showModes) return null;
  function button(all, label, count) {
    const pressed = all ? !view.grouped : view.grouped;
    return H.createElement(Lf, {
      type: 'button', size: 'sm', variant: pressed ? 'secondary' : 'ghost',
      'aria-pressed': pressed,
      onClick() {
        table.resetRowSelection();
        table.setPageIndex(0);
        view.setAllRecords(all);
      },
    }, label + ' (' + count + ')');
  }
  return H.createElement('div', {className: 'inline-flex items-center gap-1 rounded-md border p-1'},
    button(false, view.labels[0], view.groupCount), button(true, view.labels[1], view.total));
}

function AdminNodeLineName({row, table}) {
  const view = table.options.meta;
  const node = row.original;
  const group = view.details?.get(node.id);
  const editor = a4t();
  const name = H.createElement(V5t, {node, t: view.translate});
  if (!group) return name;
  const open = view.expanded === node.id;
  const detailsId = 'admin-line-details-' + node.id;
  function detail(record, role) {
    return H.createElement('div', {key: record.id, className: 'space-y-1 border-l pl-3'},
      H.createElement('div', {className: 'text-xs text-muted-foreground'}, role + ' · #' + record.id),
      H.createElement('div', {className: 'font-medium break-words'}, record.name),
      H.createElement('div', {className: 'font-mono text-xs text-muted-foreground break-all'}, record.host + ':' + record.port),
      H.createElement(Lf, {type: 'button', variant: 'outline', size: 'sm',
        'aria-label': view.labels[5] + ' ' + record.name + ' #' + record.id,
        onClick() {
          editor.setServerType(record.type);
          editor.setEditingServer(record);
          editor.setIsOpen(true);
        },
      }, view.labels[5]));
  }
  return H.createElement('div', {className: 'space-y-1', style: {whiteSpace: 'normal'}}, name,
    H.createElement('button', {type: 'button', className: 'text-xs text-muted-foreground hover:text-primary',
      'aria-expanded': open, 'aria-controls': detailsId,
      onClick: () => view.setExpanded(open ? null : node.id),
    }, H.createElement('span', {'aria-hidden': true}, open ? '▾ ' : '▸ '), view.labels[2]),
    open && H.createElement('div', {id: detailsId, className: 'space-y-3 py-2'},
      detail(group.backend, view.labels[3]), group.others.map(entry => detail(entry, view.labels[4]))));
}
