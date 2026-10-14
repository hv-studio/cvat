#!/bin/bash
# Sample commands to deploy nuclio functions on GPU

set -eu

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
FUNCTIONS_DIR=${1:-$SCRIPT_DIR}

rendered_config_dir=""
cleanup() {
    if [ -n "$rendered_config_dir" ]; then
        rm -rf -- "$rendered_config_dir"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

nuctl create project cvat --platform local

shopt -s globstar

for func_config in "$FUNCTIONS_DIR"/**/function-gpu.yaml
do
    func_root="$(dirname "$func_config")"
    func_rel_path="$(realpath --relative-to="$SCRIPT_DIR" "$(dirname "$func_root")")"
    deploy_config="$func_config"

    if grep -qF '${SAM_WEIGHTS_DIR}' "$func_config"; then
        # An explicit environment variable takes precedence over local settings.
        if [ -z "${SAM_WEIGHTS_DIR:-}" ] && [ -f "$SCRIPT_DIR/../.env.sam" ]; then
            source "$SCRIPT_DIR/../.env.sam"
        fi
        if [ -z "${SAM_WEIGHTS_DIR:-}" ]; then
            echo "Set SAM_WEIGHTS_DIR or copy serverless/pytorch/facebookresearch/sam/weights.env.example to .env.sam and configure it." >&2
            exit 1
        fi

        if [ -z "$rendered_config_dir" ]; then
            rendered_config_dir="$(mktemp -d "${TMPDIR:-/tmp}/cvat-nuclio.XXXXXX")"
        fi
        deploy_config="$rendered_config_dir/function-gpu.yaml"
        SAM_WEIGHTS_DIR="$SAM_WEIGHTS_DIR" python3 - "$func_config" "$deploy_config" <<'PY'
import json
import os
from pathlib import Path
import sys

weights_dir = Path(os.environ["SAM_WEIGHTS_DIR"])
if not weights_dir.is_absolute() or not weights_dir.is_dir():
    sys.exit("SAM_WEIGHTS_DIR must be an existing absolute directory path.")
checkpoint = weights_dir / "sam-h.pth"
if not checkpoint.is_file() or not os.access(checkpoint, os.R_OK):
    sys.exit(f"SAM checkpoint is missing or unreadable: {checkpoint}")

template = Path(sys.argv[1]).read_text(encoding="utf-8")
# JSON string quoting also produces a valid YAML scalar for paths with spaces or quotes.
rendered = template.replace("${SAM_WEIGHTS_DIR}", json.dumps(str(weights_dir)))
Path(sys.argv[2]).write_text(rendered, encoding="utf-8")
PY
    fi

    echo "Deploying $func_rel_path function..."
    nuctl deploy --project-name cvat --path "$func_root" \
        --file "$deploy_config" --platform local \
        --env CVAT_FUNCTIONS_REDIS_HOST=cvat_redis_ondisk \
        --env CVAT_FUNCTIONS_REDIS_PORT=6666 \
        --platform-config '{"attributes": {"network": "cvat_cvat"}}'
done

nuctl get function --platform local
