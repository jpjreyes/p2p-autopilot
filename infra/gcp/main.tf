# P2P Autopilot on GCP (D21). Why GCP for this project: long headless-browser runs are Cloud Run Jobs' native
# workload (no 15-minute cap, no queue plumbing, pay only while a run executes), and the portfolio deploys each
# project where its workload fits (ROADMAP cloud map).
#
#   console (Vercel) ──► api (Cloud Run service) ──► run-agent (Cloud Run Job, one execution per run, Chromium)
#                          │                                │ steps + review items ─► Postgres (Neon, external)
#                          │                                └ screenshots + PDFs   ─► private bucket
#                          └ reads the warehouse baked into the image (see, predict) and the latest brief
#   Cloud Scheduler (Mondays) ──► weekly-brief (Cloud Run Job) ─► private bucket
#   portals (Cloud Run service): the mock supplier portals the agent works on
#
# Least privilege: one service account per piece, each with only the secrets and bucket rights it uses; the API may
# start exactly one job and nothing else. Secrets are created empty: their values are added out of band.

locals {
  services = ["run.googleapis.com", "artifactregistry.googleapis.com", "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com", "storage.googleapis.com", "cloudtrace.googleapis.com", "iam.googleapis.com",
  "billingbudgets.googleapis.com"]
  name = "p2p-autopilot"
}

data "google_project" "this" {}

