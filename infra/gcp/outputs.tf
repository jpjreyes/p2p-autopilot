output "api_url" {
  description = "Set as NEXT_PUBLIC_API_URL in the console's Vercel project."
  value       = google_cloud_run_v2_service.api.uri
}

output "portals_url" {
  value = google_cloud_run_v2_service.portals.uri
}

output "bucket" {
  value = google_storage_bucket.data.name
}

output "secrets_to_fill" {
  description = "Add each value once: printf '%s' \"$VALUE\" | gcloud secrets versions add <name> --data-file=-"
  value       = [for s in google_secret_manager_secret.s : s.secret_id]
}
