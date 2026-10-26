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
function directory_metadata(string $path,bool $blocked=false): array {
    $report=['classification'=>$blocked?'parent_unavailable':'missing','exists'=>false,'directory'=>false,
             'is_symlink'=>false,'owner_class'=>'unknown','mode'=>null,'realpath_matches'=>false];
    if ($blocked) return $report;
    clearstatcache(true,$path);
    $info=@lstat($path);
    if ($info===false) {
        // A failed lstat is missing only if its readable, already checked
        // parent confirms no entry. Permission/IO failures are not absence.
        $entries=@scandir(dirname($path));
        if ($entries===false || in_array(basename($path),$entries,true)) $report['classification']='unreadable';
        return $report;
    }
    return array_replace($report,['classification'=>'present','exists'=>true,
        'directory'=>($info['mode']&0170000)===0040000,'is_symlink'=>($info['mode']&0170000)===0120000,
        'owner_class'=>$info['uid']===0?'root':'nonroot','mode'=>sprintf('%04o',$info['mode']&07777),
        'realpath_matches'=>realpath($path)===$path]);
}
function directory_usable(array $meta,string $role): bool {
    if (!$meta['directory'] || $meta['is_symlink'] || !$meta['realpath_matches']) return false;
    if (in_array($role,['anchor','app'],true)) return true; // Existing Laravel storage/app may be app-owned and writable.
    if ($meta['owner_class']!=='root') return false;
    $mode=octdec($meta['mode']);
    return $role==='scope' ? $mode===0700 : ($mode&0022)===0;
}
function scope_directories(string $directory): array {
    if (basename($directory)!=='upstream-20261022' || basename(dirname($directory))!=='backups' ||
        basename(dirname($directory,2))!=='app' ||
        (!defined('XBOARD_LEGACY_GUARD_SCOPE_LIBRARY_ONLY') && dirname($directory,3)!=='/www/storage')) rejected('container_parent_invalid');
    $anchor=directory_metadata(dirname($directory,3));
    $anchorSafe=directory_usable($anchor,'anchor');
    $app=directory_metadata(dirname($directory,2),!$anchorSafe);
    $appSafe=directory_usable($app,'app');
    $backups=directory_metadata(dirname($directory),!$appSafe);
    $backupsSafe=directory_usable($backups,'backups');
    $scope=directory_metadata($directory,!$backupsSafe);
    // Missing intermediate directory means its fixed child is also missing;
    // do not traverse an unsafe existing parent to inspect that child.
    if ($anchorSafe && $app['classification']==='missing') {
        $backups['classification']='missing';$scope['classification']='missing';
    } elseif ($appSafe && $backups['classification']==='missing') $scope['classification']='missing';
    $scopeSafe=directory_usable($scope,'scope');
    $creatable=$anchorSafe && ($appSafe || ($app['classification']==='missing' && (octdec($anchor['mode'])&07000)===0)) &&
               ($backupsSafe || $backups['classification']==='missing') && $scope['classification']==='missing';
    return ['directories'=>['anchor'=>$anchor,'app'=>$app,'backups'=>$backups,'scope'=>$scope],
            'parent_safe'=>$anchorSafe && $appSafe && $backupsSafe && $scopeSafe,'parent_creatable'=>$creatable];
}
function directory_identity(string $directory): array {
    clearstatcache(true,$directory);
    $info=lstat($directory);
    if ($info===false || ($info['mode']&0170000)!==0040000 || realpath($directory)!==$directory) rejected('container_parent_invalid');
    return array_intersect_key($info,array_flip(['dev','ino','uid','gid','mode']));
}
function sync_parent(string $directory): void {
    $handle=fopen($directory,'r');
    if ($handle===false) rejected('container_commit_unknown');
    try { if (!fsync($handle)) rejected('container_commit_unknown'); }
    finally { fclose($handle); }
}
function create_app_inheriting_storage(string $app,array $storage,array &$created): void {
    foreach (['posix_geteuid','posix_getegid','posix_seteuid','posix_setegid'] as $function)
        if (!function_exists($function)) rejected('container_parent_invalid');
    $uid=posix_geteuid();$gid=posix_getegid();
    if ($uid!==0 || $gid!==0) rejected('container_scope_invalid');
    if (($storage['mode']&07000)!==0) rejected('container_parent_invalid');
    $mode=$storage['mode']&0777;$mask=umask(0000);
    try {
        // Create with the existing Laravel storage identity/mode directly.
        // Never chown/chmod an existing path, including a raced-in app entry.
        if (!posix_setegid($storage['gid']) || !posix_seteuid($storage['uid'])) rejected('container_parent_invalid');
        if (!mkdir($app,$mode,false)) rejected('container_parent_invalid');
        $created[]='app';
    } finally {
        $restoredUid=posix_seteuid($uid);$restoredGid=posix_setegid($gid);umask($mask);
        if (!$restoredUid || !$restoredGid) rejected('container_commit_unknown');
    }
    $new=directory_identity($app);
    if ($new['uid']!==$storage['uid'] || $new['gid']!==$storage['gid'] || ($new['mode']&07777)!==$mode ||
        directory_identity(dirname($app))!==$storage) rejected('container_commit_unknown');
    sync_parent(dirname($app));
}
function create_missing_directories(string $directory,array &$created): void {
    $before=scope_directories($directory);
    if ($before['parent_safe']) return;
    if (!$before['parent_creatable']) rejected('container_parent_invalid');
    $anchor=dirname($directory,3);
    $anchorIdentity=directory_identity($anchor);
    $app=dirname($directory,2);
    $appMetadata=directory_metadata($app);
    if ($appMetadata['classification']==='missing') create_app_inheriting_storage($app,$anchorIdentity,$created);
    elseif (!directory_usable($appMetadata,'app')) rejected('container_parent_invalid');
    foreach (['backups'=>dirname($directory),'scope'=>$directory] as $role=>$path) {
        $meta=directory_metadata($path);
        if ($meta['classification']==='missing') {
            $parent=dirname($path);
            $identity=directory_identity($parent);
            // No recursive mkdir: an existing file/link/directory is never
            // followed, chmodded, replaced, or treated as a successful create.
            if (!mkdir($path,0700,false)) rejected('container_parent_invalid');
            $created[]=$role;
            if (directory_identity($anchor)!==$anchorIdentity || directory_identity($parent)!==$identity ||
                !directory_usable(directory_metadata($path),$role) || directory_metadata($path)['mode']!=='0700') rejected('container_commit_unknown');
            sync_parent($parent);
        } elseif (!directory_usable($meta,$role)) rejected('container_parent_invalid');
    }
    if (!scope_directories($directory)['parent_safe']) rejected('container_commit_unknown');
}
function status_at(string $directory,string $raw): array {
    clearstatcache(true);
    $parents=scope_directories($directory);
    $safe=$parents['parent_safe'];
    $target=$directory.'/manifest.private';
    // Never traverse an unsafe or missing fixed parent to read the target.
    $info=$safe ? @lstat($target) : false;
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
            'target_matches'=>$matches,'target_private'=>$private,'parent_safe'=>$safe,
            'parent_creatable'=>$parents['parent_creatable'],'directories'=>$parents['directories'],
            'directories_created'=>[],'manifest_created'=>false];
}
function mirror_scope(string $directory,string $raw,string $action): array {
    manifest_scope($raw);
    if (!in_array($action,['inspect','restore'],true)) rejected('container_scope_invalid');
    $before=status_at($directory,$raw);
    if ($action==='inspect') return $before;
    if (!$before['parent_safe'] && !$before['parent_creatable']) rejected('container_parent_invalid');
    $created=[];
    try { create_missing_directories($directory,$created); }
    catch (Throwable $error) { if ($created) rejected('container_commit_unknown'); throw $error; }
    $before=status_at($directory,$raw);
    if ($before['target_exists']) {
        if (!$before['target_matches']) rejected('container_manifest_conflict');
        if (!$before['target_private']) rejected('container_manifest_permissions');
        return array_replace($before,['status'=>'already_matches','directories_created'=>$created]);
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
        return array_replace($after,['status'=>'restored','manifest_created'=>true,'directories_created'=>$created]);
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
        umask(0077);
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
