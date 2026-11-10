#!/usr/bin/env bash
# ensure-apt.sh —— Actions 里按需装系统包：镜像有就不碰 apt，源不可达就快速放弃，绝不把 job 拖死。
#
# 背景（2026-11-10 02:30 Godlike 那次 exit 124）：
#   ubuntu-24.04 runner 本来自带 xvfb/xauth/unzip/curl/wget/jq/Google Chrome，
#   但 workflow 里无条件 apt-get update，碰到镜像源滴漏（单次 read 不超时、整体一直挂着）
#   就变成 120s + 240s 两把超时，bash -e 直接把 job 判死，后面全 skipped。
# 背景（2026-11-10 05:0x vps8 / Magma 同时红，装依赖 5 分 28 秒）：
#   azure.archive.ubuntu.com:80 与 security.ubuntu.com 整段连不上，archive.ubuntu.com:80 也
#   Connection failed；同一台 runner 换到 https://archive.ubuntu.com:443 立刻能下。
#   → 现在先用 https 源；仍失败再换官方 archive 并重试一轮。
#
# 用法：
#   bash ensure-apt.sh --need "Xvfb xdotool" --pkgs "xvfb xdotool"
#   bash ensure-apt.sh --need-pkg "libnss3 xvfb" --pkgs "libnss3 xvfb"
#   bash ensure-apt.sh --need-pkg "xvfb fonts-wqy-microhei"   # --pkgs 可省略，自动回退
#
#   --need      检查 PATH 上的二进制（command -v）
#   --need-pkg  检查 apt 包是否已装（dpkg-query），适合没有同名二进制的库/字体包
#   --need-cmd  检查任意 shell 表达式
#   --pkgs      实际安装的 apt 包名；省略时用 --need-pkg / --need 的清单兜底
#
# 规则：
#   1. 全部满足 → 完全不碰 apt，打印一行 INFO 走人
#   2. 有缺失：先把 http 源升级成 https（80 端口在 runner 上时好时坏），再 5s 探测一次，
#      探测不通直接换官方 archive，不白等 update 超时
#   3. update 失败 / install 失败 → 换官方 https archive 源再试一轮
#   4. 两轮都不通 → warning 跳过 apt 继续跑，不阻断（依赖后面还能自检）
#   5. 装完重新自检，仍缺就 ::error:: 逐个点名（比让浏览器步骤报天书有用）
set -uo pipefail

NEED=""
NEED_PKGS=""
PKGS=""
TIME_LIMITS="${TIME_LIMITS:-45 60}"
NEED_CMDS=()
APT_SRC_GLOB="${APT_SRC_GLOB:-/etc/apt/sources.list /etc/apt/sources.list.d}"

while [ $# -gt 0 ]; do
  case "$1" in
    --need)      NEED="${2:-}";  shift 2 ;;
    --need-pkg)  NEED_PKGS="${2:-}"; shift 2 ;;
    --need-cmd)  NEED_CMDS+=("${2:-}"); shift 2 ;;
    --pkgs)      PKGS="${2:-}";  shift 2 ;;
    --timeouts)  TIME_LIMITS="${2:-}"; shift 2 ;;
    -h|--help)   sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "::error::ensure-apt.sh 未知参数: $1"; exit 2 ;;
  esac
done

# --pkgs 忘了传时自动回退：否则 apt-get install 拿到空包名会「成功」地什么都不装，
# 紧接着自检仍缺 → ::error:: 退出 1（2026-11-10 vps8 就是这样挂的）。
if [ -z "$(echo ${PKGS:-})" ]; then
  PKGS="$NEED_PKGS"
  if [ -n "$PKGS" ]; then
    echo "::warning::未传 --pkgs，按 --need-pkg 清单安装: ${PKGS}"
  elif [ -n "$NEED" ]; then
    PKGS="$NEED"
    echo "::warning::未传 --pkgs，按 --need 二进制名推断包名安装: ${PKGS}（大小写不一定对，建议显式传 --pkgs）"
  fi
fi

# 返回当前缺失项（二进制名 / pkg:包名 / <cmd:表达式>），全部满足则输出空
check() {
  local b pk c out=""
  for b in $NEED; do
    command -v "$b" >/dev/null 2>&1 || out="$out $b"
  done
  for pk in $NEED_PKGS; do
    dpkg-query -W -f='${Status}' "$pk" 2>/dev/null | grep -q "install ok installed" || out="$out pkg:$pk"
  done
  for c in ${NEED_CMDS[@]+"${NEED_CMDS[@]}"}; do
    [ -n "$c" ] || continue
    eval "$c" >/dev/null 2>&1 || out="$out <cmd:${c}>"
  done
  printf '%s' "${out# }"
}

