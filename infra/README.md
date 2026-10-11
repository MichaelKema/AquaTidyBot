# GitHub Actions and AWS Lightsail

The workflow tests the bot on Python 3.10 and 3.12, validates and tests Terraform with a mocked AWS provider, runs ShellCheck, and builds Docker. Pull requests never publish or deploy. Successful builds on the repository's default branch publish `ghcr.io/michaelkema/aquatidybot:sha-COMMIT`. CD deploys the returned immutable digest using temporary Lightsail SSH credentials and GitHub OIDC.

Infrastructure is applied separately after reviewing a Terraform plan. The deployment role can request SSH access to this one instance; it cannot provision infrastructure. No AWS resources are created just by adding these files.

## Provision a managed Lightsail instance

Install Terraform 1.14+ and the AWS CLI, and authenticate to your AWS account locally. For a new deployment, the module provisions an Ubuntu 22.04 instance, static IP, SSH firewall rule and GitHub deployment role. For your existing AquaTidy server, use the existing-instance section below. Choose your region, zone and bundle; you can list bundles and blueprints with `aws lightsail get-bundles` and `aws lightsail get-blueprints`.

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

The committed provider lock file includes checksums for Apple Silicon macOS and the Linux x86_64 GitHub runner. When upgrading providers, regenerate both platform hashes before pushing:

```sh
terraform -chdir=infra providers lock -platform=darwin_arm64 -platform=linux_amd64
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
| `DISCORD_TOKEN` | Required for a fresh host; optional afterward (reuse the token saved on the host) |
| `GHCR_USERNAME` | Optional GitHub username for pulling a private image |
| `GHCR_READ_TOKEN` | Optional personal access token with `read:packages`, allowed to read this package |

GHCR packages initially may be private. Either make this bot's package public after the first publish or configure the two GHCR secrets. The runner publishes with its built-in `GITHUB_TOKEN`. A private host pull uses the supplied read token, which must remain valid for image recovery on a replacement instance. [GitHub documents the GHCR authentication and visibility requirements](https://docs.github.com/en/packages/working-with-the-container-registry/working-with-the-container-registry).

Push to the default branch or run **CI and CD** manually on that branch. Without the deployment role and instance variables, CI and image publishing work while deployment is skipped. The AWS CLI requests temporary SSH keys and trusted host keys through [Lightsail's access API](https://docs.aws.amazon.com/lightsail/2016-11-28/api-reference/API_InstanceAccessDetails.html). Private keys stay in a temporary runner directory. Strict host verification is enabled; secrets reach the host through encrypted SSH stdin, not Terraform or command arguments.

Allow the first bootstrap several minutes to install Docker and create the host data directory. The deployment script waits for a ready marker. Its startup check verifies the container process stays running for 20 seconds, not a Discord login or successful reminder. Check the bot in Discord after the first deployment.

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

The public example uses a placeholder instance ARN. Keep your actual settings in the ignored `infra/terraform.tfvars`. Existing-instance mode manages the deployment IAM role and optionally the GitHub OIDC provider. It leaves the instance, firewall and IP outside Terraform management. SQLite uses the existing root disk, so new installations provision no additional disk.

An earlier deployment provisioned an unused `aquatidy-data` disk. The local settings retain it with `retain_legacy_data_disk = true`, pending a reviewed detach/delete operation. Terraform moved blocks preserve its existing state addresses. Do not remove its resource blocks or local state as a shortcut to cleanup.

Run the init, validation and plan commands above, review the planned resources, then apply. Ensure your current Lightsail firewall permits SSH from the workflow runner; existing mode leaves those rules as they are. In GitHub, set `LIGHTSAIL_INSTANCE_NAME=AquaTidy` and `AWS_REGION=us-east-1`, plus the role ARN and secrets documented above. The workflow obtains the current IP from the Lightsail API rather than hardcoding the screenshot's address.

Existing instances do not execute new launch user data. Render and install the same bootstrap manually using your existing SSH access:

```sh
python infra/scripts/render_bootstrap.py --repository MichaelKema/AquaTidyBot > /tmp/aquatidy-bootstrap.sh
# Upload to AquaTidy over your existing SSH connection, then run as root.
```

The bootstrap uses Ubuntu's apt package manager and systemd. It creates `/var/lib/aquatidy/data` on the existing root disk and installs the `aquatidy` service and daily backup timer. It does not format or mount an extra disk. Pull the image before stopping the old bot, then deploy with the token read on the host. Disable the old service only after confirming the new bot has connected. Run only one bot process. Older in-memory deployments need `!start #channel America/New_York` once per server after the upgrade. Use your preferred IANA timezone. Image builds run on GitHub's runner, not the 512 MB instance.

## Persistence, updates and recovery

SQLite lives at `/var/lib/aquatidy/data/aquatidy.sqlite3`, mounted into the container at `/data`. Replacing the container or restarting the service preserves this file. Image selection, bot environment and optional registry credentials also live under `/var/lib/aquatidy`, with access restricted to root. An empty deployment token reuses the saved host token; provide `DISCORD_TOKEN` to initialize a fresh server or rotate it.

The `aquatidy-backup.timer` runs daily and after a missed scheduled run. The script uses SQLite's online backup API, checks integrity, compresses the result and removes backups older than seven days. Backups live at `/var/lib/aquatidy/backups`. Run `sudo /usr/local/bin/aquatidy-backup` to create one immediately. These local backups protect against database mistakes; they do not survive loss of the whole instance disk. Copy backups to separate storage or retain Lightsail instance snapshots before replacing the server. Provisioning a replacement instance alone does not restore the database or token.

Each update pulls an immutable image before stopping the current service. Startup failures restore the previous image and environment; this does not roll back database schema changes. The workflow serializes deployments and the host uses a deployment lock. The deployment check verifies that the container stays running for 20 seconds; check Discord login and reminder configuration after initial deployment.

For recovery, stop `aquatidy`, decompress a verified backup to `/var/lib/aquatidy/data/aquatidy.sqlite3`, remove stale `-wal` and `-shm` files while the service is stopped, and start the service. Keep the saved image and environment files, or initialize the replacement host with the token over trusted SSH. Do not put tokens in shell history or Terraform variables/state.

On the host, inspect `sudo systemctl status aquatidy`, `sudo journalctl -u aquatidy`, `sudo docker logs aquatidy`, and `sudo systemctl status aquatidy-backup.timer`. Docker log rotation bounds local log growth. Review every Terraform plan before applying infrastructure changes.
