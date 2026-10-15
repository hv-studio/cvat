# CVAT 安装指南

本文介绍在 Ubuntu / Kubuntu 22.04、24.04（x86_64 / amd64）上安装 CVAT，并接入 SAM ViT-B/L/H。
普通标注功能不需要 GPU；SAM GPU 部署需要 NVIDIA 显卡、兼容驱动和 NVIDIA Container Toolkit。
已有可用环境时，可跳过对应步骤。

仅安装 CVAT：完成第 2、3.1、4 节。启用 SAM：依次完成第 2～7 节，并在镜像准备和部署时选择相同的 A/B 路线。

- [1. 安装路线与资源](#1-安装路线与资源)
- [2. 安装 Docker](#2-安装-docker)
- [3. 获取项目与准备镜像](#3-获取项目与准备镜像)
- [4. 启动 CVAT](#4-启动-cvat)
- [5. 准备 SAM 运行环境](#5-准备-sam-运行环境)
- [6. 部署 SAM](#6-部署-sam)
- [7. 验证与使用](#7-验证与使用)
- [8. 日常管理与镜像分享](#8-日常管理与镜像分享)
- [9. 故障排查](#9-故障排查)

## 1. 安装路线与资源

Docker **镜像**是可分发的运行环境，**容器**是由镜像启动的程序实例，**数据卷**用于保存数据库和上传数据。
Docker Compose 负责启动 CVAT 的多个服务；Nuclio 负责运行 SAM，`nuctl` 是它的命令行工具。

SAM 部署有两条路线，镜像准备与部署步骤应选择同一路线：

| 路线 | 适用情况 | 操作 |
| --- | --- | --- |
| A：正常构建 | 需要从源码构建 SAM 环境 | 准备辅助镜像，再运行部署脚本 |
| B：预构建镜像 | 已有完整镜像包，希望跳过依赖安装 | 导入完整包，再部署已构建的镜像 |

镜像包下载：[百度网盘](https://pan.baidu.com/s/1wr1nPCj7GOxt-3YuCrp0VQ)，提取码 **`pjnj`**。
下载后保留原文件名，放入项目根目录的 `images/`，无需解压。

| 文件 | 用途 |
| --- | --- |
| `nuclio-alpine-3.20.tar` | 路线 A：Nuclio 本地存储辅助镜像 |
| `uhttpc-0.0.3-amd64.tar` | 路线 A：构建时使用的健康检查辅助镜像 |
| `cvat-sam-nuclio-amd64.tar` | 路线 B：SAM、配套 CVAT UI、Nuclio Dashboard 和 Alpine 镜像 |

路线 B 只需下载第三个包。上述包适用于 `linux/amd64`，**不含 checkpoint、ONNX decoder、CVAT 后端镜像或标注数据**。
旧版完整包可能缺少配套 UI 和自动选型代码，使用前核对发布说明；当前完整包的导出方式见第 8.3 节。
从空白系统安装仍需准备 Docker、驱动等依赖；权重见第 5 节。请为镜像、构建缓存、权重和数据集预留足够磁盘空间。

命令使用 Bash 执行，除系统安装外均在项目根目录运行。多行命令可整块复制；`sudo` 输入密码时不显示字符属于正常现象。
`$HOME/Projects` 和项目内 `weights/sam` 仅为可替换的目录示例。个人路径写入被 Git 忽略的本地配置，不写入仓库模板。

## 2. 安装 Docker

### 2.1 软件源与基础工具

先检查已有环境：

```bash
docker --version
docker compose version
docker info
```

如果均正常，可跳过安装，按需配置第 2.3 节的镜像加速。已有 Docker 包冲突时，参照
[官方 Ubuntu 安装说明](https://docs.docker.com/engine/install/ubuntu/)处理，不要删除 Docker 数据目录。

不同下载渠道需分别配置：

| 用途 | 地址 |
| --- | --- |
| Ubuntu apt 包 | `https://mirrors.nju.edu.cn/ubuntu/` |
| Docker Engine / Compose apt 包 | `https://mirrors.nju.edu.cn/docker-ce/linux/ubuntu` |
| SAM 构建中的 pip 包 | `https://mirrors.nju.edu.cn/pypi/web/simple` |
| Docker Hub 加速示例 | `https://docker.1ms.run` |

**南大的 `docker-ce/` 是软件包源，不能填入 Docker 的 `registry-mirrors`。**
Docker Hub 加速也不覆盖 `gcr.io` 或 `quay.io`。

下面的命令备份并将 Ubuntu 官方源替换为南大源，兼容 `sources.list` 和 `ubuntu.sources`。
已经配置好南大源时跳过；其他第三方 Ubuntu 源可通过系统“软件源”设置修改。

```bash
sudo /usr/bin/python3 - <<'PY'
import re
import shutil
from datetime import datetime
from pathlib import Path

stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
for path in (Path('/etc/apt/sources.list'), Path('/etc/apt/sources.list.d/ubuntu.sources')):
    if not path.exists():
        continue
    old = path.read_text()
    new = re.sub(
        r'https?://(?:(?:[\w-]+\.)?archive|security)\.ubuntu\.com/ubuntu/?',
        'https://mirrors.nju.edu.cn/ubuntu/', old,
    )
    if new != old:
        backup = path.with_name(path.name + '.bak-' + stamp)
        shutil.copy2(path, backup)
        path.write_text(new)
        print(f'已更新 {path}；备份：{backup}')
PY
```

安装基础工具：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git nano python3 python3-yaml
```

### 2.2 Docker Engine 与 Compose

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://mirrors.nju.edu.cn/docker-ce/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

. /etc/os-release
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://mirrors.nju.edu.cn/docker-ce/linux/ubuntu %s stable\n' \
  "$(dpkg --print-architecture)" "${UBUNTU_CODENAME:-$VERSION_CODENAME}" \
  | sudo tee /etc/apt/sources.list.d/docker.list

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

**注销并重新登录**，使 Docker 用户组权限生效，再运行 `docker info` 和 `docker compose version`。
后续 Docker / nuctl 命令使用普通用户执行。Docker 组具有管理宿主机容器的权限，仅向可信用户开放。

### 2.3 Docker Hub 镜像加速（可选）

以 `https://docker.1ms.run` 为例，可按网络条件替换为其他可用的 Docker Hub 加速服务。
编辑前备份已有配置：

```bash
sudo install -m 0755 -d /etc/docker
if sudo test -f /etc/docker/daemon.json; then
  sudo cp -a /etc/docker/daemon.json "/etc/docker/daemon.json.bak-$(date +%Y%m%d-%H%M%S)"
fi
sudo nano /etc/docker/daemon.json
```

新文件可使用以下内容；已有文件则只增加或修改 `registry-mirrors` 字段，保留 `runtimes` 等其他字段。
JSON 不支持注释，字段间需要逗号，最后一个字段后不加逗号。

```json
{
  "registry-mirrors": ["https://docker.1ms.run"]
}
```

Nano 中按 `Ctrl+O`、回车保存，再按 `Ctrl+X` 退出。校验通过后重启 Docker，并检查配置：

```bash
sudo dockerd --validate --config-file /etc/docker/daemon.json \
  && sudo systemctl restart docker
docker info --format '{{json .RegistryConfig.Mirrors}}'
docker pull ubuntu:22.04
```

输出应包含配置的地址。重启会短暂影响已有容器；镜像仍按 `ubuntu:22.04` 等原名称拉取。
第三方加速服务的可用性取决于网络和服务状态。Quay / GCR 超时时，使用本地包或配置
[Docker daemon 代理](https://docs.docker.com/engine/daemon/proxy/)；仅设置终端代理不一定影响 Docker 服务。

## 3. 获取项目与准备镜像

### 3.1 项目目录与本地配置

已有源码时直接进入项目根目录。新下载可执行：

```bash
mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
git clone https://github.com/hv-studio/cvat.git
cd cvat
mkdir -p images
```

也可使用有权限获取的源码包，解压后进入包含 `docker-compose.yml` 的目录。
本文使用被 Git 忽略的 `docker-compose.override.yml` 保存机器配置。为统一后续命令，新安装创建空配置；已有文件保留：

```bash
if [ ! -e docker-compose.override.yml ]; then
  printf '{}\n' > docker-compose.override.yml
fi
```

仅在需要时增加网络等配置，网段冲突见第 9 节。使用显式 `-f` 参数时，必须同时列出这个覆盖文件。
保持默认项目名 `cvat`，以匹配部署脚本使用的网络 `cvat_cvat`。

### 3.2 路线 A：准备构建镜像

优先导入 `images/` 下的两个辅助包；没有包但已有对应镜像时直接使用，否则在线拉取。
**现场拉取 GCR 镜像必须确保 Docker 能访问 `gcr.io`。**

```bash
(
  set -euo pipefail
  if [ -f images/nuclio-alpine-3.20.tar ]; then
    docker load -i images/nuclio-alpine-3.20.tar
  elif ! docker image inspect gcr.io/iguazio/alpine:3.20 >/dev/null 2>&1; then
    docker pull --platform linux/amd64 gcr.io/iguazio/alpine:3.20
  fi

  if [ -f images/uhttpc-0.0.3-amd64.tar ]; then
    docker load -i images/uhttpc-0.0.3-amd64.tar
  elif ! docker image inspect gcr.io/iguazio/uhttpc:0.0.3-amd64 >/dev/null 2>&1; then
    docker pull --platform linux/amd64 gcr.io/iguazio/uhttpc:0.0.3-amd64
  fi

  for sam_build_image in \
    ubuntu:22.04 \
    quay.io/nuclio/dashboard:1.16.3-amd64 \
    quay.io/nuclio/handler-builder-python-onbuild:1.16.3-amd64; do
    if ! docker image inspect "$sam_build_image" >/dev/null 2>&1; then
      docker pull --platform linux/amd64 "$sam_build_image"
    fi
  done
)
```

其中 Alpine 用于 Nuclio 本地存储，`uhttpc` 提供健康检查工具，handler-builder 提供 Python 运行组件，
Dashboard 提供模型管理服务。构建配置使用 `noBaseImagesPull: true`，准备好镜像后不会强制刷新构建辅助镜像。

### 3.3 路线 B：导入完整镜像包

```bash
docker load -i images/cvat-sam-nuclio-amd64.tar
docker image inspect \
  cvat.pth.facebookresearch.sam.vit_h:latest-gpu \
  cvat/ui:dev \
  quay.io/nuclio/dashboard:1.16.3-amd64 \
  gcr.io/iguazio/alpine:3.20 \
  --format '{{join .RepoTags ", "}}  {{.Os}}/{{.Architecture}}'
```

确认四个镜像均存在，架构为 `linux/amd64`。此路线不需要单独准备 `uhttpc` 或 handler-builder 镜像。
完成第 4～5 节后，执行第 6.2 节的免构建部署。

## 4. 启动 CVAT

启动 CVAT 和 Nuclio：

```bash
docker compose \
  -f docker-compose.yml \
  -f components/serverless/docker-compose.serverless.yml \
  -f docker-compose.override.yml \
  up -d
```

`up -d` 创建并在后台运行服务，自动下载缺少的 CVAT、数据库等镜像。
仅使用普通标注功能时，也可按此方式启动，跳过后续 SAM 步骤。

默认使用本地的 `cvat/server:dev` 和 `cvat/ui:dev`，缺失时拉取发布镜像；本地源码修改不会自动进入镜像。
路线 B 导入的 `cvat/ui:dev` 含配套 SAM 插件，不要再用在线 `pull` 覆盖它。
需要运行修改后的前后端时，参照[源码构建说明](site/content/en/docs/administration/community/basics/installation.md#how-to-pullbuildupdate-cvat-images)。
使用其他发布版本时，保持源码、server 和 UI 版本配套。

检查启动状态，等待初始化完成：

```bash
docker ps
docker logs --tail 80 cvat_server
```

首次安装创建管理员，按提示填写账号信息；已有账号则跳过：

```bash
docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'
```

用 Chrome 打开 <http://localhost:8080/> 并登录。默认路由按 `localhost` 匹配。
如需局域网访问，在项目 `.env` 中将 `CVAT_HOST` 设置为服务器 IP 或域名，不带协议、端口或路径，再执行启动命令。
Nuclio Dashboard 默认不对宿主机开放 8070 端口，不影响 CVAT 使用 SAM。

## 5. 准备 SAM 运行环境

### 5.1 NVIDIA GPU 支持

先执行 `nvidia-smi`，确认主机驱动正常；失败时通过系统“附加驱动”安装适合显卡的 NVIDIA 驱动并重启。
网盘预构建包使用 CUDA 13.0，需要 CUDA 13.x 兼容驱动，通常为 580 系列或更新。
自行构建时以实际 PyTorch / CUDA 版本为准。宿主机无需额外安装完整 CUDA Toolkit。

安装 NVIDIA Container Toolkit，让 Docker 可以使用 GPU。该软件由 NVIDIA 仓库提供：

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

重启 Docker 后，按第 4 节重新执行 `up -d`。选择对应镜像验证 GPU：

```bash
# 路线 A
docker run --rm --pull=never --gpus all ubuntu:22.04 nvidia-smi
```

```bash
# 路线 B
docker run --rm --pull=never --gpus all --entrypoint nvidia-smi \
  cvat.pth.facebookresearch.sam.vit_h:latest-gpu
```

应显示显卡信息。`--rm` 只删除测试容器，保留镜像。

### 5.2 nuctl

安装与仓库 Dashboard 匹配的 `1.16.3` 版本：

```bash
curl -fL \
  https://github.com/nuclio/nuclio/releases/download/1.16.3/nuctl-1.16.3-linux-amd64 \
  -o /tmp/nuctl-1.16.3-linux-amd64
sudo install -m 0755 /tmp/nuctl-1.16.3-linux-amd64 /usr/local/bin/nuctl
nuctl version
```

GitHub 无法访问时，可在其他机器下载同一文件后复制过来，再执行 `sudo install`。

### 5.3 SAM 权重与路径

使用 **Meta 原版 SAM checkpoint**，按需下载一种或多种：

| 类型 | 建议文件名 | 官方下载 |
| --- | --- | --- |
| `vit_b` | `sam-b.pth` | [ViT-B](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth) |
| `vit_l` | `sam-l.pth` | [ViT-L](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_l_0b3195.pth) |
| `vit_h` | `sam-h.pth` | [ViT-H](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth) |

例如在项目根目录下载 ViT-B：

```bash
mkdir -p weights/sam
curl -fL --retry 3 -C - \
  https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth \
  -o weights/sam/sam-b.pth
```

已有正确权重时跳过下载。Transformers 的 `model.safetensors`、其他封装的 `.pt`、SAM2/SAM3 权重不能直接替代。
在权重目录创建 `cvat.json`，指定类型和相对该目录的 checkpoint 路径：

```json
{
  "checkpoint": "sam-b.pth",
  "type": "vit_b"
}
```

在项目根目录创建并编辑 `.env.sam`：

```bash
if [ ! -e .env.sam ]; then
  cp serverless/pytorch/facebookresearch/sam/weights.env.example .env.sam
fi
nano .env.sam
```

将 `SAM_WEIGHTS_DIR` 设置为权重目录的绝对路径，例如用 `realpath weights/sam` 获取路径后填入。
配置格式如下（替换示例路径）：

```bash
SAM_WEIGHTS_DIR="/absolute/path/to/cvat/weights/sam"
SAM_RESTART_POLICY=no
```

该值应解析为权重所在目录的绝对路径，不包含文件名；路径含空格时使用引号。保存后检查：

```bash
(
  source .env.sam
  cat "$SAM_WEIGHTS_DIR/cvat.json"
  ls -lh "$SAM_WEIGHTS_DIR"/*.pth
)
```

`.env.sam` 被 Git 忽略，部署脚本将目录只读挂载到 `/opt/weights/sam`。
已导出的非空 `SAM_WEIGHTS_DIR` 环境变量优先于文件；执行 `unset SAM_WEIGHTS_DIR` 可恢复使用文件配置。
模型运行期间需保持该目录可访问，无需修改仓库中的权重路径模板。

### 5.4 配套 decoder 与前端

每种模型类型需要对应的 ONNX decoder。按 [SAM 导出说明](serverless/pytorch/facebookresearch/sam/README.md#export-matching-decoders)
生成到权重目录的 `onnx/` 下；已有 SAM 镜像时可用临时容器导出，否则先准备说明中列出的 Python 依赖。
文件名为 `decoder-vit_b.onnx`、`decoder-vit_l.onnx` 或 `decoder-vit_h.onnx`，前端根据服务返回的
`model_type` 自动选择。同一类型的 checkpoint 共用 decoder，不比较权重内容。

**SAM 后端和 CVAT UI 均须使用本仓库配套代码。** 旧镜像包和官方发布的 UI 不包含此自动选型协议，
仅导入旧包或挂载 ONNX 不会更新代码。首次安装需准备对应版本的镜像；UI 源码构建见第 4 节链接。

生成 decoder 后，启动 CVAT 时增加静态文件挂载：

```bash
docker compose --env-file .env.sam \
  -f docker-compose.yml \
  -f components/serverless/docker-compose.serverless.yml \
  -f components/serverless/docker-compose.sam.yml \
  -f docker-compose.override.yml \
  up -d
```

此配置仅向浏览器提供 `onnx/`，不暴露 checkpoint。若还在 `.env` 设置了 `CVAT_HOST` 等变量，
将 `--env-file .env.sam` 改为 `--env-file .env --env-file .env.sam`。

## 6. 部署 SAM

### 6.1 路线 A：构建并部署

完成第 3.2 节的镜像准备后执行：

```bash
./serverless/deploy_gpu.sh serverless/pytorch/facebookresearch/sam/nuclio
```

构建使用南大 Ubuntu 和 PyPI 源，SAM 从 PyPI 安装为 `segment-anything`。
最小 Ubuntu 镜像先通过 HTTP 源安装 CA 证书，保留仓库签名校验，再切换到 HTTPS。
配置说明见 [SAM README](serverless/pytorch/facebookresearch/sam/README.md)。

PyTorch/CUDA 下载及镜像解包可能耗时较长。停留在 `Building docker image` 时，可在另一终端查看进度：

```bash
docker buildx history ls
read -r -p '请输入对应构建的 REF：' sam_build_ref
docker buildx history logs "$sam_build_ref" --progress plain
```

`history` 需要较新的 Buildx。构建日志不等同于 Dashboard 日志；暂时没有输出不代表失败。

### 6.2 路线 B：部署预构建镜像

完成第 3.3 节的导入后，使用以下命令。它从仓库模板生成临时配置，保留模型元数据、GPU 和权重挂载，
移除构建项，再运行已导入的镜像。**此路线不运行 `deploy_gpu.sh`。**
镜像必须包含第 5.4 节所述的配套后端；固定 ViT-H 版本的旧归档不能直接用于自动切换。

```bash
(
  set -euo pipefail
  if [ -f .env.sam ]; then
    if [ -z "${SAM_WEIGHTS_DIR:-}" ]; then
      SAM_WEIGHTS_DIR=$(source .env.sam; printf '%s' "${SAM_WEIGHTS_DIR:-}")
    fi
    if [ -z "${SAM_RESTART_POLICY:-}" ]; then
      SAM_RESTART_POLICY=$(source .env.sam; printf '%s' "${SAM_RESTART_POLICY:-}")
    fi
  fi
  SAM_RESTART_POLICY=${SAM_RESTART_POLICY:-always}
  export SAM_WEIGHTS_DIR SAM_RESTART_POLICY

  sam_runtime_dir="$(mktemp -d "${TMPDIR:-/tmp}/cvat-sam-runtime.XXXXXX")"
  trap 'rm -rf -- "$sam_runtime_dir"' EXIT

  /usr/bin/python3 - "$sam_runtime_dir/function.yaml" <<'PY'
import os
import sys
from pathlib import Path

import yaml

weights_dir = Path(os.environ['SAM_WEIGHTS_DIR']).resolve(strict=True)
template = Path('serverless/pytorch/facebookresearch/sam/nuclio/function-gpu.yaml')
config = yaml.safe_load(template.read_text(encoding='utf-8'))
config['metadata']['namespace'] = 'nuclio'
spec = config['spec']
del spec['build']
spec['image'] = 'cvat.pth.facebookresearch.sam.vit_h:latest-gpu'
spec['platform']['attributes']['restartPolicy']['name'] = os.environ['SAM_RESTART_POLICY']
for entry in spec['volumes']:
    if entry['volume']['name'] == 'sam-weights':
        entry['volume']['hostPath']['path'] = str(weights_dir)

Path(sys.argv[1]).write_text(
    yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding='utf-8',
)
PY

  docker image inspect cvat.pth.facebookresearch.sam.vit_h:latest-gpu >/dev/null
  docker image inspect gcr.io/iguazio/alpine:3.20 >/dev/null
  docker network inspect cvat_cvat >/dev/null

  nuctl create project cvat --platform local --namespace nuclio
  nuctl deploy pth-facebookresearch-sam-vit-h \
    --project-name cvat \
    --platform local \
    --namespace nuclio \
    --file "$sam_runtime_dir/function.yaml" \
    --run-image cvat.pth.facebookresearch.sam.vit_h:latest-gpu \
    --env CVAT_FUNCTIONS_REDIS_HOST=cvat_redis_ondisk \
    --env CVAT_FUNCTIONS_REDIS_PORT=6666 \
    --platform-config '{"attributes": {"network": "cvat_cvat"}}'
)
```

此步骤需要系统 Python 的 `python3-yaml` 包。部署会加载权重，但不应重新安装 apt/pip 依赖。
必须移除 `spec.build` 且不传 `--path`；仅添加 `--run-image` 不能保证跳过构建。
函数名 `pth-facebookresearch-sam-vit-h` 是前端接口约定，保持不变。

## 7. 验证与使用

检查函数及 GPU 状态：

```bash
nuctl get function --platform local --namespace nuclio
docker logs --tail 100 nuclio-nuclio-pth-facebookresearch-sam-vit-h
docker exec nuclio-nuclio-pth-facebookresearch-sam-vit-h \
  python3 -c 'import torch; print("torch:", torch.__version__); print("CUDA:", torch.version.cuda); print("GPU:", torch.cuda.is_available())'
```

函数应为 `ready`、副本数 `1/1`，GPU 检查输出 `True`，日志中没有模型加载错误。
随后在真实图片上验证交互：

1. 创建含图片或视频的 Task，设置标签并进入 Job。
2. 打开左侧 **Magic wand / AI tools → Interactors**，选择标签和 **Segment Anything**。
3. 保留像素掩码时，关闭 **Convert masks to polygons**。
4. 点击 **Interact**，左键添加正点，右键添加负点。
5. 点击 **Done** 完成形状，再保存 Job。

修正已有标注时，可直接编辑掩码，或用 SAM 生成替代结果，保留原对象所需属性后删除旧形状，避免重复标注。
操作说明见 [AI Tools](site/content/en/docs/annotation/auto-annotation/ai-tools.md)。

YTVIS 数据需先转换为受支持的逐帧格式，例如 COCO instances；上传图片后，通过 **Import annotations / COCO 1.0**
导入对应标注，保持文件名和标签一致。SAM 不自动维护跨帧身份，需要另行保存视频、帧和实例 ID 的映射。
先验证一个小任务的导入、编辑、导出，再批量处理。

## 8. 日常管理与镜像分享

### 8.1 启动、停止与数据

恢复服务时执行第 4 节的 `up -d`；使用配套 decoder 时改用第 5.4 节命令，以保留静态文件挂载。
然后按需启动已部署的 SAM 容器：

```bash
docker start nuclio-nuclio-pth-facebookresearch-sam-vit-h
```

临时停止：

```bash
docker stop nuclio-nuclio-pth-facebookresearch-sam-vit-h
docker compose \
  -f docker-compose.yml \
  -f components/serverless/docker-compose.serverless.yml \
  -f docker-compose.override.yml \
  stop
```

未部署 SAM 时跳过针对该容器的命令。SAM 函数由 Nuclio 创建，需要单独管理；正常启动无需重新构建。
`stop` 保留数据。**不要用 `down -v` 或 `docker volume prune` 排查安装问题**，这些操作可能删除标注数据。
任务迁移使用 CVAT 的备份、导出功能；镜像归档不代替数据备份。

切换 SAM 模型时，先确认对应 decoder 已导出，再修改权重目录中的 `cvat.json`，执行以下命令并刷新网页：

```bash
docker restart nuclio-nuclio-pth-facebookresearch-sam-vit-h
```

配置在 SAM 初始化时读取。此流程要求前后端已完成第 5.4 节的代码和挂载配置，不会自动更新旧容器内的代码。
若替换了同名 ONNX 文件，需强制刷新网页以更新浏览器缓存。

### 8.2 关闭开机自动启动（可选）

默认重启策略为 `always`，Docker 启动时会恢复容器。需要完全手动启动时，
在 `docker-compose.override.yml` 中为每个服务设置 `restart: "no"`。
下面的命令保留其他本地配置，并更新所有 CVAT/Nuclio 服务：

```bash
/usr/bin/python3 - <<'PY'
from pathlib import Path
import yaml

path = Path('docker-compose.override.yml')
config = yaml.safe_load(path.read_text()) or {}
services = config.setdefault('services', {})
for filename in ('docker-compose.yml', 'components/serverless/docker-compose.serverless.yml'):
    for name in yaml.safe_load(Path(filename).read_text())['services']:
        services.setdefault(name, {})['restart'] = 'no'
path.write_text(yaml.safe_dump(config, sort_keys=False))
PY
```

启动时将 `docker-compose.override.yml` 放在所有 `-f` 参数的最后，以覆盖 serverless 配置。
同时在 `.env.sam` 中设置 `SAM_RESTART_POLICY=no`，使后续两条 SAM 部署路线使用手动启动策略。
已有容器可直接更新策略，无需停止服务：

```bash
docker ps -aq --filter label=com.docker.compose.project=cvat \
  | xargs -r docker update --restart=no
docker update --restart=no nuclio-nuclio-pth-facebookresearch-sam-vit-h
```

未部署 SAM 时跳过最后一条。Docker 服务本身可以继续随系统启动；上述 CVAT 和 SAM 容器会等待手动启动。
`no` 同时关闭容器异常退出后的自动重启，启动与关闭命令仍使用第 8.1 节所述方式。

### 8.3 导出完整 SAM 镜像包

验证部署成功后，在项目根目录执行；如需保留旧归档，先更换输出文件名：

```bash
mkdir -p images
docker save -o images/cvat-sam-nuclio-amd64.tar \
  cvat.pth.facebookresearch.sam.vit_h:latest-gpu \
  cvat/ui:dev \
  quay.io/nuclio/dashboard:1.16.3-amd64 \
  gcr.io/iguazio/alpine:3.20
(
  cd images
  sha256sum cvat-sam-nuclio-amd64.tar > cvat-sam-nuclio-amd64.tar.sha256
)
```

分享镜像包、校验文件、对应版本的项目源码和权重下载地址，同时注明镜像架构及 PyTorch/CUDA 兼容要求。
接收者若拿到校验文件，可在 `images/` 中执行 `sha256sum -c cvat-sam-nuclio-amd64.tar.sha256`，再按路线 B 部署。
另行提供权重目录中的 `cvat.json` 和 `onnx/`，或让接收者按第 5 节生成 decoder。

使用 `docker save/load`，不要使用 `docker export/import`。镜像不包含挂载的权重或函数注册状态，
接收者仍需配置自己的 `.env.sam` 并部署。完全离线安装还需另行准备 Compose 所需全部镜像及主机安装包。

### 8.4 在 Google Cloud Shell 下载 GCR 辅助包

无法直接访问 GCR，且没有现成辅助包时，在 **Google Cloud Shell** 执行：

```bash
(
  set -euo pipefail
  docker pull --platform linux/amd64 gcr.io/iguazio/alpine:3.20
  docker pull --platform linux/amd64 gcr.io/iguazio/uhttpc:0.0.3-amd64
  docker save -o "$HOME/nuclio-alpine-3.20.tar" gcr.io/iguazio/alpine:3.20
  docker save -o "$HOME/uhttpc-0.0.3-amd64.tar" gcr.io/iguazio/uhttpc:0.0.3-amd64
)
cloudshell download "$HOME/nuclio-alpine-3.20.tar"
cloudshell download "$HOME/uhttpc-0.0.3-amd64.tar"
```

浏览器下载后，将文件放到项目 `images/`，按第 3.2 节导入。也可用 Cloud Shell 的 **Download file** 菜单下载。

## 9. 故障排查

### 9.1 网页无法访问

```bash
docker ps -a
docker logs --tail 100 cvat_server
docker logs --tail 100 traefik
curl --noproxy '*' -I http://localhost:8080/
ss -ltn '( sport = :8080 )'
```

检查容器是否反复退出、8080 是否被占用、浏览器是否为本地地址绕过代理，以及访问主机名是否匹配 `CVAT_HOST`。

VPN 或局域网与 Docker 网段冲突时，用 `ip -4 route` 和 `docker network inspect cvat_cvat` 检查路由。
在 `docker-compose.override.yml` 中合并以下配置，将 `<unused-subnet>` 替换为确认未占用的私有 CIDR 网段：

```yaml
networks:
  cvat:
    ipam:
      config:
        - subnet: <unused-subnet>
```

已有网络需要重建才能应用新网段：使用第 4 节相同的三个 `-f` 参数先执行 `down`（不加 `-v`），再执行 `up -d`。
若已有 SAM 函数连接该网络，先删除其部署，网络重建后按第 6 节重新部署。保留 CVAT 数据卷和权重。

### 9.2 镜像拉取与构建失败

| 现象 | 处理 |
| --- | --- |
| `gcr.io` 超时 | 按第 3 节导入本地包，或处理 Docker daemon 的网络/代理；Docker Hub 加速不代理 GCR |
| 导入后仍尝试拉取 | 用 `docker image inspect` 核对完整标签，用 `docker context show` 确认同一 Docker daemon；构建配置需含 `noBaseImagesPull: true` |
| `No system certificates available`，随后找不到 apt 包 | 使用仓库 GPU 配置中的 HTTP 安装 CA → HTTPS 安装依赖流程，不要关闭证书验证 |
| 长时间停留在构建提示 | 按第 6.1 节查看 Buildx 日志；镜像下载、导出和解包都可能耗时 |

`noBaseImagesPull` 不会让 apt/pip 离线。Python 版本弃用或 pip root 提示本身不表示部署失败，以实际错误和函数状态为准。

### 9.3 Nuclio 辅助容器冲突

出现 `nuclio-local-storage-reader` 名称已占用、容器未运行时，先检查：

```bash
docker ps -a --filter name=nuclio-local-storage-reader
docker logs --tail 50 nuclio-local-storage-reader
```

确认是已停止的存储辅助容器后，尝试 `docker start nuclio-local-storage-reader`。
若仍失败，确认没有其他部署在进行，再用 `docker rm nuclio-local-storage-reader` 删除停止的容器，让 nuctl 重建。
不要删除 Nuclio 存储卷。

### 9.4 中断后提示函数正在 provision

```bash
pgrep -af 'nuctl|docker build'
docker buildx history ls
nuctl get function --platform local --namespace nuclio
```

确认没有构建仍在运行，且函数仅残留 `building` / `provisioning` 状态后，删除该函数再重新部署：

```bash
nuctl delete function pth-facebookresearch-sam-vit-h \
  --platform local --namespace nuclio --force
```

此操作移除 SAM 部署，保留 CVAT 数据和宿主机权重。`error` 状态通常可直接重试，不必删除；不要同时部署同一函数。

### 9.5 GPU、权重与界面

| 现象 | 检查项 |
| --- | --- |
| 主机 `nvidia-smi` 失败 | NVIDIA 驱动是否正确安装 |
| 主机正常、容器看不到 GPU | Container Toolkit 和 Docker runtime 配置 |
| `CUDA driver version is insufficient` | 驱动是否兼容镜像中的 CUDA 版本 |
| `CUDA out of memory` | 可用显存和其他 GPU 程序；ViT-H 需要足够显存 |
| 权重不存在或 `state_dict` 不匹配 | `.env.sam`、目录权限、`cvat.json` 的 checkpoint/type 与 Meta SAM 格式是否对应 |
| UI 无 Segment Anything | 启动命令是否包含 serverless 配置，函数是否在项目 `cvat` 中为 `ready`，网络是否为 `cvat_cvat` |
| 浏览器 SAM 解码失败 | 前后端是否包含自动选型代码、固定函数名是否正确、`/assets/sam/decoder-<type>.onnx` 是否已导出并挂载；替换同名文件后强制刷新 |

修改权重目录后需要重新部署，单纯重启容器不会更新挂载配置。
COCO 导入失败则检查格式、文件结构和掩码编码；该问题独立于 SAM 部署，不能通过重命名原始 YTVIS 文件解决。
