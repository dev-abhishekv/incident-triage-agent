###############################################################################
# pipeline-triage-agent — GCP foundation
#
# Creates: APIs, BigQuery datasets, GCS raw bucket, Artifact Registry,
#          service accounts + IAM, Pub/Sub, Secret Manager, budget alert.
#
# Does NOT create: Cloud Run Job / Service, Cloud Scheduler, Workflows.
#   Those are added in week 1 once the container image exists. Stubs at bottom.
#
# Usage:
#   terraform init
#   terraform plan  -var project_id=YOUR_PROJECT -var billing_account=XXXXXX
#   terraform apply -var project_id=YOUR_PROJECT -var billing_account=XXXXXX
###############################################################################

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

###############################################################################
# Variables
###############################################################################

variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  default     = "asia-south1" # Mumbai — lowest latency from Bengaluru
}

variable "billing_account" {
  type        = string
  description = "Billing account ID, for the budget alert"
}

variable "budget_amount_inr" {
  type    = number
  default = 2000
}

variable "alert_email" {
  type        = string
  description = "Email for budget notifications"
  default     = ""
}

variable "bucket_name" {
  type        = string
  description = "GCS raw bucket suffix or full name"
  default     = "weather-data"
}

locals {
  name = "triage"
  labels = {
    project = "pipeline-triage-agent"
    owner   = "abhishek"
    env     = "dev"
  }
}

###############################################################################
# APIs
###############################################################################

