from fastapi import FastAPI, HTTPException, Query, Depends, status, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import csv
import logging
import os
import asyncpg
import io
import json
import jwt
from passlib.context import CryptContext
from jwt.exceptions import InvalidTokenError
from error_handler import ErrorHandler
from dotenv import load_dotenv
import httpx

# Load environment variables
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Database credentials
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST")

# Perplexity Configuration
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
# Valid Perplexity Sonar models (current, unprefixed)
PERPLEXITY_ALLOWED_MODELS = {
    "sonar",
    "sonar-mini",
    "sonar-small",
    "sonar-medium",
    "sonar-pro",
    "sonar-reasoning",
    "sonar-reasoning-pro",
}
_env_model = os.getenv("PERPLEXITY_MODEL", "sonar-pro")
PERPLEXITY_MODEL = _env_model if _env_model in PERPLEXITY_ALLOWED_MODELS else "sonar-pro"

# Authentication Configuration
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

logging.info(f"Perplexity API Key loaded: {'Exists' if PERPLEXITY_API_KEY else 'Not Found'}")
if _env_model not in PERPLEXITY_ALLOWED_MODELS:
    logging.warning(
        f"Invalid PERPLEXITY_MODEL '{_env_model}'. Falling back to 'sonar-pro'. "
        f"Allowed: {sorted(PERPLEXITY_ALLOWED_MODELS)}"
    )
logging.info(f"Perplexity model: {PERPLEXITY_MODEL}")

app = FastAPI()

class UserQuery(BaseModel):
    workflow_id: int
    query_text: str

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

@app.get("/")
def root():
    return RedirectResponse("/static/index.html")

# Startup/shutdown
@app.on_event("startup")
async def startup():
    app.state.db_pool = None
    try:
        if DB_USER and DB_PASSWORD and DB_NAME and DB_HOST:
            app.state.db_pool = await asyncpg.create_pool(
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                host=DB_HOST,
                port=5432,
            )
            logging.info("Database connection pool created.")
        else:
            logging.warning("Database environment variables missing. Starting without DB connection.")
    except Exception as e:
        logging.error(f"Failed to create DB pool: {str(e)}. Starting without DB connection.")
        app.state.db_pool = None
    app.state.error_handler = ErrorHandler(app.state.db_pool)

@app.on_event("shutdown")
async def shutdown():
    if getattr(app.state, "db_pool", None):
        await app.state.db_pool.close()
        logging.info("Database connection pool closed.")



async def query_perplexity_model(prompt: str, api_key: str, model_name: str, error_handler: ErrorHandler, workflow_id: Optional[int] = None):
    try:
        if not api_key:
            raise ValueError("Perplexity API key not provided.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant. Respond concisely."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Perplexity API HTTP {resp.status_code}: {resp.text}")
            data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Perplexity API returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        return content, None
    except Exception as e:
        error_message = f"Perplexity API error: {str(e)}"
        if workflow_id:
            await error_handler.log_error(workflow_id, "API_Error", error_message)
        logging.error(error_message)
        return None, error_message



# DB test endpoint
@app.get("/test_db_connection")
async def test_db_connection():
    try:
        if not app.state.db_pool:
            return {"status": "error", "message": "Database not configured"}
        conn = await app.state.db_pool.acquire()
        await app.state.db_pool.release(conn)
        return {"status": "success", "message": "Database connection is working!"}
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}


# Workflows endpoint
@app.get("/workflows")
async def get_workflows(skip: int = 0, limit: int = 50):
    if not app.state.db_pool:
        raise HTTPException(status_code=503, detail="Database not configured")
    async with app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT workflow_id, workflow_name, status, schedule FROM workflows ORDER BY workflow_id OFFSET $1 LIMIT $2",
            skip, limit
        )
        return [dict(row) for row in rows]

# Logs endpoint
@app.get("/workflows/{workflow_id}/logs")
async def get_logs(workflow_id: int, skip: int = 0, limit: int = 50):
    if not app.state.db_pool:
        raise HTTPException(status_code=503, detail="Database not configured")
    async with app.state.db_pool.acquire() as conn:
        logs = await conn.fetch(
            "SELECT log_id, log_message, error_type, timestamp FROM error_logs WHERE workflow_id=$1 ORDER BY timestamp DESC OFFSET $2 LIMIT $3",
            workflow_id, skip, limit
        )
        if not logs:
            raise HTTPException(status_code=404, detail="No logs found for this workflow")
        return [dict(log) for log in logs]

