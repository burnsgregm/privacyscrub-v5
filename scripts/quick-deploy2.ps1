param (
    [Parameter(Mandatory=$true)]
    [string]$ProjectId,

    [string]$Service = "all", # Options: "gateway", "orchestrator", "gpu-worker", or "all"
    [string]$Region = "us-central1"
)

$Repo = "$Region-docker.pkg.dev/$ProjectId/privacyscrub-v5"

Write-Host ">>> Starting Quick Deployment..." -ForegroundColor Green

$ServicesToDeploy = @()
if ($Service -eq "all") {
    $ServicesToDeploy = @("gateway", "orchestrator", "gpu-worker")
} elseif ($Service -in @("gateway", "orchestrator", "gpu-worker")) {
    $ServicesToDeploy = @($Service)
} else {
    Write-Error "Invalid -Service argument. Must be 'all', 'gateway', 'orchestrator', or 'gpu-worker'."
    exit 1
}

foreach ($Target in $ServicesToDeploy) {
    Write-Host ""
    Write-Host ">>> ?? Quick Deploying [$Target]..." -ForegroundColor Cyan

    # --- SPECIAL HANDLING FOR GPU WORKER CACHE ---
    # This block moves the pre-downloaded model cache into the build context
    if ($Target -eq "gpu-worker") {
        $SourceFolder = "../scripts/model_cache"
        $DestinationFolder = "../services/gpu-worker/model_cache"
        
        if (Test-Path $SourceFolder -PathType Container) {
            Write-Host "    [0/3] Relocating model_cache to build context..." -NoNewline
            
            # Remove stale cache in worker folder to ensure a clean copy
            if (Test-Path $DestinationFolder -PathType Container) {
                Remove-Item $DestinationFolder -Recurse -Force
            }
            
            # Move the fresh model cache into the GPU worker directory
            Move-Item $SourceFolder $DestinationFolder
            Write-Host " Done." -ForegroundColor Green
        }
    }

    # 1. Build
    Write-Host "    [1/3] Building Docker Image..." -NoNewline
    # Suppress verbose output from Docker to keep the log clean
    docker build -t "$Repo/$Target`:latest" -f "../services/$Target/Dockerfile" "../services/$Target"
    
    # Check for build failure
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Build Failed (Exit Code: $LASTEXITCODE). Check the detailed Docker log above for the failing step."
        exit 1
    }
    Write-Host " Done." -ForegroundColor Green

    # 2. Push
    Write-Host "    [2/3] Pushing to Registry..." -NoNewline
    docker push "$Repo/$Target`:latest" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Push Failed."
        exit 1
    }
    Write-Host " Done." -ForegroundColor Green

    # 3. Deploy
    $CloudRunName = "privacyscrub-$Target"
    
    Write-Host "    [3/3] Updating Cloud Run Service..."
    # We use gcloud run deploy with only the image flag to preserve existing ENV VARS (URLs, Project ID)
    gcloud run deploy $CloudRunName `
      --image "$Repo/$Target`:latest" `
      --region $Region `
      --project $ProjectId
    
    Write-Host ">>> ? Update Complete: $Target" -ForegroundColor Green
}

Write-Host ""
Write-Host ">>> All Quick Deployment Tasks Complete!" -ForegroundColor Green