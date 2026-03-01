# 私有仓库脚本拉取

只需修改 **1 处**：

---

### 1. 添加拉取步骤

```yaml
- name: 拉取私有仓库
  uses: actions/checkout@v4
  with:
    repository: oyz6/scripts
    token: ${{ secrets.REPO_TOKEN }}
    path: .  
```

---

## 前提

- Secrets 中已配置 `REPO_TOKEN`
- 私有仓库结构中存在对应脚本
- 注意：> /dev/null 2>&1 会隐藏所有输出，调试时建议先去掉。