resource "google_project_service" "apis" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "app" {
  repository_id = local.name
  location      = var.region
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# ---------------------------------------------------------------- storage: screenshots, invoice PDFs, briefs

resource "random_id" "bucket" {
  byte_length = 4
}

resource "google_storage_bucket" "data" {
  name                        = "${local.name}-${random_id.bucket.hex}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced" # read only through the API
  force_destroy               = true
  lifecycle_rule {
    condition {
      age            = 30
      matches_prefix = ["runs/"] # run evidence is kept 30 days; briefs are kept
    }
    action {
      type = "Delete"
    }
  }
}

# ---------------------------------------------------------------- secrets (values added out of band)

locals {
  secrets = {
    anthropic_api_key  = "Anthropic API key (agent and extraction model calls, the brief's summary)"
    database_url       = "Postgres URL (Neon): runs, steps, review queue, order system, portal state"
    portal_admin_token = "Token for the portals' /admin endpoints (chaos switches)"
    portal_secret      = "Secret the portals derive opaque icon tokens and sessions from"
  }
}

resource "google_secret_manager_secret" "s" {
  for_each  = local.secrets
  secret_id = "${local.name}-${replace(each.key, "_", "-")}"
  labels    = { app = local.name }
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------- service accounts

resource "google_service_account" "sa" {
  for_each     = toset(["api", "worker", "portals", "brief", "scheduler"])
  account_id   = "${local.name}-${each.value}"
  display_name = "P2P Autopilot ${each.value}"
}

locals {
  secret_access = {
    api     = ["database_url"]
    worker  = ["anthropic_api_key", "database_url", "portal_admin_token"]
    portals = ["database_url", "portal_admin_token", "portal_secret"]
    brief   = ["anthropic_api_key"]
  }
  secret_pairs = flatten([for sa, list in local.secret_access : [for s in list : { sa = sa, secret = s }]])
}

resource "google_secret_manager_secret_iam_member" "access" {
  for_each  = { for p in local.secret_pairs : "${p.sa}-${p.secret}" => p }
  secret_id = google_secret_manager_secret.s[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sa[each.value.sa].email}"
}

resource "google_storage_bucket_iam_member" "writers" {
  for_each = toset(["worker", "brief"])
  bucket   = google_storage_bucket.data.name
  role     = "roles/storage.objectCreator"
  member   = "serviceAccount:${google_service_account.sa[each.value].email}"
}

resource "google_storage_bucket_iam_member" "readers" {
  for_each = toset(["api", "worker"])
  bucket   = google_storage_bucket.data.name
  role     = "roles/storage.objectViewer"
  member   = "serviceAccount:${google_service_account.sa[each.value].email}"
}

resource "google_project_iam_member" "trace" {
  for_each = toset(["api", "worker", "brief"])
  project  = var.project_id
  role     = "roles/cloudtrace.agent"
  member   = "serviceAccount:${google_service_account.sa[each.value].email}"
}

resource "google_artifact_registry_repository_iam_member" "pull" {
  for_each   = toset(["api", "worker", "portals", "brief"])
  location   = google_artifact_registry_repository.app.location
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.sa[each.value].email}"
}

# the API may start the agent job with this run's parameters, and nothing else
resource "google_project_iam_custom_role" "run_one_job" {
  role_id     = "p2pAutopilotRunAgentJob"
  title       = "Start the agent job with overrides"
  permissions = ["run.jobs.run", "run.jobs.runWithOverrides", "run.executions.get"]
}

resource "google_cloud_run_v2_job_iam_member" "api_runs_agent" {
  name     = google_cloud_run_v2_job.agent.name
  location = var.region
  role     = google_project_iam_custom_role.run_one_job.id
  member   = "serviceAccount:${google_service_account.sa["api"].email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_brief" {
  name     = google_cloud_run_v2_job.brief.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.sa["scheduler"].email}"
}

# ---------------------------------------------------------------- the mock portals

resource "google_cloud_run_v2_service" "portals" {
  name                = "${local.name}-portals"
  location            = var.region
  deletion_protection = false
  template {
    service_account = google_service_account.sa["portals"].email
    scaling {
      max_instance_count = 2
    }
    containers {
      image   = var.image
      command = ["sh", "-c", "uvicorn p2p_autopilot.portals.app:app --host 0.0.0.0 --port $PORT"]
      env {
        name = "PORTAL_STATE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.s["database_url"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "PORTAL_ADMIN_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.s["portal_admin_token"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "PORTAL_SESSION_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.s["portal_secret"].secret_id
            version = "latest"
          }
        }
      }
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}

resource "google_cloud_run_v2_service_iam_member" "portals_public" {
  name     = google_cloud_run_v2_service.portals.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers" # mock portals: the agent reaches them like any website
}

# ---------------------------------------------------------------- the agent job (one execution per run)

resource "google_cloud_run_v2_job" "agent" {
  name                = "${local.name}-run-agent"
  location            = var.region
  deletion_protection = false
  template {
    task_count = 1
    template {
      service_account = google_service_account.sa["worker"].email
      timeout         = "1800s" # runs take 2-5 min; no 15-minute ceiling
      max_retries     = 0       # a failed run is recorded as an error, not silently repeated
      containers {
        image   = var.image
        command = ["python", "-m", "p2p_autopilot.worker"]
        env {
          name  = "PORTAL_BASE_URL"
          value = google_cloud_run_v2_service.portals.uri
        }
        env {
          name  = "LPA_BACKEND"
          value = "anthropic"
        }
        env {
          name  = "LPA_BUCKET"
          value = google_storage_bucket.data.name
        }
        env {
          name  = "LPA_TRACE_GCP"
          value = "1"
        }
        env {
          name = "ANTHROPIC_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.s["anthropic_api_key"].secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.s["database_url"].secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "PORTAL_ADMIN_TOKEN"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.s["portal_admin_token"].secret_id
              version = "latest"
            }
          }
        }
        resources {
          limits = { cpu = "2", memory = "4Gi" } # headless Chromium
        }
      }
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}

# ---------------------------------------------------------------- the API

resource "google_cloud_run_v2_service" "api" {
  name                = "${local.name}-api"
  location            = var.region
  deletion_protection = false
  template {
    service_account = google_service_account.sa["api"].email
    scaling {
      max_instance_count = 2
    }
    containers {
      image = var.image
      env {
        name  = "LPA_RUNNER"
        value = "cloudrun"
      }
      env {
        name  = "LPA_RUN_JOB"
        value = google_cloud_run_v2_job.agent.id
      }
      env {
        name  = "LPA_BUCKET"
        value = google_storage_bucket.data.name
      }
      env {
        name  = "LPA_RUNS_PER_HOUR"
        value = tostring(var.runs_per_hour)
      }
      env {
        name  = "CONSOLE_ORIGINS"
        value = var.console_origin
      }
      env {
        name  = "LPA_TRACE_GCP"
        value = "1"
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.s["database_url"].secret_id
            version = "latest"
          }
        }
      }
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers" # the console calls it from the browser; guardrails are in the API (D21)
}

# ---------------------------------------------------------------- the weekly brief

resource "google_cloud_run_v2_job" "brief" {
  name                = "${local.name}-weekly-brief"
  location            = var.region
  deletion_protection = false
  template {
    task_count = 1
    template {
      service_account = google_service_account.sa["brief"].email
      timeout         = "600s"
      max_retries     = 1
      containers {
        image   = var.image
        command = ["python", "-m", "p2p_autopilot.process.brief"]
        env {
          name  = "LPA_BACKEND"
          value = "anthropic"
        }
        env {
          name  = "LPA_BUCKET"
          value = google_storage_bucket.data.name
        }
        env {
          name  = "LPA_TRACE_GCP"
          value = "1"
        }
        env {
          name = "ANTHROPIC_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.s["anthropic_api_key"].secret_id
              version = "latest"
            }
          }
        }
        resources {
          limits = { cpu = "1", memory = "1Gi" }
        }
      }
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}

resource "google_cloud_scheduler_job" "weekly_brief" {
  name      = "${local.name}-weekly-brief"
  region    = var.region
  schedule  = "0 7 * * 1" # Mondays 07:00
  time_zone = "America/Los_Angeles"
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/${google_cloud_run_v2_job.brief.id}:run"
    oauth_token {
      service_account_email = google_service_account.sa["scheduler"].email
    }
  }
  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------- budget alert

resource "google_billing_budget" "monthly" {
  count           = var.billing_account == "" ? 0 : 1
  billing_account = var.billing_account
  display_name    = "${local.name} monthly"
  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }
  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
}
