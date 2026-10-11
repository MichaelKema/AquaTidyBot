mock_provider "aws" {}

variables {
  existing_instance_name      = null
  existing_instance_arn       = null
  create_github_oidc_provider = false
  github_oidc_provider_arn    = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
}

run "lightsail_deployment" {
  command = plan
  assert {
    condition     = aws_lightsail_disk_attachment.data.disk_path == "/dev/xvdf"
    error_message = "The bootstrap disk path must match the attachment."
  }
  assert {
    condition     = aws_lightsail_disk.data.availability_zone == aws_lightsail_instance.bot[0].availability_zone
    error_message = "The persistent disk must remain in the instance's availability zone."
  }
  assert {
    condition     = length(aws_lightsail_instance_public_ports.bot[0].port_info) == 1 && one(aws_lightsail_instance_public_ports.bot[0].port_info).from_port == 22
    error_message = "Only SSH should be exposed."
  }
  assert {
    condition     = strcontains(aws_iam_role.deploy.assume_role_policy, "repo:MichaelKema/AquaTidyBot:environment:production")
    error_message = "Deployment access must be scoped to this repository and production environment."
  }
  assert {
    condition     = strcontains(aws_lightsail_instance.bot[0].user_data, "mountpoint -q /var/lib/aquatidy")
    error_message = "The bot must refuse to run without its persistent data mount."
  }
}

run "existing_aquatidy_instance" {
  command = plan
  variables {
    existing_instance_name = "AquaTidy"
    existing_instance_arn  = "arn:aws:lightsail:us-east-1:123456789012:Instance/11111111-2222-3333-4444-555555555555"
  }
  assert {
    condition     = length(aws_lightsail_instance.bot) == 0 && length(aws_lightsail_instance_public_ports.bot) == 0 && length(aws_lightsail_static_ip.bot) == 0 && length(aws_lightsail_static_ip_attachment.bot) == 0
    error_message = "Existing-instance mode must leave the instance, firewall and IP unmanaged."
  }
  assert {
    condition     = aws_lightsail_disk_attachment.data.instance_name == "AquaTidy" && output.instance_name == "AquaTidy"
    error_message = "Disk and deployment settings must target the existing AquaTidy instance."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.deploy.policy).Statement[0].Resource == var.existing_instance_arn
    error_message = "SSH access must be scoped to the existing instance's exact ARN."
  }
}

run "create_github_identity_provider" {
  command = plan
  variables {
    create_github_oidc_provider = true
    github_oidc_provider_arn    = null
  }
  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 1 && aws_iam_openid_connect_provider.github[0].url == "https://token.actions.githubusercontent.com" && toset(aws_iam_openid_connect_provider.github[0].client_id_list) == toset(["sts.amazonaws.com"])
    error_message = "Create the GitHub provider with the AWS STS audience."
  }
}
