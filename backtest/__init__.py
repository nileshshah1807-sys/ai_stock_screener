"""Point-in-time backtest engine for Model 5.0 (P0 validation).

This package is deliberately separate from :mod:`screener`. The production
screener answers "what looks good today"; this package answers "what would the
model have said on a past date, using only what was knowable then". The two have
opposite requirements around caching and data recency, and mixing them is how
look-ahead bias gets in.

Nothing here may import live-quote helpers from :mod:`screener.data_collection`.
Every price this package uses comes from an archived exchange file for the date
being simulated.
"""
