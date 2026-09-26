"""Global cloud judgement switch for verified conversations."""



class PrivacyGate:
    def __init__(self, enabled: bool = True):
        self.set_cloud(enabled)

    def set_cloud(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("invalid_cloud_setting")
        self._enabled = enabled

    def allows_cloud(self) -> bool:
        return self._enabled
