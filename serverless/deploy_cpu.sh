#!/bin/bash
# Sample commands to deploy nuclio functions on CPU

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

export DOCKER_BUILDKIT=1

docker build -t cvat.openvino.base "$SCRIPT_DIR/openvino/base"

nuctl create project cvat --platform local

shopt -s globstar

for func_config in "$FUNCTIONS_DIR"/**/function.yaml
do
    func_root="$(dirname "$func_config")"
    func_rel_path="$(realpath --relative-to="$SCRIPT_DIR" "$(dirname "$func_root")")"
    deploy_config="$func_config"

    if grep -qF '${SAM_WEIGHTS_DIR}' "$func_config"; then
        # Explicit environment variables take precedence over local settings.
        if [ -f "$SCRIPT_DIR/../.env.sam" ]; then
            if [ -z "${SAM_WEIGHTS_DIR:-}" ]; then
                SAM_WEIGHTS_DIR=$(source "$SCRIPT_DIR/../.env.sam"; printf '%s' "${SAM_WEIGHTS_DIR:-}")
            fi
            if [ -z "${SAM_RESTART_POLICY:-}" ]; then
                SAM_RESTART_POLICY=$(source "$SCRIPT_DIR/../.env.sam"; printf '%s' "${SAM_RESTART_POLICY:-}")
            fi
        fi
        if [ -z "${SAM_WEIGHTS_DIR:-}" ]; then
            echo "Set SAM_WEIGHTS_DIR or copy serverless/pytorch/facebookresearch/sam/weights.env.example to .env.sam and configure it." >&2
            exit 1
        fi

        if [ -z "$rendered_config_dir" ]; then
            rendered_config_dir="$(mktemp -d "${TMPDIR:-/tmp}/cvat-nuclio.XXXXXX")"
        fi
        deploy_config="$rendered_config_dir/function.yaml"
        SAM_WEIGHTS_DIR="$SAM_WEIGHTS_DIR" SAM_RESTART_POLICY="${SAM_RESTART_POLICY:-always}" \
            python3 - "$func_config" "$deploy_config" <<'PY'
import json
import os
import sys
from pathlib import Path

weights_dir = Path(os.environ["SAM_WEIGHTS_DIR"]).resolve(strict=True)
template = Path(sys.argv[1]).read_text(encoding="utf-8")
restart_policy = os.environ["SAM_RESTART_POLICY"]
# JSON string quoting also produces a valid YAML scalar for paths with spaces or quotes.
rendered = template.replace("${SAM_WEIGHTS_DIR}", json.dumps(str(weights_dir)))
rendered = rendered.replace("${SAM_RESTART_POLICY}", json.dumps(restart_policy))
Path(sys.argv[2]).write_text(rendered, encoding="utf-8")
PY
    fi

    if [ -f "$func_root/Dockerfile" ]; then
        docker build -t "cvat.${func_rel_path//\//.}.base" "$func_root"
    fi

    echo "Deploying $func_rel_path function..."
    nuctl deploy --project-name cvat --path "$func_root" \
        --file "$deploy_config" --platform local \
        --env CVAT_FUNCTIONS_REDIS_HOST=cvat_redis_ondisk \
        --env CVAT_FUNCTIONS_REDIS_PORT=6666 \
        --platform-config '{"attributes": {"network": "cvat_cvat"}}'
done

nuctl get function --platform local
