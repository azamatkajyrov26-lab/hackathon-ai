#!/bin/sh
set -e

echo "=== SubsidyAI: Starting initialization ==="

# 1. Migrations
echo "[1/6] Running migrations..."
python manage.py migrate --noinput

# 2. Collect static files
echo "[2/6] Collecting static files..."
python manage.py collectstatic --noinput 2>/dev/null || true

# 3. Seed reference data (directions, subsidy types, budgets, demo users)
echo "[3/6] Seeding reference data..."
python manage.py seed_data

# 4. Generate emulated entities (500 synthetic farm entities with data from 7 systems)
echo "[4/6] Generating emulated entities..."
python manage.py generate_data --count 500 2>/dev/null || python manage.py generate_data

# 5. Create test applications and run scoring
echo "[5/6] Creating test applications..."
python manage.py create_test_applications --count 300 2>/dev/null || true

# 6. Train ML model
echo "[6/6] Training ML model..."
python manage.py train_model 2>/dev/null || true

echo "=== Initialization complete! ==="
echo ""
echo "Demo accounts (login / password):"
echo "  farmer1   / demo123     - Applicant (IIN: 880720300456)"
echo "  farmer2   / demo123     - Applicant (IIN: 901105200789)"
echo "  specialist / demo123    - MIO Specialist"
echo "  commission / demo123    - Commission Member"
echo "  head      / demo123     - MIO Head"
echo "  admin     / demo123     - Administrator"
echo "  auditor   / demo123     - Auditor"
echo ""
echo "ECP login (demo IINs):"
echo "  880720300456 - СПК Береке Астана (ОДОБРЕНИЕ)"
echo "  901105200789 - КХ Жумабаев (ОДОБРЕНИЕ)"
echo "  950315400123 - ИП Абрамова (ОТКАЗ)"
echo ""

# Start server
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
