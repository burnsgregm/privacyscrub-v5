# Usage: ./deploy.ps1 -ProjectId "my-gcp-project"
param (
    [string]$ProjectId
)

$Region = "us-central1"
$Repo = "$Region-docker.pkg.dev/$ProjectId/privacyscrub-v5"

Write-Host ">>> Starting PrivacyScrub V5 Enterprise Deployment..." -ForegroundColor Green

# 1. Enable Required GCP APIs [cite: 662]
Write-Host ">>> Enabling APIs..."
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudtasks.googleapis.com firestore.googleapis.com --project $ProjectId

# 2. Build & Push Docker Images [cite: 675]
$Services = @("gateway", "orchestrator", "gpu-worker")

foreach ($Service in $Services) {
    Write-Host ">>> Building Service: $Service..."
    $ImageUri = "$Repo/$Service`:latest"
    
    # Docker Build
    docker build -t $ImageUri -f "../services/$Service/Dockerfile" "../services/$Service"
    
    # Docker Push
    docker push $ImageUri
}

# 3. Deploy/Update Cloud Run Services
# We re-deploy the services created by Terraform, updating them with the actual image
# and injecting the Service URLs for service-to-service communication.

Write-Host ">>> fetching Service URLs..."
$OrchestratorUrl = gcloud run services describe privacyscrub-orchestrator --region $Region --format 'value(status.url)'
$GpuWorkerUrl = gcloud run services describe privacyscrub-gpu-worker --region $Region --format 'value(status.url)'

Write-Host ">>> Updating Services with Real Images and Env Vars..."

# Update Gateway (Inject Orchestrator URL)
gcloud run deploy privacyscrub-gateway `
  --image "$Repo/gateway:latest" `
  --region $Region `
  --set-env-vars "ORCHESTRATOR_URL=$OrchestratorUrl"

# Update Orchestrator (Inject Worker URL)
gcloud run deploy privacyscrub-orchestrator `
  --image "$Repo/orchestrator:latest" `
  --region $Region `
  --set-env-vars "WORKER_URL=$GpuWorkerUrl"

# Update GPU Worker
gcloud run deploy privacyscrub-gpu-worker `
  --image "$Repo/gpu-worker:latest" `
  --region $Region 
  # Note: GPU allocation is handled in Terraform via launch_stage/limits. 
  # Using `gcloud run deploy` here maintains those settings if we don't overwrite resources.

Write-Host ">>> V5 Deployment Complete!" -ForegroundColor Green