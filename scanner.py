from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
import json
import os
from dataclasses import asdict

import strategy
import weekly_detector
import weekly_pipeline
import h4_detector
from setup_engine import SetupEngine
from market_cache import MarketCache
from telegram_alerts import send_alert
from config import PAIRS, BE_PAIRS


STATE_FILE = "pipeline_state.json"


INDEX_PAIRS = {"SPX", "NDX"}
INDEX_PIP_SIZE = 0.1
XAU_PIP_SIZE = 50 / 55  # ~0.909, real SL distance (60x) = ~$54.55, corrected from old 0.01 (was producing a $0.60 SL, too tight, matched live)
BTC_PIP_SIZE = 500 / 60  # ~8.333, real SL distance (60x) = $500
ETH_PIP_SIZE = 50 / 55  # ~0.909, real SL distance (60x) = ~$54.55
XAG_PIP_SIZE = 0.001


def _pip_size(pair: str) -> float:
    p = pair.upper()
    if p in INDEX_PAIRS:
        return INDEX_PIP_SIZE
    if p in ("XAU/USD", "XAUUSD"):
        return XAU_PIP_SIZE
    if p in ("XAG/USD", "XAGUSD"):
        return XAG_PIP_SIZE
    if p in ("BTC/USD", "BTCUSD"):
        return BTC_PIP_SIZE
    if p in ("ETH/USD", "ETHUSD"):
        return ETH_PIP_SIZE
    return 0.01 if p.endswith("JPY") else 0.0001


def _last_weekly_candle_is_closed() -> bool:
    """
    Forex weekly candles close around Friday ~22:00 UTC. Treat Sat/Sun,
    or Friday after 22:00 UTC, as closed; anything else means the most
    recent weekly candle returned by the API is still forming.
    """
    now = datetime.now(timezone.utc)
    if now.weekday() in (5, 6):
        return True
    if now.weekday() == 4 and now.hour >= 22:
        return True
    return False


def _closed_weekly_candles(weekly):
    """Drop the last weekly candle if it hasn't closed yet."""
    if not weekly:
        return weekly
    if _last_weekly_candle_is_closed():
        return weekly
    return weekly[:-1]


@dataclass
class ScanResult:
    pair: str
    status: str
    setup: Optional[object] = None
    reason: str = ""


@dataclass
class PairState:
    stage: str = "AWAIT_WEEKLY_ZONE"
    direction: Optional[str] = None
    zone: Optional[object] = None
    weekly_confirmation_index: Optional[int] = None
    daily_liquidity: Optional[float] = None
    h4_confirmation_price: Optional[float] = None
    h4_notified: list = field(default_factory=list)


