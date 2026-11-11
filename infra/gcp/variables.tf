variable "project_id" {
  description = "GCP project that holds everything (one project per environment)."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry and the bucket."
  type        = string
  default     = "us-central1"
}

variable "image" {
  description = "Container image (built by scripts/gcp_deploy.sh into this project's Artifact Registry)."
  type        = string
}

variable "console_origin" {
  description = "Where the Next.js console runs (Vercel), allowed by the API's CORS."
  type        = string
  default     = "http://localhost:3061"
}

variable "runs_per_hour" {
  description = "Public-demo guardrail: agent runs the API will start per hour (each one costs model calls)."
  type        = number
  default     = 6
}

variable "billing_account" {
  description = "Billing account id for the budget alert (empty = no budget resource)."
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "Budget alert threshold; emails at 50%, 90% and 100%."
  type        = number
  default     = 10
}
