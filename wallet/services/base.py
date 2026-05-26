class BaseWalletProvider:
    provider_code = None

    def create_deposit_intent(self, *, wallet, amount, currency, **kwargs):
        raise NotImplementedError

    def create_payout(self, *, wallet, amount, currency, destination, **kwargs):
        raise NotImplementedError

    def verify_webhook(self, request):
        raise NotImplementedError

    def parse_webhook_event(self, request):
        raise NotImplementedError