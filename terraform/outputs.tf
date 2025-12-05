output "gateway_url" {
  value = google_cloud_run_v2_service.gateway.uri
}

output "orchestrator_url" {
  value = google_cloud_run_v2_service.orchestrator.uri
}

output "gpu_worker_url" {
  value = google_cloud_run_v2_service.gpu_worker.uri
}