# 遍历源文件（$1=回调名）——sources.list 与 sources.list.d/*.list|*.sources 都覆盖
each_src() {
  local cb="$1" target f
  for target in $APT_SRC_GLOB; do
    [ -e "$target" ] || continue
    if [ -d "$target" ]; then
      set -- "$target"/*.list "$target"/*.sources
    else
      set -- "$target"
    fi
    for f in "$@"; do
      [ -f "$f" ] || continue
      "$cb" "$f"
    done
  done
}

_host_one() {
  [ -n "${FIRST_HOST:-}" ] && return 0
  FIRST_HOST=$(grep -ohE 'https?://[^/[:space:]]+' "$1" 2>/dev/null | head -1)
}

src_host() {
  FIRST_HOST=""
  each_src _host_one
  printf '%s' "$FIRST_HOST"
}

# 5s 探测源是否活着：源整体不可达时直接换源，不白等两轮 update 超时
src_reachable() {
  local u code
  u="$(src_host)"
  [ -z "$u" ] && return 0
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -I "$u/" 2>/dev/null || true)
  printf '%s' "$code" | grep -qE '^[1-5][0-9][0-9]$'
}

_upgrade_one() {
  grep -q 'http://[^ ]*ubuntu\.com' "$1" 2>/dev/null || return 0
  sudo sed -i -E 's#http://([a-z0-9.-]*ubuntu\.com)#https://\1#g' "$1" || true
}

# http → https：2026-11-10 那批 runner 上 80 端口成段超时，443 正常，升级是零代价的
prefer_https_sources() {
  each_src _upgrade_one
}

_fix_one() {
  grep -qE 'azure\.archive\.ubuntu\.com|security\.ubuntu\.com|http://archive\.ubuntu\.com' "$1" 2>/dev/null || return 0
  if sudo sed -i -E \
       -e 's#https?://azure\.archive\.ubuntu\.com/ubuntu/?#https://archive.ubuntu.com/ubuntu/#g' \
       -e 's#https?://security\.ubuntu\.com/ubuntu/?#https://archive.ubuntu.com/ubuntu/#g' \
       -e 's#http://archive\.ubuntu\.com/ubuntu/?#https://archive.ubuntu.com/ubuntu/#g' \
       "$1"; then
    FIXED=$((FIXED + 1))
  fi
}

# 把 azure / security / http archive 统一换成官方 https archive
rescue_sources() {
  FIXED=0
  each_src _fix_one
  if [ "$FIXED" -gt 0 ]; then
    echo "::warning::已将 ${FIXED} 个源文件换成 https://archive.ubuntu.com"
  else
    echo "::warning::没有找到可替换的源（可能已经是官方 https）"
  fi
  return 0
}

apt_update() {
  local t
  for t in $TIME_LIMITS; do
    if timeout "$t" sudo apt-get update -qq \
         -o Acquire::Retries=1 \
         -o Acquire::http::Timeout=8 \
         -o Acquire::https::Timeout=8 \
         -o Acquire::ForceIPv4=true; then
      echo "[INFO] apt-get update 成功（${t}s 上限内）"
      return 0
    fi
    echo "::warning::apt-get update 超时/失败（${t}s 上限），换新连接重试"
  done
  return 1
}

apt_install() {
  # shellcheck disable=SC2086
  timeout 240 sudo apt-get install -y --no-install-recommends \
    -o Acquire::Retries=1 \
    -o Acquire::http::Timeout=10 \
    -o Acquire::https::Timeout=10 \
    -o DPkg::Lock::Timeout=120 \
    $PKGS
}

miss="$(check)"
if [ -z "$miss" ]; then
  # 依赖齐了也把源升到 https：后面第三方 action（fscarmen/warp-on-actions 等）
  # 自己跑 apt-get update，http(80) 一挂就是 5 分钟白等（2026-11-10 Godlike 312s）。
  prefer_https_sources
  echo "[INFO] 系统依赖已由镜像满足，跳过 apt（need: ${NEED:-无}${NEED_PKGS:+ / pkg: $NEED_PKGS}）"
  exit 0
fi

echo "::warning::镜像缺少:[${miss}] → 尝试 apt 安装: ${PKGS}"

if [ -z "$(echo ${PKGS:-})" ]; then
  echo "::warning::没有可安装的包名（缺 --pkgs/--need-pkg/--need 都为空），跳过 apt，只做最终自检"
else
  prefer_https_sources
  if ! src_reachable; then
    echo "::warning::首选源 $(src_host) 5s 内无响应，直接换官方 https archive，跳过 update 超时等待"
    rescue_sources
  fi

  if apt_update && apt_install; then
    echo "[INFO] apt install 完成: ${PKGS}"
  else
    echo "::warning::apt 未成功（多为镜像连接失败/下载超时），换官方 https archive 重试一轮"
    rescue_sources
    apt_update || echo "::warning::换源后 update 仍失败，仍尝试安装"
    if apt_install; then
      echo "[INFO] 换源后 apt install 完成: ${PKGS}"
    else
      echo "::warning::换源重试仍未成功，继续走自检"
    fi
  fi
fi

miss="$(check)"
if [ -n "$miss" ]; then
  echo "::error::依赖仍然缺失:[${miss}]（apt 两轮都没装上，检查包名或源）"
  exit 1
fi
echo "[INFO] 系统依赖自检通过"
