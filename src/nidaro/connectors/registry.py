from nidaro.connectors.base import Connector


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.name] = connector

    def get(self, name: str) -> Connector:
        try:
            return self._connectors[name]
        except KeyError as error:
            raise KeyError(f"Unknown connector: {name}") from error

    def names(self) -> list[str]:
        return sorted(self._connectors)
