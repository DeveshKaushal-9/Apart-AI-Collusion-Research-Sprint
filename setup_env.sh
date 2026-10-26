#!/usr/bin/env bash
# Clone the upstream environment (Agrawal et al. 2025) at the pinned commit and apply this project's patch.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p external
if [ ! -d external/llm-agent-collusion ]; then
  git clone https://github.com/andyjliu/llm-agent-collusion.git external/llm-agent-collusion
fi
cd external/llm-agent-collusion
git checkout -q "$(cat ../../env_patch/UPSTREAM_COMMIT.txt)"
git apply --check ../../env_patch/llm-agent-collusion.patch && git apply ../../env_patch/llm-agent-collusion.patch
echo "Environment ready: external/llm-agent-collusion (patched)"
