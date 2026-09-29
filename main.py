import time

import requests

from bot.config import settings
from bot.indicators import INTERVAL_MS
from bot.logger_setup import setup_logging
from bot.trader import Trader


def main() -> None:
    log = setup_logging(settings.log_level)

    if settings.mode_conflict:
        log.error("REAL_MONEY and PAPER_TRADING in your .env disagree. Delete the PAPER_TRADING "
                  "line and keep only REAL_MONEY=true or REAL_MONEY=false.")
        return
    if settings.strategy not in ("ema", "smc"):
        log.error("STRATEGY must be 'ema' or 'smc' (got '%s').", settings.strategy)
        return
    if settings.strategy == "smc" and settings.smc_timeframe not in INTERVAL_MS:
        log.error("SMC_TIMEFRAME must be one of %s (got '%s').",
                  ", ".join(INTERVAL_MS), settings.smc_timeframe)
        return

    if not settings.paper_trading and (not settings.api_key or not settings.api_secret):
        log.error("LIVE mode needs BITUNIX_API_KEY / BITUNIX_API_SECRET. Set them "
                  "(Railway variables or a local .env), or use REAL_MONEY=false.")
        return

    log.info("Starting bot | mode=%s strategy=%s symbol=%s margin_fraction=%.2f tp=%.3f%% sl=%.3f%% ladder=%s",
             "PAPER" if settings.paper_trading else "LIVE (REAL MONEY)", settings.strategy.upper(),
             settings.symbol, settings.margin_fraction, settings.tp_pct * 100,
             settings.sl_pct * 100, settings.leverage_ladder)

    if not settings.paper_trading:
        log.warning("!!! REAL_MONEY=true: this bot will place REAL orders with REAL money. "
                    "Starting in 10 seconds - press Ctrl+C now to cancel.")
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            log.info("Cancelled.")
            return

    backoff = 5
    while True:
        started = time.time()
        try:
            Trader(settings, log).run_forever()
        except SystemExit as e:
            log.error("Stopping: %s", e)
            break
        except KeyboardInterrupt:
            log.info("Interrupted by user, shutting down.")
            break
        except requests.exceptions.RequestException as e:
            # Network trouble: short one-line message, quick retry (state is saved).
            log.warning("Network problem (%s: %s). Retrying in 10s...", type(e).__name__, str(e)[:150])
            time.sleep(10)
            continue
        except Exception:
            if time.time() - started > 300:
                backoff = 5  # it ran fine for a while, so this is a fresh problem
            log.exception("Unhandled error in trading loop, restarting in %ss...", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
            continue
        else:
            break


if __name__ == "__main__":
    main()
