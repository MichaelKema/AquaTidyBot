variable "aws_region" {
  description = "AWS deployment region."
  type        = string
  default     = "us-east-1"
}
variable "availability_zone" {
  description = "Lightsail instance and persistent disk must share this availability zone."
  type        = string
  default     = "us-east-1a"
}
variable "name" {
  description = "Lightsail instance name and resource prefix."
  type        = string
  default     = "aquatidy"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Use 3-31 lowercase letters, digits or hyphens, starting with a letter."
  }
}
variable "bundle_id" {
  description = "Lightsail Linux bundle; confirm availability with aws lightsail get-bundles."
  type        = string
  default     = "small_3_0"
}
variable "data_disk_size" {
  description = "Persistent Lightsail disk size in GiB (minimum 8)."
  type        = number
  default     = 8
  validation {
    condition     = var.data_disk_size >= 8 && floor(var.data_disk_size) == var.data_disk_size
    error_message = "Use an integer disk size of at least 8 GiB."
  }
}
variable "ssh_cidrs" {
  description = "SSH source ranges. Hosted GitHub runners require reachable TCP 22; use fixed ranges with a runner that has static egress."
  type        = list(string)
  default     = ["0.0.0.0/0"]
  validation {
    condition     = length(var.ssh_cidrs) > 0 && alltrue([for cidr in var.ssh_cidrs : can(cidrnetmask(cidr))])
    error_message = "Supply at least one valid IPv4 CIDR."
  }
}
variable "github_repository" {
  description = "GitHub owner/repository allowed to deploy, case-sensitive."
  type        = string
  default     = "MichaelKema/AquaTidyBot"
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use owner/repository."
  }
}
variable "github_oidc_provider_arn" {
  description = "Existing GitHub OIDC provider ARN; required unless create_github_oidc_provider is true."
  type        = string
  default     = null
  validation {
    condition     = var.create_github_oidc_provider ? var.github_oidc_provider_arn == null : can(regex("^arn:aws:iam::[0-9]{12}:oidc-provider/token\\.actions\\.githubusercontent\\.com$", coalesce(var.github_oidc_provider_arn, "unset")))
    error_message = "Provide an existing GitHub OIDC provider ARN, or enable creation and leave the ARN unset."
  }
}
variable "create_github_oidc_provider" {
  description = "Create the account-wide GitHub OIDC provider when none exists."
  type        = bool
  default     = false
}
variable "github_oidc_subject" {
  description = "Override for a customized/immutable-ID GitHub OIDC subject. Defaults to repo:OWNER/REPO:environment:production."
  type        = string
  default     = null
}

variable "existing_instance_name" {
  description = "Existing Lightsail instance to deploy to. When set, Terraform does not manage its instance, firewall, or IP."
  type        = string
  default     = null
  validation {
    condition     = var.existing_instance_name == null ? true : can(regex("^[A-Za-z0-9][A-Za-z0-9_-]*$", var.existing_instance_name))
    error_message = "Use the exact existing Lightsail instance name."
  }
}
variable "existing_instance_arn" {
  description = "Exact ARN of the existing Lightsail instance, required when existing_instance_name is set. Retrieve with aws lightsail get-instance."
  type        = string
  default     = null
  validation {
    condition     = var.existing_instance_name == null ? true : can(regex("^arn:aws:lightsail:[a-z0-9-]+:[0-9]{12}:Instance/[A-Za-z0-9-]+$", var.existing_instance_arn))
    error_message = "Provide the existing instance ARN from the Lightsail API."
  }
}
