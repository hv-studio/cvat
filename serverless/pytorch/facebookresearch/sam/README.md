# SAM ViT-H GPU deployment with local weights

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

The deployment script uses host Python 3 (standard library only) to validate
the directory and checkpoint, then render the GPU configuration into a temporary
directory. The temporary configuration is removed on exit, including deployment
failures. Use the deployment script rather than passing the unrendered template
directly to `nuctl`.

The function mounts the directory read-only at `/opt/weights/sam` and loads
`/opt/weights/sam/sam-h.pth`. The container path is independent of the host path.
