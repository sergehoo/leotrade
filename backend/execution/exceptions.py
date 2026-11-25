class OrderRejected(Exception):
    def __init__(self, reason: str, decision=None):
        super().__init__(reason)
        self.decision = decision


class TradingDisabled(Exception):
    pass
