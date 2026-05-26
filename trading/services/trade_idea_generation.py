from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from strategies.models import Signal, Strategy
from trading.models import TradeIdea
from trading.services.market_scanner import MarketScannerService
from trading.services.opportunity_scoring import OpportunityScoringService

class TradeIdeaGenerationService:
    MIN_OVERALL_SCORE = 0.65

    @staticmethod
    def _get_or_create_strategy(asset, timeframe):
        strategy = (
            Strategy.objects.filter(
                asset=asset,
                timeframe=timeframe,
                is_active=True,
            )
            .exclude(status__in=["ARCHIVED", "FAILED", "PAUSED"])
            .order_by("-allow_live_execution", "-is_autonomous", "name")
            .first()
        )

        if strategy:
            return strategy

        return Strategy.objects.create(
            name=f"Auto {asset.symbol} {timeframe.code}",
            strategy_type="HYBRID",
            status="PAPER",
            asset=asset,
            timeframe=timeframe,
            is_active=True,
            is_autonomous=False,
            allow_live_execution=False,
            run_interval_seconds=max((getattr(timeframe, "minutes", 5) or 5) * 60, 60),
            min_confidence_threshold=0.0,
            risk_per_trade_percent=1.0,
            parameters={
                "source": "TradeIdeaGenerationService",
                "auto_created": True,
                "atr_stop_mult": 1.5,
                "atr_tp_mult": 3.0,
            },
            description="Stratégie auto-générée pour supporter la création de TradeIdea.",
        )
    @staticmethod
    def _to_decimal(value, default: str = "0") -> Decimal:
        try:
            if value is None or value == "":
                return Decimal(default)
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(default)

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_minutes_from_timeframe(timeframe) -> int:
        if timeframe is None:
            return 5

        minutes = getattr(timeframe, "minutes", None)
        if isinstance(minutes, int) and minutes > 0:
            return minutes

        code = getattr(timeframe, "code", None) or str(timeframe)
        code = (code or "").strip().lower()

        mapping = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
        }
        return mapping.get(code, 5)

    @staticmethod
    def _signal_side_from_direction(direction: str) -> str:
        if direction in ["BUY", "CALL"]:
            return "BUY"
        if direction in ["SELL", "PUT"]:
            return "SELL"
        return "HOLD"

    @staticmethod
    def _find_strategy(asset, timeframe):
        return (
            Strategy.objects.filter(
                asset=asset,
                timeframe=timeframe,
                is_active=True,
            )
            .exclude(status__in=["ARCHIVED", "FAILED", "PAUSED"])
            .order_by("-allow_live_execution", "-is_autonomous", "name")
            .first()
        )

    @classmethod
    def build_explanation(
        cls,
        symbol: str,
        timeframe: str,
        direction: str,
        scores: dict,
        features: dict,
    ) -> str:
        reasons = []

        rsi = features.get("rsi_14")
        macd = features.get("macd")
        macd_signal = features.get("macd_signal")
        sma_20 = features.get("sma_20")
        sma_50 = features.get("sma_50")
        close = features.get("close")

        try:
            if close is not None and sma_20 is not None and sma_50 is not None:
                close_v = float(close)
                sma20_v = float(sma_20)
                sma50_v = float(sma_50)

                if close_v > sma20_v > sma50_v:
                    reasons.append("tendance haussière confirmée par les moyennes mobiles")
                elif close_v < sma20_v < sma50_v:
                    reasons.append("tendance baissière confirmée par les moyennes mobiles")
        except Exception:
            pass

        try:
            if macd is not None and macd_signal is not None:
                macd_v = float(macd)
                macd_signal_v = float(macd_signal)

                if macd_v > macd_signal_v:
                    reasons.append("MACD au-dessus de sa ligne signal")
                elif macd_v < macd_signal_v:
                    reasons.append("MACD sous sa ligne signal")
        except Exception:
            pass

        try:
            if rsi is not None:
                rsi_v = float(rsi)
                if rsi_v > 55:
                    reasons.append("RSI orienté vers un momentum acheteur")
                elif rsi_v < 45:
                    reasons.append("RSI orienté vers un momentum vendeur")
        except Exception:
            pass

        return (
            f"Trade idea détectée sur {symbol} ({timeframe}) avec biais {direction}. "
            f"Confiance={float(scores.get('confidence_score', 0)):.2f}, "
            f"setup={float(scores.get('setup_score', 0)):.2f}, "
            f"risque={float(scores.get('risk_score', 0)):.2f}, "
            f"potentiel={float(scores.get('reward_score', 0)):.2f}. "
            f"Raisons principales : "
            f"{', '.join(reasons) if reasons else 'configuration technique favorable'}."
        )

    @classmethod
    def compute_levels(
        cls,
        direction: str,
        close: float | int | Decimal,
        atr: float | int | Decimal | None,
    ) -> tuple[Decimal, Decimal, Decimal, float]:
        close_dec = cls._to_decimal(close, default="0")
        atr_dec = cls._to_decimal(atr, default="0.001")

        if atr_dec <= 0:
            atr_dec = Decimal("0.001")

        if direction in ["BUY", "CALL"]:
            entry = close_dec
            stop = close_dec - (atr_dec * Decimal("1.5"))
            take = close_dec + (atr_dec * Decimal("3.0"))
        else:
            entry = close_dec
            stop = close_dec + (atr_dec * Decimal("1.5"))
            take = close_dec - (atr_dec * Decimal("3.0"))

        risk = abs(entry - stop)
        reward = abs(take - entry)
        expected_rr = float(reward / risk) if risk else 0.0

        return entry, stop, take, expected_rr

    @classmethod
    @transaction.atomic
    def generate(cls, timeframe_code: str | None = None, user=None) -> list[TradeIdea]:
        if user is None:
            raise ValueError("TradeIdeaGenerationService.generate requiert un user non nul.")

        scan_run, rows = MarketScannerService.scan(timeframe_code=timeframe_code or "5m")
        if scan_run is None:
            raise ValueError("MarketScannerService.scan a retourné un scan_run nul.")

        ideas: list[TradeIdea] = []

        for row in rows:
            asset = row.get("asset")
            timeframe = row.get("timeframe")
            features = row.get("features") or {}
            market_snapshot = row.get("market_snapshot") or {}

            if not asset or not timeframe or not isinstance(features, dict):
                continue

            strategy = cls._get_or_create_strategy(asset, timeframe)
            if strategy is None:
                continue

            scores = OpportunityScoringService.score(features) or {}
            overall_score = cls._safe_float(scores.get("overall_score", 0), 0.0)

            if overall_score < cls.MIN_OVERALL_SCORE:
                continue

            direction = OpportunityScoringService.choose_direction(features)
            signal_side = cls._signal_side_from_direction(direction)

            timeframe_code_value = getattr(timeframe, "code", None) or "5m"
            timeframe_minutes = cls._safe_minutes_from_timeframe(timeframe)

            entry, stop, take, expected_rr = cls.compute_levels(
                direction=direction,
                close=features.get("close") or 0,
                atr=features.get("atr_14"),
            )

            symbol = getattr(asset, "symbol", "") or ""

            explanation = cls.build_explanation(
                symbol=symbol or "UNKNOWN",
                timeframe=timeframe_code_value,
                direction=direction,
                scores=scores,
                features=features,
            )

            expires_at = timezone.now() + timezone.timedelta(minutes=timeframe_minutes * 3)
            candle_time = (
                features.get("candle_time")
                or market_snapshot.get("candle_time")
                or market_snapshot.get("open_time")
            )

            if candle_time is None:
                candle_time = timezone.now()

            already_exists = TradeIdea.objects.filter(
                user=user,
                scan_run=scan_run,
                asset=asset,
                timeframe=timeframe,
                direction=direction,
                status="NEW",
            ).exists()

            if already_exists:
                continue

            signal = Signal.objects.create(
                strategy=strategy,
                strategy_run=None,
                candle_time=candle_time,
                side=signal_side,
                confidence=cls._safe_float(scores.get("confidence_score", 0), 0.0),
                price=entry,
                stop_loss=stop,
                take_profit=take,
                reason=explanation,
                features_snapshot=features,
                model_output={
                    "source": "TradeIdeaGenerationService",
                    "scan_run_id": scan_run.id if scan_run else None,
                    "timeframe_code": timeframe_code_value,
                    "overall_score": overall_score,
                    "setup_score": cls._safe_float(scores.get("setup_score", 0), 0.0),
                    "risk_score": cls._safe_float(scores.get("risk_score", 0), 0.0),
                    "reward_score": cls._safe_float(scores.get("reward_score", 0), 0.0),
                    "symbol": symbol,
                    "direction": direction,
                    "user_id": user.id,
                },
                expires_at=expires_at,
                status="NEW",
            )

            idea = TradeIdea.objects.create(
                user=user,
                scan_run=scan_run,
                asset=asset,
                timeframe=timeframe,
                strategy=strategy,
                signal=signal,
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                stop_loss=stop,
                take_profit=take,
                horizon_minutes=timeframe_minutes * 4,
                expected_rr=expected_rr,
                confidence_score=cls._safe_float(scores.get("confidence_score", 0), 0.0),
                setup_score=cls._safe_float(scores.get("setup_score", 0), 0.0),
                risk_score=cls._safe_float(scores.get("risk_score", 0), 0.0),
                reward_score=cls._safe_float(scores.get("reward_score", 0), 0.0),
                overall_score=overall_score,
                market_snapshot=market_snapshot,
                features_snapshot=features,
                explanation=explanation,
                ai_payload={
                    "scanner": "MarketScannerService",
                    "scorer": "OpportunityScoringService",
                    "timeframe_code": timeframe_code_value,
                    "user_id": user.id,
                    "signal_id": signal.id,
                    "strategy_id": strategy.id,
                },
                status="NEW",
                expires_at=expires_at,
            )
            ideas.append(idea)

        update_fields = []

        if hasattr(scan_run, "idea_count"):
            scan_run.idea_count = len(ideas)
            update_fields.append("idea_count")

        if hasattr(scan_run, "payload"):
            current_payload = getattr(scan_run, "payload", None) or {}
            current_payload["generated_ideas"] = len(ideas)
            current_payload["user_id"] = user.id
            current_payload["timeframe_code"] = timeframe_code or "5m"
            scan_run.payload = current_payload
            update_fields.append("payload")

        if hasattr(scan_run, "updated_at"):
            update_fields.append("updated_at")

        if update_fields:
            scan_run.save(update_fields=update_fields)

        return ideas
