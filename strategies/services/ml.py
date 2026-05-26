# strategies/ml.py
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


class StrategyModelServiceError(Exception):
    pass


class BaseModelAdapter:
    LABEL_MAP = {
        1: "BUY",
        -1: "SELL",
        0: "HOLD",
        "1": "BUY",
        "-1": "SELL",
        "0": "HOLD",
        "BUY": "BUY",
        "SELL": "SELL",
        "HOLD": "HOLD",
    }

    def __init__(self, model: Any, model_path: str):
        self.model = model
        self.model_path = model_path

    def get_feature_names(self) -> list[str] | None:
        if hasattr(self.model, "feature_names_in_"):
            return list(self.model.feature_names_in_)
        return None

    def map_prediction_label(self, raw_pred: Any) -> str:
        return self.LABEL_MAP.get(raw_pred, "HOLD")

    def predict(self, X: pd.DataFrame) -> dict[str, Any]:
        raise NotImplementedError


class SklearnLikeAdapter(BaseModelAdapter):
    def predict(self, X: pd.DataFrame) -> dict[str, Any]:
        raw_pred = self.model.predict(X)[0]

        probabilities = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
        if hasattr(self.model, "predict_proba"):
            try:
                proba = self.model.predict_proba(X)[0]
                classes = getattr(self.model, "classes_", [])
                for cls, p in zip(classes, proba):
                    mapped = self.map_prediction_label(cls)
                    probabilities[mapped] = float(p)
            except Exception:
                pass

        side = self.map_prediction_label(raw_pred)
        confidence = float(max(probabilities.values())) if any(probabilities.values()) else 0.0

        return {
            "backend": "sklearn_like",
            "raw_prediction": raw_pred,
            "side": side,
            "confidence": confidence,
            "probabilities": probabilities,
        }


class XGBoostAdapter(BaseModelAdapter):
    def predict(self, X: pd.DataFrame) -> dict[str, Any]:
        raw_pred = self.model.predict(X)[0]
        probabilities = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}

        if hasattr(self.model, "predict_proba"):
            try:
                proba = self.model.predict_proba(X)[0]
                classes = getattr(self.model, "classes_", [])
                for cls, p in zip(classes, proba):
                    probabilities[self.map_prediction_label(cls)] = float(p)
            except Exception:
                pass

        side = self.map_prediction_label(raw_pred)
        confidence = float(max(probabilities.values())) if any(probabilities.values()) else 0.0

        return {
            "backend": "xgboost",
            "raw_prediction": raw_pred,
            "side": side,
            "confidence": confidence,
            "probabilities": probabilities,
        }


class LightGBMAdapter(BaseModelAdapter):
    def predict(self, X: pd.DataFrame) -> dict[str, Any]:
        raw_pred = self.model.predict(X)[0]

        probabilities = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
        if isinstance(raw_pred, (list, np.ndarray)) and len(np.array(raw_pred).shape) > 0:
            arr = np.array(raw_pred).flatten()
            if len(arr) == 3:
                probabilities["SELL"] = float(arr[0])
                probabilities["HOLD"] = float(arr[1])
                probabilities["BUY"] = float(arr[2])
                side = max(probabilities, key=probabilities.get)
                confidence = float(max(probabilities.values()))
                return {
                    "backend": "lightgbm",
                    "raw_prediction": raw_pred,
                    "side": side,
                    "confidence": confidence,
                    "probabilities": probabilities,
                }

        mapped = self.map_prediction_label(raw_pred)
        return {
            "backend": "lightgbm",
            "raw_prediction": raw_pred,
            "side": mapped,
            "confidence": 0.0,
            "probabilities": probabilities,
        }


class CatBoostAdapter(BaseModelAdapter):
    def predict(self, X: pd.DataFrame) -> dict[str, Any]:
        raw_pred = self.model.predict(X)[0]
        if isinstance(raw_pred, (list, np.ndarray)):
            raw_pred = raw_pred[0]

        probabilities = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
        try:
            proba = self.model.predict_proba(X)[0]
            classes = getattr(self.model, "classes_", [])
            for cls, p in zip(classes, proba):
                probabilities[self.map_prediction_label(cls)] = float(p)
        except Exception:
            pass

        side = self.map_prediction_label(raw_pred)
        confidence = float(max(probabilities.values())) if any(probabilities.values()) else 0.0

        return {
            "backend": "catboost",
            "raw_prediction": raw_pred,
            "side": side,
            "confidence": confidence,
            "probabilities": probabilities,
        }


class PyTorchAdapter(BaseModelAdapter):
    def __init__(self, model: Any, model_path: str):
        super().__init__(model, model_path)
        try:
            import torch
            self.torch = torch
        except Exception as exc:
            raise StrategyModelServiceError("PyTorch n'est pas disponible.") from exc

    def predict(self, X: pd.DataFrame) -> dict[str, Any]:
        torch = self.torch
        self.model.eval()

        with torch.no_grad():
            tensor = torch.tensor(X.values.astype(np.float32))
            output = self.model(tensor)

            if hasattr(output, "detach"):
                output = output.detach().cpu().numpy()

            output = np.array(output)
            if output.ndim == 2:
                output = output[0]

            probabilities = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}

            if len(output) == 3:
                exp = np.exp(output - np.max(output))
                probs = exp / exp.sum()
                probabilities["SELL"] = float(probs[0])
                probabilities["HOLD"] = float(probs[1])
                probabilities["BUY"] = float(probs[2])
                side = max(probabilities, key=probabilities.get)
                confidence = float(max(probabilities.values()))
                raw_prediction = int(np.argmax(probs))
            else:
                raw_prediction = float(output[0]) if len(output) else 0.0
                side = "BUY" if raw_prediction > 0 else "SELL" if raw_prediction < 0 else "HOLD"
                confidence = abs(float(raw_prediction))

        return {
            "backend": "pytorch",
            "raw_prediction": raw_prediction,
            "side": side,
            "confidence": confidence,
            "probabilities": probabilities,
        }


