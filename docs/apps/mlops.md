# MLflow experiment tracking

This installs a single-node MLflow tracking server and a small working training
pipeline, rather than a collection of idle platforms. The initial Kubernetes
Job trains a linear regression on synthetic data; a CronJob repeats it at
02:00 UTC every day. Each run records the random seed, dataset sizes, held-out
RMSE, a mean-prediction baseline RMSE, the generated dataset and a portable
`model.json` containing the learned slope and intercept. The seed is the UTC
date, so reruns on the same day are reproducible. These are demonstration data
and a simple JSON model, not a production model, MLflow Model Registry entry,
or a claim about real-world performance.

The shared apps root enables this on dev; it will also deploy on homelab when
its currently suspended apps root is enabled. Both need a default
ReadWriteOnce StorageClass and enough resources to run MLflow and the training
job. Homelab requires its documented storage, networking and other
prerequisites first. The server and training pods opt out of Linkerd injection;
their traffic is plaintext. There is no public route or authentication.
The namespace's standard ingress policy also allows gateway and monitoring
namespaces, so treat those and the `mlops` namespace as trusted. Do not expose
the server externally or send sensitive datasets to it without adding
authentication, TLS, appropriate network restrictions and backup.

## Try it

After Flux reconciles, check the server and the initial run:

```sh
kubectl -n mlops rollout status deployment/mlflow
kubectl -n mlops wait --for=condition=complete job/mlops-training-initial --timeout=10m
kubectl -n mlops logs job/mlops-training-initial
kubectl -n mlops port-forward service/mlflow 5000:5000
```

Open `http://localhost:5000`, select the `synthetic-regression` experiment and
compare the metrics and artifacts across runs. Download `model.json` and use
`prediction = slope * x + intercept`. To trigger another run without waiting
for the schedule:

```sh
kubectl -n mlops create job --from=cronjob/mlops-training training-manual-$(date +%s)
kubectl -n mlops get jobs
kubectl -n mlops logs job/<job-name>
```

Manual Jobs are not owned by the CronJob and must be deleted explicitly when
no longer needed. The initial Job is managed by Flux and stays completed;
changing the script does not rerun it. New scheduled or manually created Jobs
use the current ConfigMap script. Inspect failed Jobs and pod events with
`kubectl -n mlops describe job <job-name>` and `kubectl -n mlops logs job/<job-name>`.
MLflow startup is allowed five minutes before a training attempt fails; failed
Jobs retry up to their configured limit. If the initial Job exhausts its retries,
fix the underlying issue, then delete `job/mlops-training-initial`; Flux will
recreate it on reconciliation.

## Connect a real workflow

From a workload in `mlops`, use `MLFLOW_TRACKING_URI=http://mlflow:5000`
and an MLflow client compatible with the server. Create a separate experiment,
log the data/version identifiers and parameters, evaluate against a held-out
dataset, and log metrics and model artifacts using `mlflow.log_*`. The server
proxies artifact uploads, so clients need no PVC mount. Review data retention,
authorization and model promotion before using real or sensitive data. This
example's JSON artifact is not directly loadable with `mlflow.pyfunc.load_model`;
use MLflow's model logging APIs for deployable models.

The server stores both SQLite metadata and artifacts on the 5 GiB
`mlflow-data` PVC. It has one replica and uses the Recreate strategy because
SQLite and this volume are not a high-availability backend. Back up both the
database and artifacts together with the server stopped or using a
storage-consistent snapshot, and test restores. Removing the Flux-managed PVC
can destroy experiment data depending on the StorageClass reclaim policy;
back it up before removal or cluster teardown. Monitor free space and prune
old runs deliberately. For multiple users or production-scale training,
replace this setup with authenticated access, a managed SQL database, object
storage, backup, and appropriate availability controls.

Spark, Airflow and RabbitMQ are intentionally not deployed yet: add them when
there is a concrete distributed processing, dependency orchestration or
messaging workload. The CronJob already provides simple scheduled execution.
