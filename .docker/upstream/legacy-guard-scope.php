<?php
// Fixed-path filesystem helper only. No application bootstrap, DB or service API.
declare(strict_types=1);
ini_set('display_errors', '0');
function rejected(string $reason): never { throw new RuntimeException($reason); }
function manifest_scope(string $raw): void {
    $value=json_decode($raw,true,512,JSON_THROW_ON_ERROR);
    if (!is_array($value) || array_keys($value)!==['machine_id','routes'] || $value['machine_id']!==21 ||
        !is_array($value['routes']) || count($value['routes'])!==41) rejected('container_scope_invalid');
    foreach ($value['routes'] as $index=>$row) {
        $number=$index+1;
        if (!is_array($row) || array_keys($row)!==['backend_id','key','public_id'] ||
            $row['key']!==sprintf('U%02d',$number) || $row['backend_id']!==357+2*$number || $row['public_id']!==358+2*$number) rejected('container_scope_invalid');
    }
    if (json_encode($value,JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR)!==$raw) rejected('container_scope_invalid');
}
function status_at(string $directory,string $raw): array {
    clearstatcache(true);
    $parent=@lstat($directory);
    $safe=$parent!==false && ($parent['mode']&0170000)===0040000 && $parent['uid']===0 && ($parent['mode']&0022)===0 && realpath($directory)===$directory;
    $target=$directory.'/manifest.private';
    $info=@lstat($target);
    $exists=$info!==false;
    $regular=$exists && ($info['mode']&0170000)===0100000;
    $private=$regular && $info['uid']===0 && ($info['mode']&0777)===0600;
    $matches=false;
    if ($safe && $regular && $info['size']===strlen($raw)) {
        $source=fopen($target,'rb');
        if ($source===false) rejected('container_io_failed');
        try {
            $opened=fstat($source);
            $body=stream_get_contents($source,strlen($raw)+1);
            $after=fstat($source);
        } finally { fclose($source); }
        clearstatcache(true,$target);
        $path=lstat($target);
        foreach (['dev','ino','uid','gid','mode','size','mtime','ctime'] as $field) {
            if ($opened===false || $after===false || $path===false || $opened[$field]!==$info[$field] ||
                $after[$field]!==$info[$field] || $path[$field]!==$info[$field]) rejected('container_manifest_conflict');
        }
        $matches=$body!==false && hash_equals($raw,$body);
    }
    return ['status'=>'inspected','manifest_sha256'=>hash('sha256',$raw),'target_exists'=>$exists,
            'target_matches'=>$matches,'target_private'=>$private,'parent_safe'=>$safe,'manifest_created'=>false];
}
function mirror_scope(string $directory,string $raw,string $action): array {
    manifest_scope($raw);
    if (!in_array($action,['inspect','restore'],true)) rejected('container_scope_invalid');
    $before=status_at($directory,$raw);
    if ($action==='inspect') return $before;
    if (!$before['parent_safe']) rejected('container_parent_invalid');
    if ($before['target_exists']) {
        if (!$before['target_matches']) rejected('container_manifest_conflict');
        if (!$before['target_private']) rejected('container_manifest_permissions');
        return array_replace($before,['status'=>'already_matches']);
    }
    $temporary=$directory.'/.guard-scope-'.bin2hex(random_bytes(16)).'.tmp';
    $target=$directory.'/manifest.private';
    $linked=false;
    try {
        $file=fopen($temporary,'x+b');
        if ($file===false || !chmod($temporary,0600)) rejected('container_io_failed');
        try {
            $offset=0;
            while ($offset<strlen($raw)) {
                $count=fwrite($file,substr($raw,$offset));
                if ($count===false || $count===0) rejected('container_io_failed');
                $offset+=$count;
            }
            if (!fflush($file) || !fsync($file)) rejected('container_io_failed');
        } finally { fclose($file); }
        // link cannot replace any existing file, directory or dangling symlink.
        if (!link($temporary,$target)) rejected('container_manifest_conflict');
        $linked=true;
        $directoryHandle=fopen($directory,'r');
        if ($directoryHandle===false) rejected('container_commit_unknown');
        try { if (!fsync($directoryHandle)) rejected('container_commit_unknown'); }
        finally { fclose($directoryHandle); }
        $after=status_at($directory,$raw);
        if (!$after['target_exists'] || !$after['target_matches'] || !$after['target_private'] || !$after['parent_safe']) rejected('container_commit_unknown');
        return array_replace($after,['status'=>'restored','manifest_created'=>true]);
    } catch (Throwable $error) {
        if ($linked) rejected('container_commit_unknown');
        throw $error;
    } finally {
        if (file_exists($temporary) || is_link($temporary)) {
            if (!unlink($temporary) && $linked) rejected('container_commit_unknown');
        }
    }
}
if (!defined('XBOARD_LEGACY_GUARD_SCOPE_LIBRARY_ONLY')) {
    set_error_handler(static function(int $severity) {
        if (!(error_reporting()&$severity)) return false;
        rejected('container_io_failed');
    });
    try {
        $raw=base64_decode('__MANIFEST_BASE64__',true);
        if ($raw===false || strlen($raw)>16384 || !function_exists('posix_geteuid') || posix_geteuid()!==0) rejected('container_scope_invalid');
        echo json_encode(mirror_scope('/www/storage/app/backups/upstream-20261022',$raw,'__ACTION__'),JSON_THROW_ON_ERROR);
    } catch (Throwable $error) {
        $allowed=['container_scope_invalid','container_parent_invalid','container_manifest_conflict','container_manifest_permissions','container_commit_unknown','container_io_failed'];
        $reason=in_array($error->getMessage(),$allowed,true)?$error->getMessage():'container_io_failed';
        echo json_encode(['status'=>'error','reason'=>$reason],JSON_THROW_ON_ERROR);
        exit(1);
    }
}
