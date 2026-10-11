#!/usr/bin/env bash
# Xboard server manager — managed by nanashiwang/Xboard.
set -Eeuo pipefail

MANAGER_VERSION=1.0.0
SELF=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")
export XBOARD_DIR=${XBOARD_DIR:-/root/Xboard}
SERVICE=xboard
ASSUME_YES=false

fail() { printf '错误：%s\n' "$*" >&2; exit 1; }
trap 'printf "操作失败（退出码 %s），后续步骤已停止。\n" "$?" >&2' ERR

usage() {
    cat <<'HELP'
Xboard 服务器管理

用法：xboard [menu|update|restart|start|stop|status|logs|uninstall|install|version|help] [--yes]
不带参数打开中文菜单。

update     拉取配置中的镜像，更新数据库和主题，启动并核验版本
restart    重启 Xboard
start      启动 Xboard（卸载容器后也可恢复）
stop       停止 Xboard
status     查看容器状态和运行版本
logs       查看最近 100 行日志
uninstall  移除 Xboard 容器，保留挂载数据；必须输入 UNINSTALL 确认
install    安装 /usr/local/bin/xboard 快捷命令
version    查看管理脚本版本

--yes 仅跳过更新、重启、启动、停止的确认，不能跳过卸载确认。
默认项目目录 /root/Xboard；其他目录可设置 XBOARD_DIR（绝对路径）。
仅支持包含 xboard 服务的镜像部署，不会自动合并上游代码。
HELP
}

