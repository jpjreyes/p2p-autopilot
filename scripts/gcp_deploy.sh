#!/usr/bin/env bash
# Deploy P2P Autopilot to GCP (D21): build the image with Cloud Build, then terraform apply.
#   1. gcloud auth login && gcloud config set project <id>      (once)
#   2. cp infra/gcp/terraform.tfvars.example infra/gcp/terraform.tfvars and fill it in
#   3. scripts/gcp_deploy.sh            first run creates the secrets empty: add their values, then run it again
# Destroy everything:  cd infra/gcp && terraform destroy
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT=$(gcloud config get-value project 2>/dev/null)
REGION=$(grep -E '^region' infra/gcp/terraform.tfvars | cut -d'"' -f2)
TAG=$(git rev-parse --short HEAD)
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/p2p-autopilot/app:${TAG}"
TF="${TERRAFORM:-terraform}"

echo "== enabling the registry, then building ${IMAGE} with Cloud Build (nothing heavy builds on this laptop)"
(cd infra/gcp && $TF init -input=false >/dev/null && \
  $TF apply -input=false -auto-approve -target=google_project_service.apis -target=google_artifact_registry_repository.app)
gcloud builds submit --tag "$IMAGE" .

echo "== applying the rest"
(cd infra/gcp && $TF apply -input=false -var "image=${IMAGE}")

MISSING=$(for s in $(cd infra/gcp && $TF output -json secrets_to_fill | tr -d '[]"' | tr ',' ' '); do
  gcloud secrets versions list "$s" --limit=1 --format='value(name)' | grep -q . || echo "$s"; done)
if [ -n "$MISSING" ]; then
  echo "== add these secret values, then run this script again:"; echo "$MISSING"
  exit 0
fi
echo "== smoke test"
API=$(cd infra/gcp && $TF output -raw api_url)
curl -fsS "$API/health" && curl -fsS "$API/api/process/overview" | head -c 300 && echo
echo "== done: set NEXT_PUBLIC_API_URL=$API in Vercel"
