"""Known swimwear stays available manually but is never an automatic default."""
AUTO_EXCLUDED = frozenset({'stand/1030230010', 'stand/1030240010'})
DAILY_DEFAULTS = {'hinana': 'stand/1040230010', 'nichika': 'stand/1030240020'}

def automatic_outfit(oid):
    return oid not in AUTO_EXCLUDED