# class TradeIdeaGenerationService:
#     MIN_OVERALL_SCORE = 0.65
#
#     @staticmethod
#     def _to_decimal(value, default: str = "0") -> Decimal:
#         try:
#             if value is None or value == "":
#                 return Decimal(default)
#             return Decimal(str(value))
#         except (InvalidOperation, TypeError, ValueError):
#             return Decimal(default)
#
#     @staticmethod
#     def _safe_minutes_from_timeframe(timeframe) -> int:
#         """
#         Supporte plusieurs formats de timeframe :
#         - objet avec champ minutes
#         - objet avec code ('1m', '5m', '1h', ...)
#         """
#         if timeframe is None:
#             return 5
#
#         minutes = getattr(timeframe, "minutes", None)
#         if isinstance(minutes, int) and minutes > 0:
#             return minutes
#
#         code = getattr(timeframe, "code", None) or str(timeframe)
#         code = (code or "").strip().lower()
#
#         mapping = {
#             "1m": 1,
#             "5m": 5,
#             "15m": 15,
#             "30m": 30,
#             "1h": 60,
#             "4h": 240,
#             "1d": 1440,
#         }
#         return mapping.get(code, 5)
#
#     @classmethod
#     def build_explanation(
#         cls,
#         symbol: str,
#         timeframe: str,
#         direction: str,
#         scores: dict,
#         features: dict,
#     ) -> str:
#         reasons = []
#
#         rsi = features.get("rsi_14")
#         macd = features.get("macd")
#         macd_signal = features.get("macd_signal")
#         sma_20 = features.get("sma_20")
#         sma_50 = features.get("sma_50")
#         close = features.get("close")
#
#         try:
#             if close is not None and sma_20 is not None and sma_50 is not None:
#                 close_v = float(close)
#                 sma20_v = float(sma_20)
#                 sma50_v = float(sma_50)
#
#                 if close_v > sma20_v > sma50_v:
#                     reasons.append("tendance haussière confirmée par les moyennes mobiles")
#                 elif close_v < sma20_v < sma50_v:
#                     reasons.append("tendance baissière confirmée par les moyennes mobiles")
#         except Exception:
#             pass
#
#         try:
#             if macd is not None and macd_signal is not None:
#                 macd_v = float(macd)
#                 macd_signal_v = float(macd_signal)
#
#                 if macd_v > macd_signal_v:
#                     reasons.append("MACD au-dessus de sa ligne signal")
#                 elif macd_v < macd_signal_v:
#                     reasons.append("MACD sous sa ligne signal")
#         except Exception:
#             pass
#
#         try:
#             if rsi is not None:
#                 rsi_v = float(rsi)
#                 if rsi_v > 55:
#                     reasons.append("RSI orienté vers un momentum acheteur")
#                 elif rsi_v < 45:
#                     reasons.append("RSI orienté vers un momentum vendeur")
#         except Exception:
#             pass
#
#         return (
#             f"Trade idea détectée sur {symbol} ({timeframe}) avec biais {direction}. "
#             f"Confiance={float(scores.get('confidence_score', 0)):.2f}, "
#             f"setup={float(scores.get('setup_score', 0)):.2f}, "
#             f"risque={float(scores.get('risk_score', 0)):.2f}, "
#             f"potentiel={float(scores.get('reward_score', 0)):.2f}. "
#             f"Raisons principales : "
#             f"{', '.join(reasons) if reasons else 'configuration technique favorable'}."
#         )
#
#     @classmethod
#     def compute_levels(
#         cls,
#         direction: str,
#         close: float | int | Decimal,
#         atr: float | int | Decimal | None,
#     ) -> tuple[Decimal, Decimal, Decimal, float]:
#         close_dec = cls._to_decimal(close, default="0")
#         atr_dec = cls._to_decimal(atr, default="0.001")
#
#         if atr_dec <= 0:
#             atr_dec = Decimal("0.001")
#
#         if direction in ["BUY", "CALL"]:
#             entry = close_dec
#             stop = close_dec - (atr_dec * Decimal("1.5"))
#             take = close_dec + (atr_dec * Decimal("3.0"))
#         else:
#             entry = close_dec
#             stop = close_dec + (atr_dec * Decimal("1.5"))
#             take = close_dec - (atr_dec * Decimal("3.0"))
#
#         risk = abs(entry - stop)
#         reward = abs(take - entry)
#         expected_rr = float(reward / risk) if risk else 0.0
#
#         return entry, stop, take, expected_rr
#
#     @classmethod
#     def generate(cls, timeframe_code: str | None = None, user=None) -> list[TradeIdea]:
#         if user is None:
#             raise ValueError("TradeIdeaGenerationService.generate requiert un user non nul.")
#         scan_run, rows = MarketScannerService.scan(timeframe_code=timeframe_code or "5m")
#         ideas: list[TradeIdea] = []
#
#         for row in rows:
#             asset = row.get("asset")
#             timeframe = row.get("timeframe")
#             features = row.get("features") or {}
#             market_snapshot = row.get("market_snapshot") or {}
#
#             if not asset or not timeframe or not isinstance(features, dict):
#                 continue
#
#             scores = OpportunityScoringService.score(features) or {}
#
#             overall_score = float(scores.get("overall_score", 0) or 0)
#             if overall_score < cls.MIN_OVERALL_SCORE:
#                 continue
#
#             direction = OpportunityScoringService.choose_direction(features)
#             timeframe_code_value = getattr(timeframe, "code", None) or "5m"
#             timeframe_minutes = cls._safe_minutes_from_timeframe(timeframe)
#
#             entry, stop, take, expected_rr = cls.compute_levels(
#                 direction=direction,
#                 close=features.get("close") or 0,
#                 atr=features.get("atr_14"),
#             )
#
#             explanation = cls.build_explanation(
#                 symbol=getattr(asset, "symbol", "UNKNOWN"),
#                 timeframe=timeframe_code_value,
#                 direction=direction,
#                 scores=scores,
#                 features=features,
#             )
#
#             idea = TradeIdea.objects.create(
#                 user=user,
#                 scan_run=scan_run,
#                 asset=asset,
#                 timeframe=timeframe,
#                 symbol=getattr(asset, "symbol", ""),
#                 direction=direction,
#                 entry_price=entry,
#                 stop_loss=stop,
#                 take_profit=take,
#                 horizon_minutes=timeframe_minutes * 4,
#                 expected_rr=expected_rr,
#                 confidence_score=scores.get("confidence_score", 0) or 0,
#                 setup_score=scores.get("setup_score", 0) or 0,
#                 risk_score=scores.get("risk_score", 0) or 0,
#                 reward_score=scores.get("reward_score", 0) or 0,
#                 overall_score=scores.get("overall_score", 0) or 0,
#                 market_snapshot=market_snapshot,
#                 features_snapshot=features,
#                 explanation=explanation,
#                 ai_payload={
#                     "scanner": "MarketScannerService",
#                     "scorer": "OpportunityScoringService",
#                     "timeframe_code": timeframe_code_value,
#                 },
#                 status="NEW",
#                 expires_at=timezone.now() + timezone.timedelta(minutes=timeframe_minutes * 3),
#             )
#             ideas.append(idea)
#
#         update_fields = []
#
#         if hasattr(scan_run, "idea_count"):
#             scan_run.idea_count = len(ideas)
#             update_fields.append("idea_count")
#
#         if hasattr(scan_run, "payload"):
#             current_payload = getattr(scan_run, "payload", None) or {}
#             current_payload["generated_ideas"] = len(ideas)
#             scan_run.payload = current_payload
#             update_fields.append("payload")
#
#         if hasattr(scan_run, "updated_at"):
#             update_fields.append("updated_at")
#
#         if update_fields:
#             scan_run.save(update_fields=update_fields)
#
#         return ideas