variable "project_id" {
    default = "porto-padel-league"
}

variable "region" {
  default = "europe-west1"
}

variable "zone" {
  default = "europe-west1-b"
}

# CIDRs allowed to reach Postgres (5432) directly, e.g. ["203.0.113.7/32"].
# No default on purpose: plan/apply must be given the owner's current IP.
variable "postgres_allowed_cidrs" {
  type = list(string)

  validation {
    condition     = length(var.postgres_allowed_cidrs) > 0 && !contains(var.postgres_allowed_cidrs, "0.0.0.0/0")
    error_message = "List at least one CIDR, and never 0.0.0.0/0."
  }
}
