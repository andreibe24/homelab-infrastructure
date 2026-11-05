import importlib.util
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch


mlflow = MagicMock()
with patch.dict(sys.modules, {"mlflow": mlflow}):
    spec = importlib.util.spec_from_file_location("train", Path(__file__).with_name("train.py"))
    train = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(train)


class TrainingTests(unittest.TestCase):
    def setUp(self):
        mlflow.reset_mock()

    @patch.object(train, "wait_for_server")
    def test_logs_reproducible_model_dataset_and_held_out_metrics(self, _wait):
        with patch.object(train, "datetime") as date:
            date.now.return_value.strftime.return_value = "20261031"
            train.main()
            first_artifacts = list(mlflow.log_dict.call_args_list)
            train.main()

        self.assertEqual(first_artifacts, mlflow.log_dict.call_args_list[2:])
        mlflow.set_experiment.assert_called_with("synthetic-regression")
        self.assertEqual(mlflow.log_params.call_args.args[0]["seed"], 20261031)
        metrics = mlflow.log_metrics.call_args.args[0]
        self.assertLess(metrics["rmse"], metrics["baseline_rmse"])
        model = first_artifacts[0].args[0]
        dataset = first_artifacts[1].args[0]
        self.assertEqual(first_artifacts[0].args[1], "model.json")
        self.assertEqual(first_artifacts[1].args[1], "dataset.json")
        self.assertEqual((len(dataset["train"]), len(dataset["test"])), (100, 20))
        self.assertAlmostEqual(model["slope"], 3, delta=0.2)
        self.assertAlmostEqual(model["intercept"], 7, delta=1)

    @patch.dict(os.environ, {"MLFLOW_TRACKING_URI": "http://mlflow:5000"})
    @patch.object(train.time, "monotonic", side_effect=[0, 301])
    @patch.object(train.urllib.request, "urlopen", side_effect=urllib.error.URLError("unavailable"))
    def test_server_timeout_is_an_error(self, _urlopen, _clock):
        with self.assertRaisesRegex(RuntimeError, "did not become ready"):
            train.wait_for_server()


if __name__ == "__main__":
    unittest.main()
