#!/bin/bash
docker exec -it talentscout-db psql -U postgres -d talentscout -c "DROP TABLE IF EXISTS messages, generated_questions, sessions, candidates CASCADE;"
python create_tables.py