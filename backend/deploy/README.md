# Deployment Resources

This directory stores the experiment infrastructure's Compose templates, image build files, and maintenance scripts. When running experiments, use the unified entry point `backend/scripts/experiment.py`; you do not need to manually start the Gitea service here first. For complete steps, see [Quick Start](../../docs/QUICKSTART.md). All commands in this document are executed from the repository root.

## Directory Purposes

| Directory | Purpose |
| --- | --- |
| [`experiment/`](experiment/) | Infrastructure templates used by the local backend. Each run independently creates Gitea, a network, storage, and an egress proxy; when local project CI is enabled, the backend adds a dedicated runner and CI service. |
| [`gitea/`](gitea/) | A single-instance Gitea, Actions runner, and egress proxy for manual integration testing. It uses fixed container names, network names, and ports, making it suitable for maintenance but not for parallel experiments. |
| [`vigil/`](vigil/) | Image build files, container entrypoint, and evidence-reading capability records for the OpenAgents delivery environment. The unified entry point prepares the delivery environment according to the frozen source and runtime recipe. |
| [`swebench-seed/`](swebench-seed/) | Storage image and runtime environment recipe for SWE-bench task workspaces; it is not the initial Harness source code. The build scripts require prepared `workspace/` and `build-state.json`. |

The standalone Harness benchmark evaluation uses `evaluation.yaml` in the repository root. For instructions, see [Evaluation Guide](../../evaluation/docs/harbor.md).

## Experiment Deployment

The local backend automatically prepares local Gitea, generates accounts and credentials, and saves them to the run's private `secrets/` directory. When web access is needed, read the actual address from the run records; ports are managed by the experiment and are not fixed at 3000.

The E2B backend uses its own Gitea.com account to host repositories and does not start local Gitea. Model credentials, `E2B_API_KEY`, and `GITEA_TOKEN` are provided through the experiment credential file. For configuration fields, see [Experiment Configuration](../../docs/CONFIGURATION.md).

Local project CI is optional and is enabled through `runtime.local.ci_enabled`. The unified entry point prepares and verifies a dedicated runner for each run; it does not reuse the shared runner deployed manually below. For specific configuration, see [Local Project CI](../../docs/CONFIGURATION.md#local-engineering-ci).

## Model Egress and Evidence Access

The delivery environment for local experiments accesses model services through an egress proxy. The backend generates destination host and port rules according to the model endpoint in the configuration; there is no need to modify the static proxy template in the repository.

The static template used for manual deployment allows Anthropic and Claude services by default. When using another model gateway, you must explicitly modify the corresponding egress rules. Self-hosted Gitea uses gzip evidence attachments; Gitea.com uses ZIP attachments and its R2 download address. The delivery environment must support the corresponding retrieval protocol, and the unified entry point pre-checks the actual runtime environment before invoking the model.

When manual deployment needs to access Gitea.com evidence, set the following before starting Compose:

```bash
export AHE_BETA_EGRESS_CONFIG=./egress-gitea-com.conf
```

This configuration adds `gitea.com:443` and access permission for R2 hosts matching the rules to the basic egress rules; it does not open access to arbitrary external addresses.

## Manually Starting Gitea

The following steps are only for infrastructure integration testing. Docker Engine, Compose, Bash, and curl are required. The service uses SQLite and named data volumes, and the HTTP and SSH ports are bound only to localhost; this template does not include TLS or high-availability deployment configuration.

Start Gitea and the egress proxy first, then initialize the account, repository, and runner:

```bash
export GITEA_ADMIN_USER=aheadmin
export GITEA_ADMIN_EMAIL=aheadmin@example.com
read -rs -p "Gitea admin password: " GITEA_ADMIN_PASS
printf '\n'
export GITEA_ADMIN_PASS

(
  cd backend/deploy/gitea
  docker compose up -d gitea egress-proxy
  bash ./bootstrap.sh
)
unset GITEA_ADMIN_PASS
```

The Gitea address is `http://localhost:3000`, and the SSH port is `2222`. The initialization script waits for the service to be ready, creates an administrator, a private work repository, and labels, generates an access Token, and starts the Actions runner after obtaining a runner registration Token.

The script writes the connection information to `backend/deploy/gitea/.env`. The file permissions are `0600`, and the file is ignored by Git:

| Field | Meaning |
| --- | --- |
| `GITEA_URL` | Service root address, without a trailing slash or the `/api/v1` suffix |
| `OWNER` | Initialized administrator username |
| `REPO` | Work repository name, defaulting to `ahe-beta-work` |
| `TOKEN` | Access Token containing the `write:user`, `write:issue`, and `write:repository` permissions |
| `RUNNER_TOKEN` | Actions runner registration Token |

When run repeatedly, the script retains existing accounts and repositories and reuses the Token in `.env`; it does not update the passwords of existing accounts. The repository name and Token name can be set through `GITEA_WORK_REPO` and `GITEA_TOKEN_NAME`.

### Check Connection

The service version endpoint returns HTTP 200, indicating that Gitea is ready:

```bash
curl -fsS http://localhost:3000/api/v1/version
```

To check repository write permissions, you can create a test Issue:

```bash
(
  source backend/deploy/gitea/.env
  curl --fail-with-body -sS \
    -H "Authorization: token $TOKEN" \
    -H 'Content-Type: application/json' \
    -X POST "$GITEA_URL/api/v1/repos/$OWNER/$REPO/issues" \
    -d '{"title":"Connection check","body":"Manual deployment verification."}'
)
```

### Stop and Clean Up

Stop the service and retain the data:

```bash
docker compose -f backend/deploy/gitea/docker-compose.yml down
```

If reinitialization is needed, the command below also deletes the Gitea and runner data volumes, including accounts, repositories, Issues, and runner registration information:

```bash
docker compose -f backend/deploy/gitea/docker-compose.yml down -v
rm -f backend/deploy/gitea/.env
```

These commands manage only the manually deployed single instance. Experiments created by the unified entry point should be managed using the `stop` and `destroy` commands of `experiment.py`. For details, see [Quick Start](../../docs/QUICKSTART.md).
