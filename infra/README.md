# GitHub Actions and AWS Lightsail

The workflow tests the bot on Python 3.10 and 3.12, validates and tests Terraform with a mocked AWS provider, runs ShellCheck, and builds Docker. Pull requests never publish or deploy. Successful builds on the repository's default branch publish `ghcr.io/michaelkema/aquatidybot:sha-COMMIT`. CD deploys the returned immutable digest using temporary Lightsail SSH credentials and GitHub OIDC.

Infrastructure is applied separately after reviewing a Terraform plan. The deployment role can request SSH access to this one instance; it cannot provision infrastructure. No AWS resources are created just by adding these files.

## Provision a managed Lightsail instance

Install Terraform 1.14+ and the AWS CLI, and authenticate to your AWS account locally. For a new deployment, the module provisions an Ubuntu 22.04 instance, static IP, SSH firewall rule, separate encrypted Lightsail data disk and GitHub deployment role. For your existing AquaTidy server, use the existing-instance section below. The instance and disk must share an availability zone. Choose your region, zone and bundle; you can list bundles and blueprints with `aws lightsail get-bundles` and `aws lightsail get-blueprints`.

If your account has no GitHub OIDC provider, set `create_github_oidc_provider = true` and leave `github_oidc_provider_arn` unset; Terraform creates it with audience `sts.amazonaws.com`. Otherwise, keep creation disabled and provide the existing provider ARN for `https://token.actions.githubusercontent.com`. The trust policy restricts access to this repository's `production` environment. If your repository uses customized or immutable-ID OIDC subjects, set `github_oidc_subject` to its exact claim. [GitHub's AWS OIDC documentation](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws) explains the claim formats.

```sh
cp infra/terraform.tfvars.example infra/terraform.tfvars
# Edit the values for your account, region, availability zone and bundle.
terraform -chdir=infra init
terraform -chdir=infra fmt -check
terraform -chdir=infra validate
terraform -chdir=infra test
terraform -chdir=infra plan -out=deployment.tfplan
terraform -chdir=infra apply deployment.tfplan
terraform -chdir=infra output
```

The example uses local state. For shared state, copy `backend.s3.tf.example` to `backend.tf` and configure an existing private, encrypted, versioned S3 bucket, then run `terraform init -migrate-state`. State, variables and plan files are ignored by Git. Keep state backups.

The only inbound port is SSH. The default allows TCP 22 from any IPv4 address because hosted GitHub runners have changing addresses; SSH still requires credentials. With a runner that has fixed egress, restrict `ssh_cidrs` to that range and update the workflow's runner. Password authentication should remain disabled. No web ports are needed for this bot.

## Configure GitHub CD

Create an environment named **production**, restricting deployment branches to the repository's default branch. The Terraform trust policy includes this environment name, so do not rename it without updating both configurations.