class TensorFlowAdapter(BaseModelAdapter):
    def __init__(self, model: Any, model_path: str):
        super().__init__(model, model_path)
        try:
            import tensorflow as tf
            self.tf = tf
        except Exception as exc:
            raise StrategyModelServiceError("TensorFlow n'est pas disponible.") from exc

    def predict(self, X: pd.DataFrame) -> dict[str, Any]:
        output = self.model.predict(X.values, verbose=0)
        output = np.array(output)

        if output.ndim == 2:
            output = output[0]

        probabilities = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}

        if len(output) == 3:
            probabilities["SELL"] = float(output[0])
            probabilities["HOLD"] = float(output[1])
            probabilities["BUY"] = float(output[2])
            side = max(probabilities, key=probabilities.get)
            confidence = float(max(probabilities.values()))
            raw_prediction = int(np.argmax(output))
        else:
            raw_prediction = float(output[0]) if len(output) else 0.0
            side = "BUY" if raw_prediction > 0 else "SELL" if raw_prediction < 0 else "HOLD"
            confidence = abs(float(raw_prediction))

        return {
            "backend": "tensorflow",
            "raw_prediction": raw_prediction,
            "side": side,
            "confidence": confidence,
            "probabilities": probabilities,
        }


class StrategyModelService:
    def __init__(self, model_path: str, backend: str | None = None):
        self.model_path = model_path
        self.backend = backend
        self.model = self._load_model(model_path, backend)
        self.adapter = self._build_adapter()

    def _load_model(self, model_path: str, backend: str | None):
        path = Path(model_path)
        if not path.exists():
            raise StrategyModelServiceError(f"Modèle introuvable: {model_path}")

        if backend == "tensorflow":
            try:
                import tensorflow as tf
                return tf.keras.models.load_model(path)
            except Exception as exc:
                raise StrategyModelServiceError(f"Chargement TensorFlow impossible: {exc}") from exc

        if backend == "pytorch":
            try:
                import torch
                model = torch.load(path, map_location="cpu")
                return model
            except Exception as exc:
                raise StrategyModelServiceError(f"Chargement PyTorch impossible: {exc}") from exc

        try:
            return joblib.load(path)
        except Exception as exc:
            raise StrategyModelServiceError(f"Impossible de charger le modèle: {exc}") from exc

    def _detect_backend(self) -> str:
        if self.backend:
            return self.backend.lower()

        module = self.model.__class__.__module__.lower()
        cls_name = self.model.__class__.__name__.lower()

        if "xgboost" in module or "xgb" in cls_name:
            return "xgboost"
        if "lightgbm" in module or "lgbm" in cls_name:
            return "lightgbm"
        if "catboost" in module or "catboost" in cls_name:
            return "catboost"
        if "torch" in module:
            return "pytorch"
        if "keras" in module or "tensorflow" in module:
            return "tensorflow"

        return "sklearn"

    def _build_adapter(self) -> BaseModelAdapter:
        backend = self._detect_backend()

        if backend == "xgboost":
            return XGBoostAdapter(self.model, self.model_path)
        if backend == "lightgbm":
            return LightGBMAdapter(self.model, self.model_path)
        if backend == "catboost":
            return CatBoostAdapter(self.model, self.model_path)
        if backend == "pytorch":
            return PyTorchAdapter(self.model, self.model_path)
        if backend == "tensorflow":
            return TensorFlowAdapter(self.model, self.model_path)

        return SklearnLikeAdapter(self.model, self.model_path)

    def _normalize_features(self, features: dict[str, Any]) -> dict[str, float]:
        if not isinstance(features, dict):
            raise StrategyModelServiceError("Les features doivent être un dictionnaire.")

        normalized = {}
        for key, value in features.items():
            try:
                normalized[key] = float(value)
            except (TypeError, ValueError) as exc:
                raise StrategyModelServiceError(
                    f"Feature invalide '{key}' avec valeur '{value}'."
                ) from exc
        return normalized

    def _build_dataframe(self, features: dict[str, Any]) -> pd.DataFrame:
        normalized = self._normalize_features(features)
        feature_names = self.adapter.get_feature_names()

        if feature_names:
            missing = [f for f in feature_names if f not in normalized]
            if missing:
                raise StrategyModelServiceError(
                    f"Features manquantes: {', '.join(missing)}"
                )
            ordered = {name: normalized.get(name, 0.0) for name in feature_names}
            return pd.DataFrame([ordered])

        return pd.DataFrame([normalized])

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        X = self._build_dataframe(features)

        try:
            result = self.adapter.predict(X)
        except Exception as exc:
            raise StrategyModelServiceError(f"Erreur de prédiction: {exc}") from exc

        result["features_used"] = X.columns.tolist()
        result["model_path"] = self.model_path
        return result