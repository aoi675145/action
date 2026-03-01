# 私有仓库脚本拉取

只需修改 **2 处**：

---

### 1. 添加拉取步骤

```yaml
- name: 拉取私有仓库
  uses: actions/checkout@v4
  with:
    repository: 用户名/私库名
    token: ${{ secrets.REPO_TOKEN }}
    path: private
```

---

### 2. 修改脚本路径

```yaml
# 原路径
run: python scripts/xxx/xxx.py

# 新路径（加 private/ 前缀）
run: python private/scripts/xxx/xxx.py > /dev/null 2>&1
```

---

## 对比

| 项目 | 修改前 | 修改后 |
|------|--------|--------|
| 仓库 | 当前仓库 | `用户名/私库名` |
| 路径 | `scripts/xxx.py` | `private/scripts/xxx.py` |

---

## 前提

- Secrets 中已配置 `REPO_TOKEN`
- 私有仓库中存在对应脚本
- 注意：> /dev/null 2>&1 会隐藏所有输出，调试时建议先去掉。