class ForexScanner:
    """
    V3 pipeline (executed in order, one stage advanced per scan cycle
    per pair, matching the Master Rulebook):

        Weekly key area
            -> Weekly engulfing confirmation
            -> Weekly body retest
            -> Daily liquidity sweep
            -> H4 confirmation
            -> Entry decision
            -> SL / 3R / 4R / BE
            -> Telegram alert

    Strategy rules remain inside strategy.py. This class only
    orchestrates the pipeline and holds per-pair progress in memory.
    """

    def __init__(self):
        self.cache = MarketCache()
        self.engine = SetupEngine()
        self.states = self._load_states()
        self._last_printed = {}

    def _notify_stage(self, pair: str, direction: str, new_stage: str, zone_kind: str = None, extra: str = ""):
        titles = {
            "AWAIT_WEEKLY_CONFIRMATION": ("Weekly key area found", "Watching for weekly engulfing confirmation."),
            "AWAIT_WEEKLY_RETEST": ("Weekly key-area confirmation", "Watching for retest into confirmation candle's body before moving to Daily."),
            "AWAIT_DAILY_LIQUIDITY": ("Weekly retest confirmed", "Watching Daily for a liquidity sweep."),
            "AWAIT_H4_CONFIRMATION": ("Daily liquidity swept", "Watching H4 for confirmation."),
        }
        if new_stage not in titles:
            return
        title, watching = titles[new_stage]
        dir_label = "(LONG)" if direction == "BUY" else "(SHORT)"
        zone_line = f"\nZone type: {zone_kind}" if zone_kind else ""
        extra_line = f"\n{extra}" if extra else ""
        message = f"{pair} \u2014 {title} {dir_label}{zone_line}\n{watching}{extra_line}"
        send_alert(message)

    def _notify_h4_progress(self, pair: str, state, signals: dict):
        dir_label = "(LONG)" if state.direction == "BUY" else "(SHORT)"
        checks = [
            ("liquidity_swept", "H4 liquidity taken", "Watching for displacement."),
            ("displacement", "H4 displacement candle detected", "Watching for market structure shift."),
        ]
        for key, title, watching in checks:
            if signals.get(key) and key not in state.h4_notified:
                state.h4_notified.append(key)
                send_alert(f"{pair} \u2014 {title} {dir_label}\n{watching}")

        structure_ok = signals.get("structure_1") and signals.get("structure_2")
        if structure_ok and "structure" not in state.h4_notified:
            state.h4_notified.append("structure")
            send_alert(f"{pair} \u2014 H4 structure shift confirmed {dir_label}\n"
                       f"Watching for a decisive close to complete entry.")

    def _load_states(self):
        states = {pair: PairState() for pair in PAIRS}
        if not os.path.exists(STATE_FILE):
            return states
        try:
            with open(STATE_FILE) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            return states
        for pair, data in raw.items():
            if pair not in states:
                continue
            zone_data = data.get("zone")
            data = dict(data)
            data["zone"] = strategy.Zone(**zone_data) if zone_data else None
            try:
                states[pair] = PairState(**data)
            except TypeError:
                pass
        return states

    def _save_states(self):
        raw = {pair: asdict(state) for pair, state in self.states.items()}
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(raw, f, indent=2)
        os.replace(tmp, STATE_FILE)

    def scan_pair(self, pair: str) -> ScanResult:
        state = self.states.setdefault(pair, PairState())

        try:
            weekly = self.cache.get_weekly(pair)
            daily = self.cache.get_daily(pair)
            h4 = self.cache.get_h4(pair)
        except Exception as exc:
            return ScanResult(pair=pair, status="ERROR", reason=str(exc))

        weekly = _closed_weekly_candles(weekly)

        if not weekly or not daily or not h4:
            return ScanResult(pair=pair, status="NO_SETUP", reason="Insufficient market data")

        pip_size = _pip_size(pair)
        current_price = weekly[-1].close

        # ---- Stage 1: Weekly key area -------------------------------
        if state.stage == "AWAIT_WEEKLY_ZONE":
            zones = weekly_detector.zones_at_price(weekly, current_price)
            if not zones:
                return ScanResult(pair=pair, status="NO_SETUP",
                                   reason="Waiting for price to return to a weekly key area")

            zone = zones[0]
            state.zone = zone
            state.direction = zone.direction
            state.stage = "AWAIT_WEEKLY_CONFIRMATION"
            self._notify_stage(pair, state.direction, state.stage, zone_kind=zone.kind)
            return ScanResult(pair=pair, status="STAGE_ADVANCED",
                               reason=f"Weekly {zone.kind} zone found, direction={zone.direction}")

        # ---- Stage 2: Weekly engulfing confirmation -----------------
        if state.stage == "AWAIT_WEEKLY_CONFIRMATION":
            if len(weekly) < 2:
                return ScanResult(pair=pair, status="NO_SETUP", reason="Not enough weekly candles")

            idx = len(weekly) - 1
            previous, current = weekly[idx - 1], weekly[idx]

            if self.engine.weekly_confirmation(previous, current, state.direction):
                state.weekly_confirmation_index = idx
                state.stage = "AWAIT_WEEKLY_RETEST"
                self._notify_stage(pair, state.direction, state.stage, zone_kind=state.zone.kind if state.zone else None)
                return ScanResult(pair=pair, status="STAGE_ADVANCED",
                                   reason="Weekly engulfing confirmation valid")

            return ScanResult(pair=pair, status="NO_SETUP",
                               reason="Waiting for weekly engulfing confirmation")

        # ---- Stage 3: Weekly body retest -----------------------------
        if state.stage == "AWAIT_WEEKLY_RETEST":
            idx = len(weekly) - 1
            if idx <= state.weekly_confirmation_index:
                return ScanResult(pair=pair, status="NO_SETUP",
                                   reason="Waiting for a new weekly candle to check retest")

            if weekly_pipeline.weekly_pipeline_ready(weekly, state.weekly_confirmation_index, current_price):
                state.stage = "AWAIT_DAILY_LIQUIDITY"
                self._notify_stage(pair, state.direction, state.stage, zone_kind=state.zone.kind if state.zone else None)
                return ScanResult(pair=pair, status="STAGE_ADVANCED",
                                   reason="Weekly body retest confirmed")

            return ScanResult(pair=pair, status="NO_SETUP",
                               reason="Waiting for weekly body retest")

        # ---- Stage 4: Daily liquidity sweep --------------------------
        if state.stage == "AWAIT_DAILY_LIQUIDITY":
            liquidity = strategy.structural_liquidity(daily, state.direction)
            if liquidity is not None:
                state.daily_liquidity = liquidity
                state.stage = "AWAIT_H4_CONFIRMATION"
                state.h4_notified = []
                self._notify_stage(pair, state.direction, state.stage, zone_kind=state.zone.kind if state.zone else None, extra=f"Level: {liquidity:.5f}")
                return ScanResult(pair=pair, status="STAGE_ADVANCED",
                                   reason=f"Daily liquidity swept at {liquidity}")

            return ScanResult(pair=pair, status="NO_SETUP",
                               reason="Waiting for daily liquidity sweep")

        # ---- Stage 5: H4 confirmation ---------------------------------
        if state.stage == "AWAIT_H4_CONFIRMATION":
            idx = len(h4) - 1
            signals = h4_detector.detect_h4_confirmation(h4, state.daily_liquidity, state.direction, idx)

            if "liquidity_swept" not in signals:
                return ScanResult(pair=pair, status="NO_SETUP",
                                   reason=signals.get("reason", "Insufficient H4 candles"))

            self._notify_h4_progress(pair, state, signals)

            confirmed = self.engine.h4_confirmation(
                direction=state.direction,
                liquidity_swept=signals["liquidity_swept"],
                displacement=signals["displacement"],
                structure_1=signals["structure_1"],
                structure_2=signals["structure_2"],
                decisive_close=signals["decisive_close"],
            )

            if confirmed:
                state.h4_confirmation_price = signals["confirmation_price"]
                state.stage = "TRADE_READY"
                return ScanResult(pair=pair, status="STAGE_ADVANCED",
                                   reason="H4 confirmation valid")

            return ScanResult(pair=pair, status="NO_SETUP",
                               reason="Waiting for H4 confirmation")

        # ---- Stage 6 & 7: Entry decision, SL/targets, alert -----------
        if state.stage == "TRADE_READY":
            liquidity_level = state.daily_liquidity
            confirmation_price = state.h4_confirmation_price

            action = strategy.entry_distance_action(liquidity_level, confirmation_price, pip_size)
            if action == "ENTER":
                entry = confirmation_price
            else:
                entry = strategy.capped_retrace_entry(liquidity_level, state.direction, pip_size)

            stop_loss = strategy.calculate_stop_loss(state.daily_liquidity, state.direction, pip_size)
            target_3r, target_4r, breakeven = strategy.calculate_targets(entry, stop_loss, state.direction)

            setup = strategy.Setup(
                direction=state.direction,
                weekly_zone=state.zone,
                daily_liquidity=state.daily_liquidity,
                entry=entry,
                stop_loss=stop_loss,
                target_3R=target_3r,
                target_4R=target_4r,
                breakeven_at=breakeven,
                status=action,
            )

            message = self._format_alert(pair, setup)
            send_alert(message)

            self.states[pair] = PairState()

            return ScanResult(pair=pair, status="TRADE_READY", setup=setup,
                               reason=f"Alert sent ({action})")

        return ScanResult(pair=pair, status="ERROR", reason=f"Unknown stage: {state.stage}")

    def _format_alert(self, pair: str, setup) -> str:
        arrow = "\U0001F7E2 BUY" if setup.direction == "BUY" else "\U0001F534 SELL"
        use_be = BE_PAIRS.get(pair, True)
        lines = [
            f"*{arrow} SETUP \u2014 {pair}*",
            "",
        ]
        if not use_be:
            lines.append("\u26A0\uFE0F *DO NOT MOVE STOP TO BREAKEVEN ON THIS PAIR* \u26A0\uFE0F")
            lines.append("_5yr backtest data shows running full SL-to-target performs better on this pair._")
            lines.append("")
        lines += [
            f"Action: *{setup.status}*",
            f"Entry (daily liquidity): `{setup.entry:.5f}`",
            f"Stop Loss: `{setup.stop_loss:.5f}`",
        ]
        if use_be:
            lines.append(f"Breakeven (1R): `{setup.breakeven_at:.5f}` \u2705 _move stop here once price hits 1R_")
        else:
            lines.append(f"(Reference only, 1R level): `{setup.breakeven_at:.5f}` \u26A0\uFE0F _do NOT use as breakeven_")
        lines += [
            f"Target 3R: `{setup.target_3R:.5f}`",
            f"Target 4R: `{setup.target_4R:.5f}`",
            f"Weekly zone: `{setup.weekly_zone.kind}` [{setup.weekly_zone.low:.5f} - {setup.weekly_zone.high:.5f}]",
        ]
        if setup.status == "RETRACE_ZONE":
            lines.append("")
            lines.append("_Entry is more than 55 pips from confirmation \u2014 wait for retracement before entering._")
        return "\n".join(lines)

    def scan_all(self):
        results = []
        changed_count = 0
        for pair in PAIRS:
            result = self.scan_pair(pair)
            results.append(result)

            key = (result.status, result.reason)
            if self._last_printed.get(pair) != key:
                self._last_printed[pair] = key
                changed_count += 1
                if result.status == "ERROR":
                    print(f"[ERROR] {pair}: {result.reason}")
                else:
                    print(f"[{result.status}] {pair} - {result.reason}")

        if changed_count == 0:
            print("(no changes this cycle)")

        self._save_states()

        return results


def main():
    print("\n=== FOREX SCANNER V3 ===")
    print("Full pipeline test\n")

    scanner = ForexScanner()
    results = scanner.scan_all()

    ready = sum(r.status == "TRADE_READY" for r in results)
    errors = sum(r.status == "ERROR" for r in results)

    print("\n================================")
    print(f"Pairs processed : {len(results)}")
    print(f"Setups found    : {ready}")
    print(f"Errors          : {errors}")
    print("================================")


if __name__ == "__main__":
    main()
