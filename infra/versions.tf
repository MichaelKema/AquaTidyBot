terraform {
  required_version = ">= 1.14, < 2.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  # Local state by default. See backend.s3.tf.example before using a team/CI backend.
}

provider "aws" {
  region = var.aws_region
}
