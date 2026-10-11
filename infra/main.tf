locals {
  github_oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.github_oidc_provider_arn
  use_existing_instance    = var.existing_instance_name != null
  instance_name            = local.use_existing_instance ? var.existing_instance_name : aws_lightsail_instance.bot[0].name
  instance_arn             = local.use_existing_instance ? var.existing_instance_arn : aws_lightsail_instance.bot[0].arn
}

resource "aws_lightsail_instance" "bot" {
  count             = local.use_existing_instance ? 0 : 1
  name              = var.name
  availability_zone = var.availability_zone
  blueprint_id      = "ubuntu_22_04"
  bundle_id         = var.bundle_id
  user_data = templatefile("${path.module}/cloud-init.sh.tftpl", {
    repository    = lower(var.github_repository)
    deploy_script = file("${path.module}/scripts/deploy.sh")
    run_script    = file("${path.module}/scripts/run.sh")
  })
  tags = { Project = var.name }
}

resource "aws_lightsail_instance_public_ports" "bot" {
  count         = local.use_existing_instance ? 0 : 1
  instance_name = local.instance_name
  port_info {
    from_port = 22
    to_port   = 22
    protocol  = "tcp"
    cidrs     = var.ssh_cidrs
  }
}

resource "aws_lightsail_static_ip" "bot" {
  count = local.use_existing_instance ? 0 : 1
  name  = "${var.name}-ip"
}
resource "aws_lightsail_static_ip_attachment" "bot" {
  count          = local.use_existing_instance ? 0 : 1
  static_ip_name = aws_lightsail_static_ip.bot[0].name
  instance_name  = local.instance_name
}

resource "aws_lightsail_disk" "data" {
  name              = "${var.name}-data"
  availability_zone = var.availability_zone
  size_in_gb        = var.data_disk_size
  tags              = { Project = var.name }
  lifecycle {
    prevent_destroy = true
  }
}
resource "aws_lightsail_disk_attachment" "data" {
  disk_name     = aws_lightsail_disk.data.name
  instance_name = local.instance_name
  disk_path     = "/dev/xvdf"
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  tags           = { Project = var.name }
}

resource "aws_iam_role" "deploy" {
  name = "${var.name}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = coalesce(var.github_oidc_subject, "repo:${var.github_repository}:environment:production")
        }
      }
    }]
  })
}
resource "aws_iam_role_policy" "deploy" {
  role = aws_iam_role.deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lightsail:GetInstanceAccessDetails"]
      Resource = local.instance_arn
    }]
  })
}
