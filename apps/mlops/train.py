"""Train and track a small, reproducible regression example."""

import math
import os
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import mlflow


def wait_for_server():
    url = os.environ["MLFLOW_TRACKING_URI"].rstrip("/") + "/health"
    deadline = time.monotonic() + 300
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
                raise RuntimeError(f"Unexpected MLflow health status: {response.status}")
        except (urllib.error.URLError, TimeoutError) as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"MLflow did not become ready at {url}") from error
            print(f"Waiting for MLflow: {error}", flush=True)
            time.sleep(5)


def main():
    wait_for_server()
    seed = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
    rng = random.Random(seed)
    samples = []
    for _ in range(120):
        x = rng.uniform(-10, 10)
        samples.append((x, 3 * x + 7 + rng.gauss(0, 2)))
    train, test = samples[:100], samples[100:]
    mean_x = sum(x for x, _ in train) / len(train)
    mean_y = sum(y for _, y in train) / len(train)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in train) / sum(
        (x - mean_x) ** 2 for x, _ in train
    )
    intercept = mean_y - slope * mean_x

    def rmse(errors):
        return math.sqrt(sum(error**2 for error in errors) / len(errors))

    model_rmse = rmse([y - (slope * x + intercept) for x, y in test])
    baseline_rmse = rmse([y - mean_y for _, y in test])

    mlflow.set_experiment("synthetic-regression")
    with mlflow.start_run(run_name=f"linear-regression-{seed}"):
        mlflow.log_params({"seed": seed, "train_rows": len(train), "test_rows": len(test)})
        mlflow.log_metrics({"rmse": model_rmse, "baseline_rmse": baseline_rmse})
        mlflow.log_dict(
            {"type": "linear_regression", "slope": slope, "intercept": intercept},
            "model.json",
        )
        mlflow.log_dict(
            {
                "train": [{"x": x, "y": y} for x, y in train],
                "test": [{"x": x, "y": y} for x, y in test],
            },
            "dataset.json",
        )
        print(
            f"Logged run {mlflow.active_run().info.run_id}: "
            f"RMSE={model_rmse:.3f}, baseline RMSE={baseline_rmse:.3f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
