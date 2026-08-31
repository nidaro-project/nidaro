"""Complete the SQLAlchemy mapper registry for standalone processes.

The app composition root imports every domain package, so the registry is
whole there. A standalone process (seed, one-off scripts) may import only a
slice — and Event carries a foreign key to `sources`, so a partial import
breaks flush-time mapper sorting. Importing this module loads every model;
call `ensure_full_metadata` before touching the database.
"""

from nidaro.calendar import models as calendar_models
from nidaro.commitments import models as commitments_models
from nidaro.connectors import models as connectors_models
from nidaro.connectors.google_calendar import models as google_calendar_models
from nidaro.connectors.whatsapp import models as whatsapp_models
from nidaro.conversations import models as conversations_models
from nidaro.db.base import Base
from nidaro.household import models as household_models
from nidaro.jobs import models as jobs_models
from nidaro.meals import models as meals_models
from nidaro.memory import models as memory_models
from nidaro.sources import models as sources_models
from nidaro.tasks import models as tasks_models

_MODEL_MODULES = (
    calendar_models,
    commitments_models,
    connectors_models,
    conversations_models,
    google_calendar_models,
    household_models,
    jobs_models,
    meals_models,
    memory_models,
    sources_models,
    tasks_models,
    whatsapp_models,
)


def ensure_full_metadata() -> list[str]:
    """Return the mapped table names after every model module is loaded."""
    return sorted(Base.metadata.tables)