# List all logs
@app.get("/list-logs")
async def list_all_logs():
    try:
        if not app.state.db_pool:
            return {"status": "error", "message": "Database not configured"}
        async with app.state.db_pool.acquire() as conn:
            logs = await conn.fetch("SELECT log_id, workflow_id, log_message, error_type, timestamp FROM error_logs ORDER BY timestamp DESC")
            if not logs:
                return {"status": "info", "message": "No error logs found in the database."}
            return {"status": "success", "logs": [dict(log) for log in logs]}
    except Exception as e:
        logging.error(f"Failed to list logs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# Query endpoint for workflows with Perplexity
@app.post("/query")
async def query_llm_with_workflow(user_query: UserQuery):
    logging.info(f"Received query for workflow_id: {user_query.workflow_id}")
    if not app.state.db_pool:
        raise HTTPException(status_code=503, detail="Database not configured")
    async with app.state.db_pool.acquire() as conn:
        workflow = await conn.fetchrow("SELECT workflow_name FROM workflows WHERE workflow_id=$1", user_query.workflow_id)
        if not workflow:
            logging.error("Workflow not found")
            raise HTTPException(status_code=404, detail="Workflow not found")
        workflow_name = workflow['workflow_name']

        logs = await conn.fetch(
            "SELECT log_id, log_message, error_type, timestamp FROM error_logs WHERE workflow_id=$1 ORDER BY timestamp DESC LIMIT 5",
            user_query.workflow_id
        )

    logs_list = [dict(log) for log in logs] if logs else []
    logs_text = "\n".join(log["log_message"] for log in logs) if logs else "No recent logs available."
    logging.info(f"Fetched {len(logs_list)} error logs from PostgreSQL for prompt assembly")

    prompt = (
        f"Workflow Name: {workflow_name}\n"
        f"Recent Logs:\n{logs_text}\n\n"
        f"User Query: {user_query.query_text}\n\n"
        "Analyze the user query based on the provided logs. "
        "IMPORTANT: You must respond ONLY with a raw JSON object. "
        "Do not include json code blocks, introductory text, or any explanations. "
        "Your entire response must start with a curly brace '{' and end with one '}'. "
        "The JSON object must have these exact keys: 'transformation_rules', 'error_analysis', and 'suggested_fixes'."
    )
    answer, error_info = await query_perplexity_model(
        prompt,
        api_key=PERPLEXITY_API_KEY,
        model_name=PERPLEXITY_MODEL,
        error_handler=app.state.error_handler,
        workflow_id=user_query.workflow_id
    )

    logging.info(f"Raw AI answer: {answer}")

    if not answer:
        raise HTTPException(status_code=500, detail=error_info)

    try:
        structured_response = json.loads(answer)
        response = {
            "transformation_rules": structured_response.get("transformation_rules", "No rules generated"),
            "error_analysis": structured_response.get("error_analysis", "No analysis available"),
            "suggested_fixes": structured_response.get("suggested_fixes", []),
            "logs": logs_list
        }
    except json.JSONDecodeError:
        response = {
            "transformation_rules": "No rules generated",
            "error_analysis": "Parsing error",
            "suggested_fixes": [],
            "logs": logs_list
        }

    if error_info:
        response["error_info"] = error_info
        response["has_error"] = True

    return response


@app.post("/query-llm")
async def query_llm_route(user_input: dict):
    prompt = user_input.get("prompt")
    workflow_id = user_input.get("workflow_id")

    if not prompt:
        raise HTTPException(status_code=400, detail="Missing prompt")
    answer, error_info = await query_perplexity_model(
        prompt,
        api_key=PERPLEXITY_API_KEY,
        model_name=PERPLEXITY_MODEL,
        error_handler=app.state.error_handler,
        workflow_id=workflow_id
    )

    response = {"answer": answer}
    if error_info:
        response["error_analysis"] = error_info
        response["has_error"] = True

    return response


@app.get("/workflows/{workflow_id}/logs/download")
async def download_error_logs(workflow_id: int):
    if not app.state.db_pool:
        raise HTTPException(status_code=503, detail="Database not configured")
    async with app.state.db_pool.acquire() as conn:
        logs = await conn.fetch("SELECT timestamp, error_type, log_message FROM error_logs WHERE workflow_id=$1 ORDER BY timestamp DESC", workflow_id)
        if not logs:
            raise HTTPException(status_code=404, detail="No error logs found")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Timestamp", "Error Type", "Log Message"])
        for log in logs:
            writer.writerow([log["timestamp"], log["error_type"], log["log_message"]])
        output.seek(0)

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=workflow_{workflow_id}_error_logs.csv"}
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Backend healthy", "timestamp": datetime.now().isoformat()}