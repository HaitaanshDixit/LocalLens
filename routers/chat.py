"""
from fastapi import APIRouter
from schemas import ChatRequest, ChatResponse
from services.rag_service import ask

router = APIRouter(prefix="/chat", tags=["RAG Chat"])


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest):
    result = ask(query=req.query, active_city=req.city)
    return ChatResponse(**result)
"""

from fastapi import APIRouter, Response
from schemas import ChatRequest, ChatResponse
from services.rag_service import ask_cached

router = APIRouter(prefix="/chat", tags=["RAG Chat"])


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, response: Response):
    # debugging the input 
    print("QUERY:", req.query)
    print("CITY:", req.city)

    result, cache_hit = ask_cached(query=req.query, active_city=req.city)
    response.headers["X-Cache"] = "HIT" if cache_hit else "MISS"

    # debugging the output
    print("RAG RESULT:", result)

    return ChatResponse(**result)