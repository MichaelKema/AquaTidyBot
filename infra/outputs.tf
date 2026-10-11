output "instance_name" {
  description = "Set repository variable LIGHTSAIL_INSTANCE_NAME to this value."
  value       = local.instance_name
}
output "deploy_role_arn" {
  description = "Set repository variable AWS_DEPLOY_ROLE_ARN to this value."
  value       = aws_iam_role.deploy.arn
}
output "aws_region" {
  description = "Set repository variable AWS_REGION to this value."
  value       = var.aws_region
}
output "public_ip" {
  description = "Managed static IP for a new instance; null when using an existing instance."
  value       = local.use_existing_instance ? null : aws_lightsail_static_ip.bot[0].ip_address
}
output "data_disk_name" {
  description = "Unused legacy disk retained pending reviewed cleanup; null for new installations."
  value       = var.retain_legacy_data_disk ? aws_lightsail_disk.data[0].name : null
}
