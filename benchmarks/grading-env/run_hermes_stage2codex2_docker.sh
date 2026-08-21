#!/usr/bin/env bash
set -euo pipefail

IMAGE="sha256:da0d12083015723edf16afe7c74f10138d056ee6948aaf02eca18af4b5bc29e0"
SOURCE_PROFILE="/home/fabio/.hermes/profiles/stage2codex2"
PROXY_SCRIPT="/home/fabio/AgentHarness-actionable-repair-20260725/benchmarks/grading-env/codex_egress_proxy.py"
PROBE_SCRIPT="/home/fabio/AgentHarness-actionable-repair-20260725/benchmarks/grading-env/codex_egress_probe.py"

case "$PWD" in
  /*/workspace|*/initial-workspace) ;;
  *)
    printf 'sandbox wrapper requires a benchmark workspace cwd, got %s\n' "$PWD" >&2
    exit 64
    ;;
esac

cell_root=$(dirname "$PWD")
workspace_name=$(basename "$PWD")
token=$(printf '%s' "$cell_root" | sha256sum | cut -c1-16)
network="ah-v2-$token"
proxy="ah-v2-proxy-$token"
agent="ah-v2-agent-$token"
profile_base="/tmp/agentharness-efficacy-v2-profiles"
private_profile="$profile_base/$token"
cleanup_resources() {
  docker rm -f "$agent" >/dev/null 2>&1 || true
  docker rm -f "$proxy" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  if [[ ! -L "$profile_base" ]]; then
    rm -rf -- "$private_profile"
  fi
}
if [[ "${1:-}" == "--sandbox-cleanup" ]]; then
  cleanup_resources
  if [[ -L "$profile_base" ]]; then
    printf 'sandbox profile base must not be a symlink\n' >&2
    exit 73
  fi
  exit 0
fi

if [[ -L "$profile_base" ]]; then
  printf 'sandbox profile base must not be a symlink\n' >&2
  exit 73
fi
mkdir -p -m 700 -- "$profile_base"
if [[ $(stat -c '%u:%a' "$profile_base") != "$(id -u):700" ]]; then
  printf 'sandbox profile base has unsafe owner or mode\n' >&2
  exit 73
fi
cleanup_resources
mkdir -m 700 -- "$private_profile"
cleanup() {
  cleanup_resources
  rm -rf -- "$private_profile"
}
trap cleanup EXIT INT TERM

cp -p -- "$SOURCE_PROFILE/auth.json" "$private_profile/auth.json"
cp -p -- "$SOURCE_PROFILE/config.yaml" "$private_profile/config.yaml"
mkdir -p "$private_profile/logs" "$private_profile/sessions"
chmod 700 "$private_profile"

docker network create --internal "$network" >/dev/null
docker run -d \
  --name "$proxy" \
  --network "$network" \
  --network-alias egress-proxy \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 64 \
  --memory 256m \
  --user 65534:65534 \
  --tmpfs /tmp:rw,nosuid,size=32m \
  --mount "type=bind,src=$PROXY_SCRIPT,dst=/proxy.py,readonly" \
  --entrypoint /opt/hermes/.venv/bin/python \
  "$IMAGE" /proxy.py >/dev/null
docker network connect --gw-priority 1 bridge "$proxy"
ready=false
for _ in $(seq 1 50); do
  if docker logs "$proxy" 2>&1 | grep -q '^READY codex-egress-proxy '; then
    ready=true
    break
  fi
  if ! docker inspect "$proxy" --format '{{.State.Running}}' 2>/dev/null | grep -q '^true$'; then
    break
  fi
  sleep 0.1
done
if [[ "$ready" != true ]]; then
  docker logs "$proxy" >&2 || true
  printf 'egress proxy failed readiness\n' >&2
  exit 70
fi

if [[ "${1:-}" == "--sandbox-egress-self-test" ]]; then
  docker run --rm \
    --network "$network" \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --pids-limit 32 \
    --memory 128m \
    --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$PROBE_SCRIPT,dst=/probe.py,readonly" \
    --entrypoint /opt/hermes/.venv/bin/python \
    "$IMAGE" /probe.py
  exit 0
fi

if [[ "${1:-}" == "--sandbox-resource-hold" ]]; then
  docker run --rm \
    --name "$agent" \
    --network "$network" \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --entrypoint /bin/sleep \
    "$IMAGE" 300
  exit 0
fi

docker run --rm \
  --name "$agent" \
  --network "$network" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 256 \
  --memory 5g \
  --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,nosuid,size=1g \
  --tmpfs /run:rw,nosuid,size=64m \
  --mount "type=bind,src=$cell_root,dst=/experiment" \
  --mount "type=bind,src=$private_profile,dst=/hermes-home" \
  --workdir "/experiment/$workspace_name" \
  --env HOME=/tmp/home \
  --env HERMES_HOME=/hermes-home \
  --env TERMINAL_CWD="/experiment/$workspace_name" \
  --env PYTHONNOUSERSITE=1 \
  --env HTTP_PROXY=http://egress-proxy:8080 \
  --env HTTPS_PROXY=http://egress-proxy:8080 \
  --env http_proxy=http://egress-proxy:8080 \
  --env https_proxy=http://egress-proxy:8080 \
  --env NO_PROXY=localhost,127.0.0.1 \
  --entrypoint /opt/hermes/.venv/bin/python \
  "$IMAGE" /opt/hermes/hermes "$@"
