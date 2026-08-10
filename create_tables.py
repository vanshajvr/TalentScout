from db.database import engine
from db.models import Base

Base.metadata.create_all(engine)
print("Tables created:", list(Base.metadata.tables.keys()))