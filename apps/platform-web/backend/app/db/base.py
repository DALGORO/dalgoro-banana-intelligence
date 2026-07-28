# app/db/base.py
from app.db.base_class import Base  # re-exporta Base

# Importa modelos para que Alembic/ORM los descubra
from app.models.user import User                # noqa: F401
from app.models.company import Company          # noqa: F401
from app.models.subscription import Subscription  # noqa: F401
from app.models.document import Document        # noqa: F401
from app.models.document_template import DocumentTemplate  # noqa: F401
from app.models.iperc_item import IPERCItem     # noqa: F401
