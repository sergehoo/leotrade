class WalletProviderRegistry:
    PROVIDERS = {}

    @classmethod
    def register(cls, code, provider_cls):
        cls.PROVIDERS[code] = provider_cls

    @classmethod
    def get(cls, code):
        provider_cls = cls.PROVIDERS.get(code)
        if not provider_cls:
            raise ValueError(f"Provider non supporté: {code}")
        return provider_cls()