<?php

function patchAdminNodeLines(string $source): string
{
    // Bind only the node table. Other admin tables use the same table renderer.
    $patches = [
        'const N=wGt({data:_||[],columns:$5t(w,e,b),' =>
            'const lineView=useAdminNodeLines(_,a,g,e);const N=wGt({data:lineView.rows,meta:lineView,getRowId:row=>String(row.id),columns:$5t(w,e,b),',
        'cell:({row:e})=>Q.jsx(V5t,{node:e.original,t:t})' =>
            'cell:AdminNodeLineName',
        'cell:({row:e})=>{const i=n.find(t=>t.id===e.original.machine_id)??null;return Q.jsx("div",{className:"flex items-center gap-1.5 px-1",children:Q.jsx(U5t,{node:e.original,machine:i,t:t})})}' =>
            'cell:({row:e,table:table})=>{const node=table.options.meta.details?.get(e.original.id)?.backend??e.original;const machine=n.find(m=>m.id===node.machine_id)??null;return Q.jsx(U5t,{node,machine,t})}',
        'toolbar:e=>Q.jsx(_5t,{table:e,refetch:i,saveOrder:r,isSortMode:s,groups:o,machines:a})' =>
            'toolbar:e=>Q.jsxs(Q.Fragment,{children:[Q.jsx(AdminNodeLineModes,{table:e}),Q.jsx(_5t,{table:e,refetch:i,saveOrder:r,isSortMode:s,groups:o,machines:a})]})',
    ];
    foreach ($patches as $before => $after) {
        $original = substr_count($source, $before);
        $patched = substr_count($source, $after);
        if ($original === 1 && $patched === 0) {
            $source = str_replace($before, $after, $source);
        } elseif ($original !== 0 || $patched !== 1) {
            throw new RuntimeException('Admin node table changed. Review the pinned distribution.');
        }
    }
    $implementation = file_get_contents(__DIR__ . '/admin-node-lines.js');
    if ($implementation === false || trim($implementation) === '') {
        throw new RuntimeException('Admin node line view source is missing.');
    }
    // Include before the table is used. Keep the resulting asset self-contained.
    $anchor = 'function K5t(){';
    if (substr_count($source, $anchor) !== 1) {
        throw new RuntimeException('Admin node table entry changed.');
    }
    if (!str_contains($source, $implementation . $anchor)) {
        if (str_contains($source, 'function groupAdminNodeLines(')) {
            throw new RuntimeException('Rebuild from the pinned admin distribution.');
        }
        $source = str_replace($anchor, $implementation . $anchor, $source);
    }
    return $source;
}
