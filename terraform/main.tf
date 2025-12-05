# 1. Artifact Registry (Stores Docker Images)
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "privacyscrub-v5"
  description   = "Docker repository for PrivacyScrub V5 Microservices"
  format        = "DOCKER"
}

# 2. Cloud Storage (Media Buckets)
resource "google_storage_bucket" "media_bucket" {
  name          = "${var.project_id}-media-v5"
  location      = var.region
  force_destroy = true

  # FR-V5-05 / NFR-SEC-04: Strict 24h TTL for privacy compliance [cite: 98, 141]
  lifecycle_rule {
    condition {
      age = 1
    }
    action {
      type = "Delete"
    }
  }
}

# 3. Firestore (State Database)
resource "google_firestore_database" "database" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
}

# 4. Cloud Tasks Queue (Job Orchestration)
resource "google_cloud_tasks_queue" "video_queue" {
  name     = "privacyscrub-video-queue"
  location = var.region
}

# 5. Cloud Run Services (Placeholders - Code deployed via script later)

# Service A: API Gateway
resource "google_cloud_run_v2_service" "gateway" {
  name     = "privacyscrub-gateway"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello" # Placeholder
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      # ORCHESTRATOR_URL injected via deploy script
    }
  }
}

# Service B: Orchestrator
resource "google_cloud_run_v2_service" "orchestrator" {
  name     = "privacyscrub-orchestrator"
  location = var.region

  template {
    timeout = "3600s" # Long timeout for splitting large files
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello" # Placeholder
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = google_storage_bucket.media_bucket.name
      }
      # WORKER_URL injected via deploy script
    }
  }
}

# Service C: GPU Worker
resource "google_cloud_run_v2_service" "gpu_worker" {
  name         = "privacyscrub-gpu-worker"
  location     = var.region
  launch_stage = "BETA" # Required for GPU

  template {
    scaling {
      max_instance_count = 5
    }
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello" # Placeholder
      resources {
        limits = {
          cpu    = "4000m"
          memory = "16Gi"
          # Uncomment below if you have GPU quota. 
          # For testing without quota, Terraform will provision CPU-only if commented out.
          # "nvidia.com/gpu" = "1" 
        }
      }
    }
  }
}