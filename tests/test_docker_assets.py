from pathlib import Path


def test_docker_compose_defines_postgres_api_and_worker_services():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "postgres:" in compose
    assert "api:" in compose
    assert "worker:" in compose
    assert "postgresql+psycopg://notify_user:notify_password@postgres:5432/notify_db" in compose
    assert "python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000" in compose
    assert "python -m src.app.worker_runner" in compose
    assert "healthcheck:" in compose


def test_dockerfile_runs_api_package():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:" in dockerfile
    assert "pip install" in dockerfile
    assert "requirements.txt" in dockerfile
    assert "uvicorn" in dockerfile


def test_postgres_concurrency_script_documents_success_criteria():
    script = Path("scripts/postgres_concurrency_check.py").read_text(encoding="utf-8")

    assert "DATABASE_URL" in script
    assert "ThreadPoolExecutor" in script
    assert "duplicate" in script.lower()
    assert "FOR UPDATE SKIP LOCKED" in script
