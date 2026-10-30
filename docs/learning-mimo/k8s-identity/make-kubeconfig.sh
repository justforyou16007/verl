#!/usr/bin/env bash
# Build a kubeconfig for the mimo-rollout ServiceAccount from mimo-rollout-rbac.yaml.
# Run it with an admin kubeconfig as the current context; it reads the cluster address from there.
# Not yet run against a real cluster.
set -euo pipefail

NS="${NS:-mimo-rl}"
SA="${SA:-mimo-rollout}"
SECRET="${SECRET:-mimo-rollout-token}"
OUT="${OUT:-./mimo-rollout.kubeconfig}"

CLUSTER_NAME="$(kubectl config view --minify -o jsonpath='{.clusters[0].name}')"
SERVER="${SERVER:-$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')}"

# The token controller fills the Secret asynchronously after it is created.
for _ in $(seq 1 30); do
  TOKEN_B64="$(kubectl -n "${NS}" get secret "${SECRET}" -o jsonpath='{.data.token}' 2>/dev/null || true)"
  [ -n "${TOKEN_B64}" ] && break
  sleep 1
done
if [ -z "${TOKEN_B64:-}" ]; then
  echo "secret ${NS}/${SECRET} has no token yet; was mimo-rollout-rbac.yaml applied?" >&2
  exit 1
fi
TOKEN="$(printf '%s' "${TOKEN_B64}" | base64 -d)"

CA_FILE="$(mktemp)"
trap 'rm -f "${CA_FILE}"' EXIT
kubectl -n "${NS}" get secret "${SECRET}" -o jsonpath='{.data.ca\.crt}' | base64 -d > "${CA_FILE}"

rm -f "${OUT}"
kubectl config --kubeconfig="${OUT}" set-cluster "${CLUSTER_NAME}" \
  --server="${SERVER}" --certificate-authority="${CA_FILE}" --embed-certs=true >/dev/null
kubectl config --kubeconfig="${OUT}" set-credentials "${SA}" --token="${TOKEN}" >/dev/null
kubectl config --kubeconfig="${OUT}" set-context "${SA}@${CLUSTER_NAME}" \
  --cluster="${CLUSTER_NAME}" --user="${SA}" --namespace="${NS}" >/dev/null
kubectl config --kubeconfig="${OUT}" use-context "${SA}@${CLUSTER_NAME}" >/dev/null
chmod 600 "${OUT}"

echo "wrote ${OUT}"
echo "  server    = ${SERVER}"
echo "  namespace = ${NS}"
echo "Copy it to a path every Ray node can read, then: export KUBECONFIG=<that path> K8S_NAMESPACE=${NS}"