resource "google_project_service" "apis" {
  for_each = toset([
    "bigquery.googleapis.com",
    "aiplatform.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "workflows.googleapis.com",
    "pubsub.googleapis.com",
    "storage.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "logging.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
    "billingbudgets.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

###############################################################################
# BigQuery datasets
###############################################################################

resource "google_bigquery_dataset" "datasets" {
  for_each = {
    raw         = "Landed source data, minimally parsed"
    core        = "Modelled tables the gold layer serves from"
    ops         = "Run events, schema history, data profiles, lineage, triage results, agent traces"
    triage_eval = "Fault-injection sandbox. Injectors may only write here."
  }

  dataset_id    = each.key
  friendly_name = each.key
  description   = each.value
  location      = var.region
  labels        = local.labels

  # Safety: eval sandbox self-cleans, the rest persist.
  default_table_expiration_ms = each.key == "triage_eval" ? 2592000000 : null # 30d

  depends_on = [google_project_service.apis]
}

###############################################################################
# GCS — raw landing zone
###############################################################################

resource "google_storage_bucket" "raw" {
  name                        = "${var.project_id}-${var.bucket_name}"
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true
  labels                      = local.labels

  lifecycle_rule {
    condition { age = 90 }
    action { type = "Delete" }
  }

  depends_on = [google_project_service.apis]
}

###############################################################################
# Artifact Registry — container images for Cloud Run
###############################################################################

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "${local.name}-images"
  format        = "DOCKER"
  labels        = local.labels

  depends_on = [google_project_service.apis]
}

###############################################################################
# Pub/Sub — run events and agent trigger
###############################################################################

resource "google_pubsub_topic" "run_events" {
  name                       = "${local.name}-run-events"
  labels                     = local.labels
  message_retention_duration = "86400s"

  depends_on = [google_project_service.apis]
}

resource "google_pubsub_topic" "incidents" {
  name                       = "${local.name}-incidents"
  labels                     = local.labels
  message_retention_duration = "86400s"

  depends_on = [google_project_service.apis]
}

###############################################################################
# Secret Manager — source API token
#
# The credential_expired fault flips this to an invalid value, so the secret
# is created here but its VALUE is managed outside Terraform on purpose.
###############################################################################

resource "google_secret_manager_secret" "source_api_token" {
  secret_id = "${local.name}-source-api-token"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

###############################################################################
# Service accounts
###############################################################################

resource "google_service_account" "pipeline" {
  account_id   = "${local.name}-pipeline"
  display_name = "Substrate pipeline runner"
}

resource "google_service_account" "agent" {
  account_id   = "${local.name}-agent"
  display_name = "Triage agent — READ ONLY on data"
}

resource "google_service_account" "scheduler" {
  account_id   = "${local.name}-scheduler"
  display_name = "Cloud Scheduler invoker"
}

# --- Pipeline: writes data, emits events -------------------------------------

resource "google_project_iam_member" "pipeline_bq_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_bigquery_dataset_iam_member" "pipeline_dataset_editor" {
  for_each   = google_bigquery_dataset.datasets
  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_storage_bucket_iam_member" "pipeline_gcs" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_pubsub_topic_iam_member" "pipeline_publish" {
  topic  = google_pubsub_topic.run_events.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.pipeline.email}"
}

resource "google_secret_manager_secret_iam_member" "pipeline_secret" {
  secret_id = google_secret_manager_secret.source_api_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.pipeline.email}"
}

# --- Agent: read-only on data, write only to its own results -----------------
# Tools are read-only by contract. Enforce it in IAM, not just in code.

resource "google_project_iam_member" "agent_bq_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_bigquery_dataset_iam_member" "agent_read_only" {
  for_each   = toset(["raw", "core", "triage_eval"])
  dataset_id = google_bigquery_dataset.datasets[each.value].dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.agent.email}"
}

# ops is the one place the agent writes (triage_results, agent_traces).
resource "google_bigquery_dataset_iam_member" "agent_ops_editor" {
  dataset_id = google_bigquery_dataset.datasets["ops"].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_storage_bucket_iam_member" "agent_gcs_read" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_project_iam_member" "agent_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_project_iam_member" "agent_logs_read" {
  project = var.project_id
  role    = "roles/logging.viewer"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

###############################################################################
# Budget alert
###############################################################################

resource "google_billing_budget" "budget" {
  billing_account = var.billing_account
  display_name    = "pipeline-triage-agent"

  budget_filter {
    projects = ["projects/649007891540"]
  }

  amount {
    specified_amount {
      currency_code = "INR"
      units         = tostring(var.budget_amount_inr)
    }
  }

  dynamic "threshold_rules" {
    for_each = [0.25, 0.5, 1.0]
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }

  depends_on = [google_project_service.apis]
}

###############################################################################
# Outputs
###############################################################################

output "raw_bucket" { value = google_storage_bucket.raw.name }
output "image_repo" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}" }
output "pipeline_sa" { value = google_service_account.pipeline.email }
output "agent_sa" { value = google_service_account.agent.email }
output "scheduler_sa" { value = google_service_account.scheduler.email }
output "run_events_topic" { value = google_pubsub_topic.run_events.name }
output "incidents_topic" { value = google_pubsub_topic.incidents.name }

###############################################################################
# Week 1, after the first image is pushed — uncomment and apply
###############################################################################
#
# resource "google_cloud_run_v2_job" "substrate" {
#   name     = "${local.name}-substrate"
#   location = var.region
#
#   template {
#     template {
#       service_account = google_service_account.pipeline.email
#       max_retries     = 1
#       timeout         = "900s"
#
#       containers {
#         image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}/substrate:latest"
#         resources {
#           limits = { cpu = "1", memory = "2Gi" }
#         }
#         env {
#           name  = "RAW_BUCKET"
#           value = google_storage_bucket.raw.name
#         }
#         env {
#           name  = "RUN_EVENTS_TOPIC"
#           value = google_pubsub_topic.run_events.id
#         }
#       }
#     }
#   }
# }
#
# resource "google_cloud_scheduler_job" "daily" {
#   name      = "${local.name}-daily"
#   schedule  = "30 1 * * *"   # 07:00 IST
#   time_zone = "Asia/Kolkata"
#
#   http_target {
#     http_method = "POST"
#     uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.substrate.name}:run"
#     oauth_token {
#       service_account_email = google_service_account.scheduler.email
#     }
#   }
# }
#
# resource "google_cloud_run_v2_job_iam_member" "scheduler_invoke" {
#   name   = google_cloud_run_v2_job.substrate.name
#   location = var.region
#   role   = "roles/run.invoker"
#   member = "serviceAccount:${google_service_account.scheduler.email}"
# }
