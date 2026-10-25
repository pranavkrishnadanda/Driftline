from driftline.config import Settings
from driftline.gateway.app import create_app

app = create_app(Settings())
