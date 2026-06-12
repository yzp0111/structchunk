# 安装

[English](../installation.md)

## 环境要求

- **Python**：3.9 或更新版本（structchunk 仅在使用类型注解时使用了 `from __future__ import annotations` 和 `int | str` 联合语法，因此兼容 3.9+）
- **操作系统**：任意（纯 Python，无平台相关代码；可选的 `os.register_at_fork` 在不支持该功能的平台上自动变为空操作）
- **磁盘空间**：不足 1 MB

## 从 PyPI 安装

对大多数用户来说，这是最简单的安装方式：

```bash
pip install structchunk
```

## 从源码安装

当你需要最新的未发布代码或想要修改 structchunk 时使用此方式：

```bash
git clone https://github.com/yzp0111/structchunk.git
cd structchunk
pip install -e ".[test]"
```

`[test]` 额外选项会安装 `pytest>=7.0`，以便你可以在本地运行测试套件。

## 使用 uv 安装

[uv](https://github.com/astral-sh/uv) 是一个快速的 Python 包管理器。如果你已安装它：

```bash
uv pip install structchunk
```

或者在 uv 管理的虚拟环境中从源码安装：

```bash
git clone https://github.com/yzp0111/structchunk.git
cd structchunk
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[test]"
```

## 验证安装

安装完成后，确认包可以导入并正确显示版本号：

```bash
python -c "import structchunk; print(structchunk.__version__)"
```

预期输出：`0.1.0`

你还可以验证 CLI 是否可用：

```bash
structchunk --help
```

## 可选：从源码构建

如需自行构建 wheel 和 sdist（例如用于离线安装）：

```bash
git clone https://github.com/yzp0111/structchunk.git
cd structchunk
python -m pip install build
python -m build
```

此命令会在 `dist/` 目录下生成 `structchunk-0.1.0-py3-none-any.whl` 和 `structchunk-0.1.0.tar.gz`。使用以下命令安装 wheel：

```bash
pip install dist/structchunk-0.1.0-py3-none-any.whl
```

## 下一步

- [快速开始](quickstart.md) — 你的第一个分块
- [算法](algorithms.md) — 选择哪种算法
- [API 参考](api.md) — 每个公开函数、类和配置字段