prepare() {
    [[ "$XBOARD_DIR" = /* && "$XBOARD_DIR" != / ]] || fail 'XBOARD_DIR 必须是项目的绝对路径，不能是根目录。'
    [[ -d "$XBOARD_DIR" ]] || fail "项目目录不存在：$XBOARD_DIR"
    cd -- "$XBOARD_DIR"
    local file found=false
    for file in compose.yaml compose.yml docker-compose.yaml docker-compose.yml; do
        [[ ! -f "$file" ]] || found=true
    done
    "$found" || fail "项目目录内没有 Compose 配置：$XBOARD_DIR"
    command -v docker >/dev/null || fail '未安装 Docker。'
    command -v python3 >/dev/null || fail '请先安装 python3。'
    # Never let an unrelated shell's Compose overrides select another project.
    unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_ENV_FILES
    docker compose version >/dev/null
    docker compose config --services | grep -Fxq "$SERVICE" || fail '当前项目没有 xboard 服务，请核对目录和部署方式。'
}

compose() { docker compose --project-directory "$XBOARD_DIR" "$@"; }

require_wait_support() {
    [[ "$(compose up --help)" = *--wait-timeout* ]] || fail 'Docker Compose 版本过旧，请先升级到支持 --wait-timeout 的版本。'
}

lock_operation() {
    command -v flock >/dev/null || fail '请先安装 flock（通常由 util-linux 提供）。'
    exec 9>"$XBOARD_DIR/.xboard-manager.lock"
    flock -n 9 || fail '另一个 Xboard 管理操作正在执行，请稍后再试。'
}

confirm() {
    "$ASSUME_YES" && return 0
    local answer
    if ! read -r -p "$1 [y/N]：" answer; then
        printf '\n已取消。\n'
        exit 0
    fi
    case "$answer" in y|Y|yes|YES) ;; *) printf '已取消。\n'; exit 0 ;; esac
}

show_status() {
    local id image_id revision
    compose ps -a "$SERVICE"
    id=$(compose ps -a -q "$SERVICE")
    if [[ -n "$id" ]]; then
        image_id=$(docker inspect --format '{{.Image}}' "$id")
        revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image_id")
        printf '运行镜像：%s\n版本提交：%s\n' "$image_id" "${revision:-未知}"
    else
        printf 'Xboard 容器尚未创建，可选择“启动”。\n'
    fi
}

verify_running() {
    local expected_image=${1:-} id state running_image
    id=$(compose ps -q "$SERVICE")
    [[ -n "$id" ]] || fail '没有找到运行中的 Xboard 容器。'
    state=$(docker inspect --format '{{.State.Running}}' "$id")
    [[ "$state" = true ]] || fail 'Xboard 容器未运行。'
    if [[ -n "$expected_image" ]]; then
        running_image=$(docker inspect --format '{{.Image}}' "$id")
        [[ "$running_image" = "$expected_image" ]] || fail '运行镜像与刚拉取的镜像不一致。'
    fi
}

update() {
    require_wait_support
    printf '将更新 %s 中的 Xboard。请先确认数据库已有备份。\n' "$XBOARD_DIR"
    confirm '开始更新？'
    lock_operation
    local image_ref expected_image revision
    image_ref=$(compose config --format json | python3 -c '
import json, sys
s = json.load(sys.stdin)["services"]["xboard"]
if not s.get("image"):
    sys.exit("xboard 服务未配置镜像，无法执行镜像更新。")
for v in s.get("volumes", []):
    if v.get("target", "").rstrip("/") in ("", "/www"):
        sys.exit("检测到整个 /www 被挂载；此命令仅适用于镜像部署，请按源码部署文档更新。")
print(s["image"])
')
    compose pull "$SERVICE"
    expected_image=$(docker image inspect --format '{{.Id}}' "$image_ref")
    revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image_ref")
    if [[ -n "${XBOARD_EXPECTED_REVISION:-}" ]]; then
        [[ "$revision" = "$XBOARD_EXPECTED_REVISION" ]] || fail "镜像版本不匹配：预期 ${XBOARD_EXPECTED_REVISION}，实际 ${revision}。"
    fi
    # Detach stdin so migrations cannot consume the menu or SSH input.
    compose run --rm -T --pull never "$SERVICE" php artisan xboard:update </dev/null
    compose up -d --pull never --wait --wait-timeout 90 "$SERVICE"
    verify_running "$expected_image"
    printf '更新完成，运行版本：%s\n' "${revision:-$expected_image}"
    show_status
}

restart() {
    require_wait_support
    confirm '重启 Xboard？连接会短暂中断。'
    lock_operation
    [[ -n "$(compose ps -a -q "$SERVICE")" ]] || fail '容器尚未创建，请先选择“启动”。'
    compose restart "$SERVICE"
    compose up -d --no-recreate --pull never --wait --wait-timeout 90 "$SERVICE"
    verify_running
    printf '重启完成。\n'
}

start() {
    require_wait_support
    confirm '启动 Xboard？'
    lock_operation
    compose up -d --wait --wait-timeout 90 "$SERVICE"
    verify_running
    printf '启动完成。\n'
}

stop() {
    confirm '停止 Xboard？网站将暂时不可用。'
    lock_operation
    compose stop "$SERVICE"
    printf 'Xboard 已停止。\n'
}

uninstall() {
    local answer id mounts='[]'
    printf '将停止并移除 %s 的 xboard 容器。\n' "$XBOARD_DIR"
    printf '保留挂载的数据、配置、插件和镜像；不会删除其他服务或 Docker。\n'
    printf '容器内未持久化的文件会丢失。恢复服务可运行 xboard start。\n'
    if ! read -r -p '确认卸载请输入 UNINSTALL（其他输入取消）：' answer || [[ "$answer" != UNINSTALL ]]; then
        printf '\n已取消卸载。\n'
        return 0
    fi
    lock_operation
    # Anonymous volumes survive rm, but cannot be reliably reattached by up.
    id=$(compose ps -a -q "$SERVICE")
    if [[ -n "$id" ]]; then
        mounts=$(docker inspect --format '{{json .Mounts}}' "$id")
    fi
    compose config --format json | XBOARD_MOUNTS="$mounts" python3 -c '
import json, os, sys
config = json.load(sys.stdin)
volumes = config["services"]["xboard"].get("volumes", [])
if any(v.get("type") == "volume" and not v.get("source") for v in volumes):
    sys.exit("检测到匿名数据卷，请先备份并改为命名卷或目录挂载，再卸载。")
named = {config.get("volumes", {}).get(v["source"], {}).get("name", v["source"])
         for v in volumes if v.get("type") == "volume" and v.get("source")}
if any(m.get("Type") == "volume" and m.get("Name") not in named
       for m in json.loads(os.environ["XBOARD_MOUNTS"])):
    sys.exit("容器有未在 Compose 中声明的命名卷或匿名卷，请先核对持久化配置再卸载。")
'
    compose stop "$SERVICE"
    compose rm --force "$SERVICE"
    printf 'Xboard 容器已卸载，挂载数据已保留。可选择“启动”恢复服务。\n'
}

install_cli() {
    require_wait_support
    command -v flock >/dev/null || fail '请先安装 flock（通常由 util-linux 提供）。'
    local bin_dir=${XBOARD_BIN_DIR:-/usr/local/bin} target temporary
    [[ "$bin_dir" = /* ]] || fail '安装目录必须是绝对路径。'
    target="$bin_dir/xboard"
    if [[ -e "$target" || -L "$target" ]]; then
        [[ -f "$target" && ! -L "$target" ]] || fail "$target 不是普通文件，拒绝覆盖。"
        grep -Fq '# Xboard server manager' "$target" || fail "$target 已被其他程序占用，拒绝覆盖。"
    fi
    mkdir -p -- "$bin_dir"
    temporary=$(mktemp "$bin_dir/.xboard.XXXXXX")
    install -m 755 "$SELF" "$temporary"
    mv -f -- "$temporary" "$target"
    printf '已安装 %s（管理脚本 %s）。\n输入 xboard 即可打开菜单。\n' "$target" "$MANAGER_VERSION"
}

menu() {
    local choice action result
    while true; do
        cat <<MENU

========== Xboard 服务器管理 ==========
项目：$XBOARD_DIR
  1. 更新 Xboard
  2. 重启 Xboard
  3. 启动 Xboard
  4. 停止 Xboard
  5. 查看状态和版本
  6. 查看最近日志
  7. 卸载服务（保留数据）
  0. 退出
MENU
        if ! read -r -p '请输入选项 [0-7]：' choice; then printf '\n'; return 0; fi
        case "$choice" in
            1) action=update ;; 2) action=restart ;; 3) action=start ;;
            4) action=stop ;; 5) action=status ;; 6) action=logs ;;
            7) action=uninstall ;; 0) return 0 ;;
            *) printf '无效选项，请输入 0-7。\n'; continue ;;
        esac
        # A child shell keeps errexit active even when the menu catches failure.
        if bash "$SELF" "$action"; then result=0; else result=$?; fi
        [[ "$result" = 0 ]] || printf '本次操作未完成，请检查上方错误信息。\n'
        read -r -p '按回车返回菜单…' choice || return 0
    done
}

main() {
    local action=${1:-menu}
    [[ $# -eq 0 ]] || shift
    if [[ $# -gt 0 ]]; then
        [[ $# -eq 1 && "$1" = --yes ]] || fail '参数无效，请运行 xboard help。'
        case "$action" in update|restart|start|stop) ASSUME_YES=true ;; *) fail '此操作不支持 --yes。' ;; esac
    fi
    case "$action" in
        help|--help|-h) usage; return ;; version|--version) printf 'xboard-manager %s\n' "$MANAGER_VERSION"; return ;;
        menu|update|restart|start|stop|status|logs|uninstall|install) ;; *) fail '未知命令，请运行 xboard help。' ;;
    esac
    prepare
    case "$action" in
        menu) menu ;; update) update ;; restart) restart ;; start) start ;;
        stop) stop ;; status) show_status ;; logs) compose logs --tail 100 "$SERVICE" ;;
        uninstall) uninstall ;; install) install_cli ;;
    esac
}

main "$@"
