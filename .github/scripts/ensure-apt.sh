#!/usr/bin/env bash
# ensure-apt.sh —— Actions 里按需装系统包：镜像有就不碰 apt，源不可达就快速放弃，绝不把 job 拖死。
#
# 背景（2026-11-10 02:30 Godlike 那次 exit 124）：
#   ubuntu-24.04 runner 本来自带 xvfb/xauth/unzip/curl/wget/jq/Google Chrome，
#   但 workflow 里无条件 apt-get update，碰到镜像源滴漏（单次 read 不超时、整体一直挂着）
#   就变成 120s + 240s 两把超时，bash -e 直接把 job 判死，后面全 skipped。
#
# 用法：
#   bash ensure-apt.sh --need "Xvfb xdotool" --pkgs "xvfb xdotool"
#   bash ensure-apt.sh --need "Xvfb" --need-cmd 'fc-list | grep -qi wqy' \
#        --pkgs "xvfb fonts-wqy-microhei"
#   bash ensure-apt.sh --need-pkg "libnss3 libxss1 xvfb" --pkgs "libnss3 libxss1 xvfb"
#
#   --need    检查 PATH 上的二进制（command -v）
#   --need-pkg 检查 apt 包是否已装（dpkg-query），适合没有同名二进制的库/字体包
#   --need-cmd 检查任意 shell 表达式
#
# 规则：
#   1. --need 的二进制全在、--need-cmd 全通过 → 完全不碰 apt，打印一行 INFO 走人
#   2. 有缺失才 apt-get update：单次 90s 上限，失败换一条新连接再来 120s
#   3. 两把都不通 → warning 跳过 apt 继续跑，不阻断（依赖后面还能自检）
#   4. 装完重新自检，仍缺就 ::error:: 逐个点名（比让浏览器步骤报天书有用）
#   5. apt install 失败但自检通过（镜像自带）→ 只 warning
set -uo pipefail

NEED=""
NEED_PKGS=""
PKGS=""
TIME_LIMITS="90 120"
NEED_CMDS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --need)      NEED="${2:-}";  shift 2 ;;
    --need-pkg)  NEED_PKGS="${2:-}"; shift 2 ;;
    --need-cmd)  NEED_CMDS+=("${2:-}"); shift 2 ;;
    --pkgs)      PKGS="${2:-}";  shift 2 ;;
    --timeouts)  TIME_LIMITS="${2:-}"; shift 2 ;;
    -h|--help)   sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "::error::ensure-apt.sh 未知参数: $1"; exit 2 ;;
  esac
done

# --pkgs 忘了传时自动回退：否则 apt-get install 拿到空包名会「成功」地什么都不装，
# 紧接着自检仍缺 → ::error:: 退出 1（2026-11-10 vps8 就是这样挂的，44 个 workflow 全这个写法）。
if [ -z "$(echo ${PKGS:-})" ]; then
  PKGS="$NEED_PKGS"
  if [ -n "$PKGS" ]; then
    echo "::warning::未传 --pkgs，按 --need-pkg 清单安装: ${PKGS}"
  elif [ -n "$NEED" ]; then
    PKGS="$NEED"
    echo "::warning::未传 --pkgs，按 --need 二进制名推断包名安装: ${PKGS}（大小写不一定对，建议显式传 --pkgs）"
  fi
fi

# 返回当前缺失项（二进制名 / cmd:<表达式>），全部满足则输出空
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

miss="$(check)"
if [ -z "$miss" ]; then
  echo "[INFO] 系统依赖已由镜像满足，跳过 apt（need: ${NEED:-无}${NEED_PKGS:+ / pkg: $NEED_PKGS}）"
  exit 0
fi

echo "::warning::镜像缺少:[${miss}] → 尝试 apt 安装: ${PKGS}"
apt_ok=0
if [ -z "$(echo ${PKGS:-})" ]; then
  echo "::warning::没有可安装的包名（缺 --pkgs/--need-pkg/--need 都为空），跳过 apt，只做最终自检"
else
  for t in $TIME_LIMITS; do
    if timeout "$t" sudo apt-get update -qq \
         -o Acquire::Retries=1 \
         -o Acquire::http::Timeout=8 \
         -o Acquire::https::Timeout=8 \
         -o Acquire::ForceIPv4=true; then
      apt_ok=1
      echo "[INFO] apt-get update 成功（${t}s 上限内）"
      break
    fi
    echo "::warning::apt-get update 超时/失败（${t}s 上限），换新连接重试"
  done

  if [ "$apt_ok" = 1 ]; then
    # shellcheck disable=SC2086
    if sudo apt-get install -y --no-install-recommends \
         -o Acquire::Retries=2 \
         -o Acquire::http::Timeout=15 \
         -o Acquire::https::Timeout=15 \
         -o DPkg::Lock::Timeout=120 \
         $PKGS; then
      echo "[INFO] apt install 完成: ${PKGS}"
    else
      echo "::warning::apt install 未完全成功，继续走自检"
    fi
  else
    echo "::warning::apt 源全程不可达，跳过 apt，直接用镜像自带组件"
  fi
fi

miss="$(check)"
if [ -n "$miss" ]; then
  echo "::error::依赖仍然缺失:[${miss}]（apt 装完仍缺，检查包名或源）"
  exit 1
fi
echo "[INFO] 系统依赖自检通过"
