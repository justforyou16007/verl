#!/usr/bin/env bash
# List (and optionally delete) leaked training pods: name starts with "mimoagent-" AND older than
# MAX_AGE_HOURS, in ONE namespace only. Dry run by default -- set APPLY=1 to actually delete.
#
# Training pods never expire on their own: KubernetesEnvironmentConfig.pod_timeout is declared
# but not used, and the pod spec has no activeDeadlineSeconds or ownerReferences. A crashed run
# therefore leaves pods behind until someone deletes them.
#
# Keep MAX_AGE_HOURS well above the longest legitimate pod lifetime:
#   General: ENV_SETUP_TIMEOUT (3600 s) + TRAJECTORY_TIMEOUT (1200 s) + grading
#   Code:    session_timeout_seconds (TRAJECTORY_TIMEOUT, 4800-7200 s) + grading
# Not yet run against a real cluster.
set -euo pipefail

NS="${NS:-mimo-rl}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-12}"
APPLY="${APPLY:-0}"
KC_ARGS=()
[ -n "${KC:-}" ] && KC_ARGS=(--kubeconfig="${KC}")

if [ "${NS}" = "default" ] || [ "${NS}" = "kube-system" ]; then
  echo "refusing to sweep namespace '${NS}': use the dedicated training namespace" >&2
  exit 1
fi

STALE="$(kubectl "${KC_ARGS[@]}" -n "${NS}" get pods -o json | python3 -I -c '
import datetime, json, sys
max_age = datetime.timedelta(hours=float(sys.argv[1]))
now = datetime.datetime.now(datetime.timezone.utc)
for pod in json.load(sys.stdin)["items"]:
    meta = pod["metadata"]
    if not meta["name"].startswith("mimoagent-") or meta.get("deletionTimestamp"):
        continue
    created = datetime.datetime.fromisoformat(meta["creationTimestamp"].replace("Z", "+00:00"))
    if now - created > max_age:
        print(meta["name"])
' "${MAX_AGE_HOURS}")"

if [ -z "${STALE}" ]; then
  echo "no mimoagent-* pods older than ${MAX_AGE_HOURS}h in ${NS}"
  exit 0
fi

echo "mimoagent-* pods older than ${MAX_AGE_HOURS}h in ${NS}:"
printf '  %s\n' ${STALE}
if [ "${APPLY}" != "1" ]; then
  echo "dry run; re-run with APPLY=1 to delete them"
  exit 0
fi
# shellcheck disable=SC2086
kubectl "${KC_ARGS[@]}" -n "${NS}" delete pod ${STALE} --grace-period=0 --wait=false
