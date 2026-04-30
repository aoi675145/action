# 私有仓库脚本拉取

## 1. 添加拉取步骤

在 GitHub Actions 工作流中加入：

```yaml
- name: 拉取私有仓库
  uses: actions/checkout@v4
  with:
    repository: ${{ github.repository_owner }}/私有仓库名
    token: ${{ secrets.REPO_TOKEN }}
    path: .
```

---

## 2. 修改执行路径

```bash
# 原来
python main.py

# 修改后
python scripts/FreeMcServer/main.py
```

---

## 3. 目录结构

私有仓库示例：

```
用户名/私有仓库名/
└── scripts/
    └── FreeMcServer/
        └── main.py
```

对应路径：

```
scripts/FreeMcServer/main.py
```

---

## 4. 前提条件

* 已创建 GitHub Token（需 `repo` `workflow` 权限）
* 已添加到仓库 Secrets：

  ```
  REPO_TOKEN
  ```

---

## 5. 说明

* `path: .` 表示拉取到当前仓库根目录
* 目录结构会被保留，因此需使用完整路径执行脚本
* 若修改 `path`，需同步调整执行路径

---