Set these **repository Actions variables** (the job's condition needs them before the environment loads):

| Variable | Value |
| --- | --- |
| `AWS_REGION` | Terraform `aws_region` output |
| `AWS_DEPLOY_ROLE_ARN` | Terraform `deploy_role_arn` output |
| `LIGHTSAIL_INSTANCE_NAME` | Terraform `instance_name` output |
| `REMINDER_TIMEZONE` | Optional default IANA name; defaults to UTC |

Set these **production environment secrets**:

| Secret | Value |
| --- | --- |
| `DISCORD_TOKEN` | Discord bot token, required |
| `GHCR_USERNAME` | Optional GitHub username for pulling a private image |
| `GHCR_READ_TOKEN` | Optional personal access token with `read:packages`, allowed to read this package |

GHCR packages initially may be private. Either make this bot's package public after the first publish or configure the two GHCR secrets. The runner publishes with its built-in `GITHUB_TOKEN`. A private host pull uses the supplied read token, which must remain valid for image recovery on a replacement instance. [GitHub documents the GHCR authentication and visibility requirements](https://docs.github.com/en/packages/working-with-the-container-registry/working-with-the-container-registry).

Push to the default branch or run **CI and CD** manually on that branch. Without the deployment role and instance variables, CI and image publishing work while deployment is skipped. The AWS CLI requests temporary SSH keys and trusted host keys through [Lightsail's access API](https://docs.aws.amazon.com/lightsail/2016-11-28/api-reference/API_InstanceAccessDetails.html). Private keys stay in a temporary runner directory. Strict host verification is enabled; secrets reach the host through encrypted SSH stdin, not Terraform or command arguments.

Allow the first bootstrap several minutes to install Docker and mount the disk. The deployment script waits for a ready marker. Its startup check verifies the container process stays running for 20 seconds, not a Discord login or successful reminder. Check the bot in Discord after the first deployment.

## Your existing AquaTidy instance

Your screenshot identifies **AquaTidy**, Ubuntu, **us-east-1a**, with a 512 MB plan and a 20 GB root disk. Its SSH user is `ubuntu`. Your CloudShell output confirms Ubuntu 24.04 (`ubuntu_24_04`) and bundle `nano_3_0`. Existing-instance mode does not need either value and keeps your current plan.

Use the supplied existing-instance example instead of the new-instance example:

```sh
# Only copy the template if you do not already have infra/terraform.tfvars.
# Your confirmed instance settings are already saved in that ignored local file.
cp -n infra/aquatidy-existing.tfvars.example infra/terraform.tfvars
aws lightsail get-instance --region us-east-1 --instance-name AquaTidy \
  --query 'instance.{arn:arn,blueprint:blueprintId,bundle:bundleId}'
aws lightsail get-disks --region us-east-1 \
  --query "disks[?attachedTo=='AquaTidy'].[name,path,sizeInGb]"
```

The public example uses a placeholder instance ARN. Your confirmed ARN is saved locally in the ignored `infra/terraform.tfvars`; keep this file private. Your CloudShell check returned no OIDC providers, so provider creation is enabled. Review the disk inventory before applying. This mode manages the GitHub OIDC provider, deployment IAM role and a **new 8 GB data disk attached to AquaTidy at /dev/xvdf**. It leaves the existing instance, firewall and IP outside Terraform management, so no instance import is needed. If that attachment path is already occupied or you already have a suitable data disk, resolve its ownership/association before applying this plan. The attached disk is additional storage, independent of the existing 20 GB root disk.

Run the init, validation and plan commands above, review the planned resources, then apply. Ensure your current Lightsail firewall permits SSH from the workflow runner; existing mode leaves those rules as they are. In GitHub, set `LIGHTSAIL_INSTANCE_NAME=AquaTidy` and `AWS_REGION=us-east-1`, plus the role ARN and secrets documented above. The workflow obtains the current IP from the Lightsail API rather than hardcoding the screenshot's address.

Existing instances do not execute new launch user data. Render and install the same bootstrap manually using your existing SSH access:

```sh
python infra/scripts/render_bootstrap.py --repository MichaelKema/AquaTidyBot > /tmp/aquatidy-bootstrap.sh
# Upload to AquaTidy over your existing SSH connection, then run as root.
```

The bootstrap uses Ubuntu's apt package manager and systemd and expects the dedicated disk at **/dev/xvdf**. It formats only a blank disk, preserves ext4, and refuses other filesystems or partitioned disks. Ensure this is the intended bot data disk before running it. Stop the current bot process before enabling CD. If it already uses SQLite, copy its database while stopped to `/var/lib/aquatidy/data/aquatidy.sqlite3` after mounting the disk. Older in-memory deployments need `!start` once per server after the upgrade. Image builds run on GitHub's runner, not on your 512 MB instance.

## Persistence, updates and recovery

SQLite lives at `/var/lib/aquatidy/data/aquatidy.sqlite3` on the attached disk, mounted into the container at `/data`. Image selection, bot environment and optional registry credentials also live on this root-only disk. [Lightsail encrypts attached disks and snapshots at rest](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-faq-block-storage.html).

The disk has `prevent_destroy`. Keep its resource block and Terraform state; removing the block removes that lifecycle protection. Before replacing an instance, stop the bot, snapshot the disk, and retain the disk in the same availability zone. The replacement bootstrap mounts it and pulls the saved image. The service refuses to run without the mount, avoiding accidental writes to an ephemeral root disk. The pipeline serializes deployments and the host also uses a deployment lock. Run only one bot process.

Each update pulls the image before stopping the current service. Startup failures restore the previous image and environment; this does not roll back database schema changes. For a manual rollback, rerun `aquatidy-deploy` with the earlier `ghcr.io/OWNER/REPO@sha256:DIGEST` and the same JSON secret payload on stdin through a trusted SSH session. Secrets should not appear in shell history.

Stop the service before making a disk snapshot for a consistent SQLite backup. A separate disk survives instance replacement; snapshots are needed to recover from disk loss or accidental file deletion. Restore snapshots in the same zone and update/import Terraform's disk association before mounting them. Changing disk size, zone, or instance configuration may require replacement; inspect every infrastructure plan. Decommission the instance separately from the retained disk.

On the host, inspect `sudo systemctl status aquatidy`, `sudo journalctl -u aquatidy`, `sudo docker logs aquatidy`, and `/var/log/cloud-init-output.log`. Deployment secrets and configuration files are root-only. Docker log rotation bounds local log growth.
