<?php
declare(strict_types=1);
define('XBOARD_LEGACY_GUARD_SCOPE_LIBRARY_ONLY',true);
require __DIR__.'/../../.docker/upstream/legacy-guard-scope.php';
set_error_handler(static function(int $severity) {
    if (!(error_reporting()&$severity)) return false;
    throw new RuntimeException('test_io_failure');
});
$count=0;
function expect(bool $value): void { if (!$value) throw new RuntimeException('assertion_failed'); }
function rejects(callable $call,string $reason): void {
    try { $call(); } catch (Throwable $error) { expect($error->getMessage()===$reason); return; }
    throw new RuntimeException('expected_failure');
}
function fixture(): string {
    $anchor=sys_get_temp_dir().'/legacy-scope-'.bin2hex(random_bytes(12));
    mkdir($anchor,0700);mkdir($anchor.'/backups',0700);
    $directory=$anchor.'/backups/upstream-20261022';
    mkdir($directory,0700);return $directory;
}
function clean(string $path): void {
    if (is_dir($path) && !is_link($path)) {
        foreach (array_diff(scandir($path),['.','..']) as $name) clean($path.'/'.$name);
        rmdir($path);
    } elseif (file_exists($path) || is_link($path)) unlink($path);
}
function test(callable $call): void {
    global $count;
    $directory=fixture();
    try { $call($directory); $count++; } finally { clean(dirname($directory,2)); }
}
$rows=[];
for ($i=1;$i<=41;$i++) $rows[]=['backend_id'=>357+2*$i,'key'=>sprintf('U%02d',$i),'public_id'=>358+2*$i];
$raw=json_encode(['machine_id'=>21,'routes'=>$rows],JSON_THROW_ON_ERROR|JSON_UNESCAPED_SLASHES);
test(function($directory)use($raw) {
    $report=mirror_scope($directory,$raw,'inspect');
    expect($report['parent_safe'] && !$report['target_exists'] && !$report['manifest_created']);
    expect(count(scandir($directory))===2);
});
test(function($directory)use($raw) {
    $report=mirror_scope($directory,$raw,'restore');
    expect($report['status']==='restored' && $report['manifest_created']);
    $path=$directory.'/manifest.private';
    expect(file_get_contents($path)===$raw && (fileperms($path)&0777)===0600);
    expect(glob($directory.'/.guard-scope-*')===[]);
    $before=lstat($path);$again=mirror_scope($directory,$raw,'restore');$after=lstat($path);
    expect($again['status']==='already_matches' && !$again['manifest_created']);
    expect($before===$after);
});
test(function($directory)use($raw) {
    $path=$directory.'/manifest.private';file_put_contents($path,'private-existing-content');chmod($path,0600);
    rejects(fn()=>mirror_scope($directory,$raw,'restore'),'container_manifest_conflict');
    expect(file_get_contents($path)==='private-existing-content');
});
test(function($directory)use($raw) {
    $path=$directory.'/manifest.private';file_put_contents($path,$raw);chmod($path,0640);
    rejects(fn()=>mirror_scope($directory,$raw,'restore'),'container_manifest_permissions');
    expect((fileperms($path)&0777)===0640);
});
test(function($directory)use($raw) {
    $path=$directory.'/manifest.private';symlink($directory.'/private-missing-target',$path);
    $report=mirror_scope($directory,$raw,'inspect');expect($report['target_exists'] && !$report['target_matches']);
    rejects(fn()=>mirror_scope($directory,$raw,'restore'),'container_manifest_conflict');
    expect(is_link($path));
});
test(function($directory)use($raw) {
    $path=$directory.'/manifest.private';mkdir($path,0700);
    rejects(fn()=>mirror_scope($directory,$raw,'restore'),'container_manifest_conflict');expect(is_dir($path));
});
test(function($directory)use($raw) {
    chmod($directory,0777);
    rejects(fn()=>mirror_scope($directory,$raw,'restore'),'container_parent_invalid');
    expect(!file_exists($directory.'/manifest.private'));
});
test(function($directory)use($raw) {
    $link=$directory.'/alias';symlink($directory,$link);
    rejects(fn()=>mirror_scope($link,$raw,'restore'),'container_parent_invalid');
    expect(!file_exists($directory.'/manifest.private'));
});
test(function($directory)use($raw) {
    rejects(fn()=>mirror_scope($directory.'/missing',$raw,'restore'),'container_parent_invalid');
    expect(!file_exists($directory.'/missing'));
});
test(function($directory)use($raw) {
    foreach ([$raw.' ',str_replace('"machine_id":21','"machine_id":20',$raw),
              str_replace('"backend_id":359','"backend_id":148',$raw),
              str_replace('"key":"U01"','"key":"U42"',$raw),
              str_replace('"machine_id":21','"machine_id":20,"machine_id":21',$raw)] as $bad)
        rejects(fn()=>mirror_scope($directory,$bad,'restore'),'container_scope_invalid');
    expect(count(scandir($directory))===2);
});
test(function($directory)use($raw) {
    rejects(fn()=>mirror_scope($directory,$raw,'execute-guard'),'container_scope_invalid');
    expect(count(scandir($directory))===2);
});
test(function($directory)use($raw) {
    $report=mirror_scope($directory,$raw,'restore');
    expect(array_keys($report)===['status','manifest_sha256','target_exists','target_matches','target_private','parent_safe',
                                 'parent_creatable','directories','directories_created','manifest_created']);
    expect($report['manifest_sha256']===hash('sha256',$raw));
    expect(!str_contains(json_encode($report),'backend_id'));
});
test(function($directory)use($raw) {
    rmdir($directory);rmdir(dirname($directory));
    $before=mirror_scope($directory,$raw,'inspect');
    expect(!$before['parent_safe'] && $before['parent_creatable']);
    expect($before['directories']['backups']['classification']==='missing');
    expect($before['directories']['scope']['classification']==='missing');
    expect(!file_exists(dirname($directory)));
    $report=mirror_scope($directory,$raw,'restore');
    expect($report['directories_created']===['backups','scope']);
    expect((fileperms($directory)&07777)===0700 && (fileperms(dirname($directory))&07777)===0700);
    expect(file_get_contents($directory.'/manifest.private')===$raw);
});
test(function($directory)use($raw) {
    $anchor=dirname($directory,2);chmod($anchor,0775);chown($anchor,1001);
    rmdir($directory);chmod(dirname($directory),0755);
    $report=mirror_scope($directory,$raw,'restore');
    expect($report['directories_created']===['scope']);
    expect($report['directories']['anchor']['owner_class']==='nonroot');
    expect($report['directories']['anchor']['mode']==='0775');
    expect((fileperms($anchor)&07777)===0775 && (fileperms(dirname($directory))&07777)===0755);
});
test(function($directory)use($raw) {
    chmod($directory,0755);
    $before=mirror_scope($directory,$raw,'inspect');
    expect(!$before['parent_safe'] && !$before['parent_creatable']);
    expect($before['directories']['scope']['classification']==='present' && $before['directories']['scope']['mode']==='0755');
    rejects(fn()=>mirror_scope($directory,$raw,'restore'),'container_parent_invalid');
    expect((fileperms($directory)&07777)===0755);
});
test(function($directory)use($raw) {
    $anchor=dirname($directory,2);rmdir($directory);rmdir(dirname($directory));
    mkdir($anchor.'/other',0700);symlink($anchor.'/other',dirname($directory));
    $before=mirror_scope($directory,$raw,'inspect');
    expect($before['directories']['backups']['is_symlink']);
    expect($before['directories']['scope']['classification']==='parent_unavailable');
    rejects(fn()=>mirror_scope($directory,$raw,'restore'),'container_parent_invalid');
    expect(count(scandir($anchor.'/other'))===2);
});
test(function($directory)use($raw) {
    $anchor=dirname($directory,2);rmdir($directory);mkdir($anchor.'/other',0700);symlink($anchor.'/other',$directory);
    $before=mirror_scope($directory,$raw,'inspect');
    expect($before['directories']['scope']['is_symlink'] && !$before['parent_creatable']);
    rejects(fn()=>mirror_scope($directory,$raw,'restore'),'container_parent_invalid');
    expect(count(scandir($anchor.'/other'))===2);
});
test(function($directory)use($raw) {
    rmdir($directory);chown(dirname($directory),1001);
    $before=mirror_scope($directory,$raw,'inspect');
    expect($before['directories']['backups']['owner_class']==='nonroot');
    rejects(fn()=>mirror_scope($directory,$raw,'restore'),'container_parent_invalid');
    expect(!file_exists($directory));
});
echo json_encode(['status'=>'passed','tests'=>$count],JSON_THROW_ON_ERROR)."\n";
