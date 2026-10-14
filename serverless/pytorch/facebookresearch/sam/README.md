# SAM ViT-H GPU deployment

Place the Meta-format SAM ViT-H checkpoint in a host directory and name it
`sam-h.pth`. Configure the directory from the CVAT repository root:

```bash
cp serverless/pytorch/facebookresearch/sam/weights.env.example .env.sam
# Edit SAM_WEIGHTS_DIR in .env.sam to point to the absolute host directory.
./serverless/deploy_gpu.sh serverless/pytorch/facebookresearch/sam/nuclio
```

The repository ignores `.env.sam`. It is sourced as a shell file; quote paths
containing spaces. A non-empty `SAM_WEIGHTS_DIR` environment variable takes
precedence over this file.

Set `SAM_RESTART_POLICY=no` in `.env.sam` to require manual startup after a host
or Docker restart. The default is `always`. This setting takes effect on deployment;
for an existing container, apply it without redeploying with
`docker update --restart=no nuclio-nuclio-pth-facebookresearch-sam-vit-h`.

The deployment script uses host Python 3 (standard library only) to validate
the directory and checkpoint, then render the GPU configuration into a temporary
directory. The temporary configuration is removed on exit, including deployment
failures. Use the deployment script rather than passing the unrendered template
directly to `nuctl`.

The function mounts the directory read-only at `/opt/weights/sam` and loads
`/opt/weights/sam/sam-h.pth`. The container path is independent of the host path.

The GPU build uses NJU package mirrors:

- Ubuntu packages, including security updates: `https://mirrors.nju.edu.cn/ubuntu/`.
  The minimal base image first uses NJU's HTTP endpoint to install
  `ca-certificates`, with Ubuntu's repository signature verification enabled.
  It then switches to HTTPS before installing the remaining dependencies. APT
  index download failures stop the build immediately.
- Python packages: `https://mirrors.nju.edu.cn/pypi/web/simple`, configured via
  `PIP_INDEX_URL` for all pip commands. SAM is installed as the `segment-anything`
  PyPI package rather than fetched directly from GitHub.

Nuclio's bundled SDK wheels are installed locally with `--no-index`. Docker image
registries are separate from these package mirrors. Changes to the build
configuration take effect on the next deployment, not in an already running build.
