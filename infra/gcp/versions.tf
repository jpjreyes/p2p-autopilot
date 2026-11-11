terraform {
  required_version = ">= 1.9"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # State stays local for the demo (one operator). For a team: a GCS backend with versioning and a lock.
}

provider "google" {
  project = var.project_id
  region  = var.region
}
